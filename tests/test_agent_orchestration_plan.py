"""RED/GREEN da Fase 5A: contrato estruturado OrchestrationPlan/Step.

Unit-level puro (sem chat/CLI): garante que o runtime nunca confia
cegamente no JSON produzido pelo LLM antes de executar qualquer etapa.
"""

from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from app.agents.orchestration import (
    MAX_PLAN_STEPS,
    MORPHEUS_PLANNING_PROMPT,
    OrchestrationPlan,
)
from app.agents.runtime import MORPHEUS_OPERATING_PROFILE, get_operating_profile
from app.agents.runtime import AgentOperatingProfileNotFoundError


def _valid_step(step_id: str = "s1", agent_id: str = "oracle", **overrides) -> dict:
    base = {
        "step_id": step_id,
        "agent_id": agent_id,
        "objective": "analisar requisitos",
        "phase": "analysis",
        "requires_approval": False,
    }
    base.update(overrides)
    return base


def _valid_plan(steps: list[dict] | None = None, **overrides) -> dict:
    base = {
        "objective": "Criar um ERP de Compras",
        "summary": "Plano inicial de analise",
        "steps": steps if steps is not None else [_valid_step()],
        "requires_approval_before_execution": True,
    }
    base.update(overrides)
    return base


class MorpheusProfileTests(unittest.TestCase):
    def test_morpheus_has_its_own_operating_profile(self) -> None:
        self.assertEqual(MORPHEUS_OPERATING_PROFILE.agent_id, "morpheus")
        self.assertIn("MORPHEUS", MORPHEUS_OPERATING_PROFILE.operating_prompt)
        self.assertIn("MORPHEUS", MORPHEUS_PLANNING_PROMPT)

    def test_morpheus_remains_non_executable_via_generic_specialist_lookup(
        self,
    ) -> None:
        # Fase 4C: MORPHEUS nao pode ser executado via /api/agents/{id}/run.
        # O profile "proprio" de MORPHEUS existe, mas fora de
        # _OPERATING_PROFILES, entao get_operating_profile continua 404-avel.
        with self.assertRaises(AgentOperatingProfileNotFoundError):
            get_operating_profile("morpheus")


class OrchestrationPlanValidationTests(unittest.TestCase):
    def test_valid_plan_is_accepted(self) -> None:
        plan = OrchestrationPlan.model_validate(_valid_plan())
        self.assertEqual(plan.objective, "Criar um ERP de Compras")
        self.assertEqual(len(plan.steps), 1)

    def test_valid_plan_round_trips_through_json(self) -> None:
        payload = _valid_plan(
            steps=[
                _valid_step("oracle-1", "oracle"),
                _valid_step("athena-1", "athena"),
            ]
        )
        plan = OrchestrationPlan.model_validate_json(json.dumps(payload))
        self.assertEqual([s.agent_id for s in plan.steps], ["oracle", "athena"])

    def test_unknown_agent_id_in_step_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(
                _valid_plan(steps=[_valid_step(agent_id="dex")])
            )

    def test_zeus_cannot_appear_as_a_step_agent(self) -> None:
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(
                _valid_plan(steps=[_valid_step(agent_id="zeus")])
            )

    def test_conclave_cannot_appear_as_a_step_agent(self) -> None:
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(
                _valid_plan(steps=[_valid_step(agent_id="conclave")])
            )

    def test_morpheus_cannot_delegate_to_itself(self) -> None:
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(
                _valid_plan(steps=[_valid_step(agent_id="morpheus")])
            )

    def test_invalid_phase_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(
                _valid_plan(steps=[_valid_step(phase="deployment")])
            )

    def test_requires_approval_must_be_strict_boolean(self) -> None:
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(
                _valid_plan(steps=[_valid_step(requires_approval="yes")])
            )

    def test_duplicate_step_ids_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(
                _valid_plan(
                    steps=[
                        _valid_step("dup", "oracle"),
                        _valid_step("dup", "athena"),
                    ]
                )
            )

    def test_plan_above_step_limit_is_rejected(self) -> None:
        too_many = [
            _valid_step(f"s{i}", "oracle") for i in range(MAX_PLAN_STEPS + 1)
        ]
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(_valid_plan(steps=too_many))

    def test_plan_at_step_limit_is_accepted(self) -> None:
        exactly_max = [_valid_step(f"s{i}", "oracle") for i in range(MAX_PLAN_STEPS)]
        plan = OrchestrationPlan.model_validate(_valid_plan(steps=exactly_max))
        self.assertEqual(len(plan.steps), MAX_PLAN_STEPS)

    def test_empty_steps_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(_valid_plan(steps=[]))

    def test_unknown_extra_field_is_rejected(self) -> None:
        payload = _valid_plan()
        payload["extra_field"] = "not allowed"
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate(payload)

    def test_malformed_json_text_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            OrchestrationPlan.model_validate_json("not json at all")

    def test_auto_executable_property_matches_analysis_without_approval(self) -> None:
        plan = OrchestrationPlan.model_validate(
            _valid_plan(
                steps=[
                    _valid_step("a", "oracle", phase="analysis", requires_approval=False),
                    _valid_step("b", "neo", phase="implementation", requires_approval=True),
                ]
            )
        )
        self.assertTrue(plan.steps[0].auto_executable)
        self.assertFalse(plan.steps[1].auto_executable)


if __name__ == "__main__":
    unittest.main()
