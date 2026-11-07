# Spec Pipeline

Transforma requisitos informais em spec executavel. Pre-implementacao.

---

## 6 Fases

| Fase | Agente | Output | Skip Se |
|------|--------|--------|---------|
| 1. Gather | [[Agentes/Morgan — PM]] | `requirements.json` | Nunca |
| 2. Assess | [[Agentes/Aria — Architect]] | `complexity.json` | source=simple |
| 3. Research | [[Agentes/Atlas — Analyst]] | `research.json` | Classe SIMPLE |
| 4. Write Spec | [[Agentes/Morgan — PM]] | `spec.md` | Nunca |
| 5. Critique | [[Agentes/Quinn — QA]] | `critique.json` | Nunca |
| 6. Plan | [[Agentes/Aria — Architect]] | `implementation.yaml` | Se APPROVED |

## Classes de Complexidade

Avaliada em 5 dimensoes (1-5 cada):
- **Scope** — Arquivos afetados
- **Integration** — APIs externas
- **Infrastructure** — Mudancas necessarias
- **Knowledge** — Familiaridade do time
- **Risk** — Criticidade

| Score | Classe | Fases Executadas |
|-------|--------|-----------------|
| <= 8 | **SIMPLE** | Gather -> Spec -> Critique (3 fases) |
| 9-15 | **STANDARD** | Todas as 6 fases |
| >= 16 | **COMPLEX** | 6 fases + ciclo de revisao |

## Verdicts da Critique (Fase 5)

| Verdict | Score Medio | Proximo Passo |
|---------|------------|---------------|
| **APPROVED** | >= 4.0 | Plan (Fase 6) |
| **NEEDS_REVISION** | 3.0-3.9 | Revise (Fase 5b) |
| **BLOCKED** | < 3.0 | Escalar pra Aria |

## Regra Constitucional (Artigo IV)

**No Invention:** Toda afirmacao no spec.md DEVE rastrear para FR-*, NFR-*, CON-* ou finding de pesquisa. Nenhuma feature inventada.

## Quando Usar

- Feature complexa precisa de spec antes de codar
- Requisitos vagos que precisam ser formalizados
- Apos Spec Pipeline -> entra no [[Workflows/Story Development Cycle]]

---

> Links: [[Workflows/Story Development Cycle]]
