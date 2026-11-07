# Orion — AIOS Master

**Modelo:** Opus 4.6
**Papel:** Orquestrador universal do [[AIOX-CORE — Agentes]]
**Tier:** Governanca do framework

---

## Responsabilidades

- Executar **qualquer tarefa** diretamente — sem restricoes
- Governanca constitucional do framework AIOS
- Override de boundaries de qualquer agente quando necessario
- Mediacao de conflitos entre agentes
- Escalacao final — quando nenhum agente resolve, Orion assume

## Comandos Principais

- `*execute` — Execucao direta de qualquer tarefa
- `*override` — Sobrescrever decisao de outro agente
- `*escalate` — Receber escalacao de agentes bloqueados
- `*mediate` — Resolver conflito entre agentes
- 25+ comandos disponiveis no total

## Delegacao

| Delega Para | Quando |
|-------------|--------|
| Qualquer agente | Conforme a natureza da tarefa |
| [[Agentes/Aria — Architect]] | Decisoes de arquitetura |
| [[Agentes/Dex — Dev]] | Implementacao |
| [[Agentes/Gage — DevOps]] | Push, PR, deploy |

## Quando Usar

- Tarefa complexa que cruza multiplos dominios
- Agente bloqueado precisa de escalacao
- Conflito entre agentes sobre abordagem
- Violacao constitucional detectada
- Qualquer situacao onde nenhum agente especifico e o ideal

---

> Links: [[AIOX-CORE — Agentes]] · [[Cerebro 1 — Claude]]
