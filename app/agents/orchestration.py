"""Contrato estruturado da primeira orquestração sequencial de MORPHEUS.

O LLM pode produzir o plano, mas o runtime valida estruturalmente antes de
executar qualquer etapa — mesmo princípio de app/chat/action_dispatcher.py
(ExcelGeneratedContent): JSON fechado, rejeição total se inválido.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    ValidationError,
    field_validator,
)

from app.agents.execution import AgentExecutionService
from app.agents.models import AgentStatus
from app.agents.runtime import MORPHEUS_IDENTITY_PROMPT
from app.agents.state import AgentRuntimeStateService


EXECUTABLE_SPECIALIST_IDS = (
    "oracle",
    "nikita",
    "athena",
    "neo",
    "hephaestus",
    "apollo",
    "trinity",
)
ALLOWED_PHASES = ("analysis", "implementation", "validation", "operations")
MAX_PLAN_STEPS = 10

StepId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
BoundedText = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class OrchestrationStep(BaseModel):
    """Uma etapa do plano. agent_id restrito aos 7 especialistas executáveis."""

    model_config = ConfigDict(extra="forbid")

    step_id: StepId
    agent_id: str
    objective: BoundedText
    phase: Literal["analysis", "implementation", "validation", "operations"]
    requires_approval: StrictBool

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, value: str) -> str:
        if value not in EXECUTABLE_SPECIALIST_IDS:
            raise ValueError(f"agent_id não executável pelo plano: {value}")
        return value

    @property
    def auto_executable(self) -> bool:
        return self.phase == "analysis" and self.requires_approval is False


class OrchestrationPlan(BaseModel):
    """Plano validado de MORPHEUS. Rejeitado inteiramente se qualquer regra falhar."""

    model_config = ConfigDict(extra="forbid")

    objective: BoundedText
    summary: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    steps: list[OrchestrationStep] = Field(min_length=1, max_length=MAX_PLAN_STEPS)
    requires_approval_before_execution: StrictBool

    @field_validator("steps")
    @classmethod
    def validate_unique_step_ids(
        cls, steps: list[OrchestrationStep]
    ) -> list[OrchestrationStep]:
        ids = [step.step_id for step in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step_id duplicado no plano.")
        return steps


_PLAN_JSON_INSTRUCTIONS = (
    "Retorne SOMENTE JSON valido, sem Markdown, sem bloco de codigo, sem "
    "comentarios e sem texto antes ou depois. O objeto deve conter "
    "exclusivamente as propriedades objective, summary, steps e "
    "requires_approval_before_execution.\n"
    "objective: string com o objetivo do projeto.\n"
    "summary: string com um resumo do plano.\n"
    "steps: lista de 1 a 10 objetos, cada um com step_id (string unica), "
    "agent_id (um entre oracle, nikita, athena, neo, hephaestus, apollo, "
    "trinity — nunca morpheus, zeus ou conclave), objective (string), "
    "phase (um entre analysis, implementation, validation, operations) e "
    "requires_approval (boolean).\n"
    "requires_approval_before_execution: boolean.\n"
    "Marque requires_approval=true para qualquer etapa de implementation ou "
    "operations, ou que altere codigo/arquivos/infraestrutura real. Etapas "
    "de analysis puramente conceituais/read-only podem ter "
    "requires_approval=false. Selecione somente os especialistas realmente "
    "necessarios para este pedido especifico — nao assuma sempre o mesmo "
    "conjunto fixo de agentes."
)

MORPHEUS_PLANNING_PROMPT = f"{MORPHEUS_IDENTITY_PROMPT}\n\n{_PLAN_JSON_INSTRUCTIONS}"


class MorpheusOrchestrationService:
    """Primeira orquestração sequencial real de MORPHEUS (Fase 5A).

    Executa somente etapas phase=="analysis" e requires_approval==False,
    em sequência, até o primeiro step que exija aprovação — momento em que
    para e retorna waiting_approval. Sem paralelismo, sem DAG, sem
    persistência de plano.
    """

    def __init__(
        self,
        execution_service: AgentExecutionService,
        state_service: AgentRuntimeStateService,
    ) -> None:
        self._execution = execution_service
        self._state = state_service

    async def plan(self, message: str) -> dict[str, Any]:
        plan_result = await self._execution.run_with_prompt(
            "morpheus", MORPHEUS_PLANNING_PROMPT, message
        )
        if plan_result["status"] != "completed":
            self._state.set_status("morpheus", AgentStatus.ERROR)
            return self._error_response(
                message, f"Falha ao gerar plano: {plan_result['output']}"
            )

        try:
            orchestration_plan = OrchestrationPlan.model_validate_json(
                plan_result["output"]
            )
        except ValidationError as error:
            self._state.set_status("morpheus", AgentStatus.ERROR)
            return self._error_response(message, f"Plano inválido: {error}")

        # Sem await entre a linha anterior e esta: nenhuma outra corrotina
        # pode observar MORPHEUS fora de WORKING nesta janela (asyncio só
        # cede controle em pontos de await).
        self._state.set_status("morpheus", AgentStatus.WORKING)
        return await self._run_plan(orchestration_plan)

    async def _run_plan(self, plan: "OrchestrationPlan") -> dict[str, Any]:
        executed: list[dict[str, Any]] = []
        previous_outputs: dict[str, str] = {}

        for step in plan.steps:
            if not step.auto_executable:
                self._state.set_status("morpheus", AgentStatus.WAITING)
                return self._respond(plan, executed, "waiting_approval", next_step=step)

            step_message = self._build_step_message(
                plan.objective, step, previous_outputs
            )
            result = await self._execution.run(step.agent_id, step_message)
            executed.append(
                {
                    "step_id": step.step_id,
                    "agent_id": step.agent_id,
                    "status": result["status"],
                    "output": result["output"],
                }
            )

            if result["status"] != "completed":
                self._state.set_status("morpheus", AgentStatus.ERROR)
                return self._respond(plan, executed, "error", failed_step=step)

            previous_outputs[step.agent_id] = result["output"]

        # Todas as etapas do plano eram auto-executáveis: ainda assim
        # paramos antes de qualquer implementação real não solicitada.
        self._state.set_status("morpheus", AgentStatus.WAITING)
        return self._respond(plan, executed, "waiting_approval", next_step=None)

    @staticmethod
    def _build_step_message(
        objective: str,
        step: "OrchestrationStep",
        previous_outputs: dict[str, str],
    ) -> str:
        lines = [
            f"Objetivo global do projeto: {objective}",
            f"Objetivo desta etapa: {step.objective}",
        ]
        if previous_outputs:
            lines.append("Resultados relevantes de etapas anteriores:")
            for agent_id, output in previous_outputs.items():
                lines.append(f"- {agent_id}: {output[:1000]}")
        return "\n".join(lines)

    def _respond(
        self,
        plan: "OrchestrationPlan",
        executed: list[dict[str, Any]],
        status: str,
        *,
        next_step: "OrchestrationStep | None" = None,
        failed_step: "OrchestrationStep | None" = None,
    ) -> dict[str, Any]:
        consolidated = {
            "objective": plan.objective,
            "summary": plan.summary,
            "specialists_executed": [item["agent_id"] for item in executed],
            "outputs": {item["agent_id"]: item["output"] for item in executed},
            "waiting_approval": status == "waiting_approval",
            "next_step": next_step.model_dump() if next_step is not None else None,
            "failed_step": failed_step.model_dump() if failed_step is not None else None,
        }
        return {
            "plan": plan.model_dump(),
            "steps_executed": executed,
            "status": status,
            "consolidated": consolidated,
        }

    @staticmethod
    def _error_response(message: str, error_detail: str) -> dict[str, Any]:
        return {
            "plan": None,
            "steps_executed": [],
            "status": "error",
            "consolidated": {
                "objective": message,
                "error": error_detail,
                "waiting_approval": False,
            },
        }
