# Quinn — QA

**Modelo:** Sonnet 4.6
**Papel:** Quality Assurance do [[AIOX-CORE — Agentes]]
**Tier:** Qualidade e validacao

---

## Responsabilidades

- Quality gates em toda entrega
- Arquitetura de testes
- Review de codigo (10 fases)
- QA Loop — ciclo de review iterativo
- Spec Pipeline — Critique

## 7 Quality Checks (QA Gate)

Cada delivery passa por 7 verificacoes:
1. Correctness — Faz o que foi pedido?
2. Completeness — Falta algo?
3. No Regression — Quebrou algo?
4. Performance — Vai ser lento?
5. Security — Tem vulnerabilidade?
6. Code Quality — Codigo limpo?
7. Tests — Testes passando?

## Verdicts

| Verdict | Significado | Proximo Passo |
|---------|-------------|---------------|
| **PASS** | Tudo ok | Story -> Done |
| **CONCERNS** | Issues menores | Fix opcional |
| **FAIL** | Issues criticos | Retorna pro [[Agentes/Dex — Dev]] |
| **WAIVED** | Bypass autorizado | Documenta razao |

## QA Loop

Review -> Fix -> Re-review (max 5 iteracoes):
- `*qa-loop {storyId}` — Iniciar loop
- APPROVE -> Done
- REJECT -> Dex corrige
- BLOCKED -> Escalacao imediata

## Quando Usar

- Story implementada precisa de review
- Story Development Cycle — Fase 4 (QA Gate)
- Spec Pipeline — fase 5 (Critique)
- Brownfield Discovery — fase 7
- Qualquer validacao de qualidade

---

> Links: [[AIOX-CORE — Agentes]] · [[Cerebro 1 — Claude]]
