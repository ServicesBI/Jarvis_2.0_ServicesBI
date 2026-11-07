# Story Development Cycle (SDC)

O workflow principal de desenvolvimento. 4 fases, do draft ao deploy.

---

## Visao Geral

```
Create -> Validate -> Implement -> QA Gate
 @sm      @po        @dev        @qa
```

## Fases

### Fase 1: Create ([[Agentes/River — SM]])
- **Task:** `create-next-story.md`
- **Input:** PRD sharded, epic context
- **Output:** `{epicNum}.{storyNum}.story.md`
- **Status:** Draft

### Fase 2: Validate ([[Agentes/Pax — PO]])
- **Task:** `validate-next-story.md`
- **Checklist de 10 pontos**
- **Decisao:**
  - **GO** (>= 7) -> Segue pra Fase 3
  - **NO-GO** (< 7) -> Retorna pra Fase 1 com fixes

### Fase 3: Implement ([[Agentes/Dex — Dev]])
- **Task:** `dev-develop-story.md`
- **Modos:** Interactive / YOLO / Pre-Flight
- **CodeRabbit:** Self-healing max 2 iteracoes
- **Status:** Ready -> InProgress

### Fase 4: QA Gate ([[Agentes/Quinn — QA]])
- **Task:** `qa-gate.md`
- **7 quality checks**
- **Decisao:** PASS / CONCERNS / FAIL / WAIVED
- **Status:** InProgress -> InReview -> Done

## Apos QA PASS

-> [[Agentes/Gage — DevOps]] faz push e PR.

## Quando Usar

| Situacao | Usar SDC? |
|----------|-----------|
| Nova story de epic | Sim, completo |
| Bug fix simples | Sim, modo YOLO (skip Fase 1-2) |
| Feature complexa | Sim, apos [[Workflows/Spec Pipeline]] |

---

> Links: [[AIOX-CORE — Agentes]]
