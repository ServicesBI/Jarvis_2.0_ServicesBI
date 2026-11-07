"""Fonte runtime única e ordenada do catálogo canônico de agentes."""

from __future__ import annotations

from app.agents.models import AgentDefinition, AgentStatus


class AgentRegistryError(ValueError):
    pass


class DuplicateAgentError(AgentRegistryError):
    pass


class UnknownAgentError(AgentRegistryError):
    pass


CANONICAL_AGENT_DEFINITIONS = (
    AgentDefinition(
        "morpheus", "MORPHEUS", "ORCHESTRATOR",
        "Planeja, decompõe, coordena especialistas, acompanha dependências e consolida resultados.",
        AgentStatus.IDLE,
        "obsidian-template/Agentes/Morpheus — Orchestrator.md",
    ),
    AgentDefinition(
        "oracle", "ORACLE", "BUSINESS & SYSTEMS ANALYST",
        "Analisa processos, requisitos, regras de negócio, ERP, critérios de aceite e KPIs.",
        AgentStatus.IDLE,
        "obsidian-template/Agentes/Oracle — Business & Systems Analyst.md",
    ),
    AgentDefinition(
        "nikita", "NIKITA", "DATA & BI ENGINEER",
        "Modela e processa dados, bancos, ETL, analytics, Power BI e modelos semânticos.",
        AgentStatus.IDLE,
        "obsidian-template/Agentes/Nikita — Data & BI Engineer.md",
    ),
    AgentDefinition(
        "athena", "ATHENA", "SOLUTION ARCHITECT",
        "Define arquitetura, stack, contratos, integrações, segurança, escalabilidade e padrões técnicos.",
        AgentStatus.IDLE,
        "obsidian-template/Agentes/Athena — Solution Architect.md",
    ),
    AgentDefinition(
        "neo", "NEO", "SOFTWARE ENGINEER",
        "Implementa, testa, refatora e depura software, integrações e documentação técnica.",
        AgentStatus.IDLE,
        "obsidian-template/Agentes/Neo — Software Engineer.md",
    ),
    AgentDefinition(
        "hephaestus", "HEPHAESTUS", "PLATFORM & OPERATIONS",
        "Prepara ambientes, entrega, observa, opera e recupera sistemas com segurança.",
        AgentStatus.IDLE,
        "obsidian-template/Agentes/Hephaestus — Platform & Operations.md",
    ),
    AgentDefinition(
        "apollo", "APOLLO", "QUALITY ENGINEER",
        "Define e executa testes, regressão, reprodução de bugs, reviews e verification gates.",
        AgentStatus.IDLE,
        "obsidian-template/Agentes/Apollo — Quality Engineer.md",
    ),
    AgentDefinition(
        "trinity", "TRINITY", "PRODUCT DESIGNER",
        "Projeta UX, UI, fluxos, design systems, acessibilidade e validação visual.",
        AgentStatus.IDLE,
        "obsidian-template/Agentes/Trinity — Product Designer.md",
    ),
)


class AgentRegistry:
    def __init__(self, definitions: tuple[AgentDefinition, ...]) -> None:
        by_id: dict[str, AgentDefinition] = {}
        for definition in definitions:
            if not isinstance(definition, AgentDefinition):
                raise TypeError("definitions must contain only AgentDefinition")
            if definition.id in by_id:
                raise DuplicateAgentError(f"Duplicate agent id: {definition.id}")
            by_id[definition.id] = definition
        self._definitions = tuple(definitions)
        self._by_id = by_id

    def list_agents(self) -> tuple[AgentDefinition, ...]:
        return self._definitions

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._by_id[agent_id]
        except KeyError as error:
            raise UnknownAgentError(f"Unknown agent id: {agent_id}") from error


def create_agent_registry() -> AgentRegistry:
    return AgentRegistry(CANONICAL_AGENT_DEFINITIONS)
