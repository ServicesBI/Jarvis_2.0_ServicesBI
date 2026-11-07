# QA Loop

Ciclo iterativo de review e fix apos o QA Gate inicial.

---

## Fluxo

```
@qa review -> verdict -> @dev fixes -> re-review (max 5 iteracoes)
```

## Comandos

| Comando | Acao |
|---------|------|
| `*qa-loop {storyId}` | Iniciar loop |
| `*qa-loop-review` | Retomar do review |
| `*qa-loop-fix` | Retomar do fix |
| `*stop-qa-loop` | Pausar, salvar estado |
| `*resume-qa-loop` | Retomar de estado salvo |
| `*escalate-qa-loop` | Forcar escalacao |

## Verdicts

| Verdict | Significado | Proximo Passo |
|---------|-------------|---------------|
| **APPROVE** | Tudo ok | Story -> Done |
| **REJECT** | Issues encontrados | [[Agentes/Dex — Dev]] corrige -> re-review |
| **BLOCKED** | Impossivel continuar | Escalacao imediata |

## Configuracao

- **Max iteracoes:** 5
- **Status file:** `qa/loop-status.json`

## Triggers de Escalacao

- `max_iterations_reached` — 5 iteracoes sem APPROVE
- `verdict_blocked` — QA declarou BLOCKED
- `fix_failure` — Dev nao conseguiu corrigir
- `manual_escalate` — Escalacao manual

## Quando Usar

- Apos QA Gate retornar FAIL ou CONCERNS
- Precisa de ciclo iterativo de refinamento
- Bug complexo que precisa multiplas tentativas

---

> Links: [[Workflows/Story Development Cycle]] · [[Agentes/Quinn — QA]] · [[Agentes/Dex — Dev]]
