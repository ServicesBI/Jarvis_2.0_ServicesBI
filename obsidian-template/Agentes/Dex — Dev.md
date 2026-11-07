# Dex — Dev

**Modelo:** Sonnet 4.6
**Papel:** Desenvolvedor fullstack do [[AIOX-CORE — Agentes]]
**Tier:** Implementacao

---

## Responsabilidades

- Desenvolvimento fullstack (frontend + backend)
- Implementacao de stories
- CodeRabbit self-healing (max 2 iteracoes)
- Atualizacao de story files (File List, checkboxes)

## Git — Permitido vs Bloqueado

| Permitido | Bloqueado |
|-----------|-----------|
| `git add`, `git commit` | `git push` -> delegar pra [[Agentes/Gage — DevOps]] |
| `git branch`, `git checkout` | `gh pr create/merge` -> delegar pra [[Agentes/Gage — DevOps]] |
| `git stash`, `git diff`, `git log` | MCP management |
| `git merge` (local) | Alterar AC/scope/titulo de stories |

## Modos de Execucao

- **Interactive** — Passo a passo com feedback
- **YOLO** — Executa tudo direto, ideal pra bug fixes
- **Pre-Flight** — Analisa antes de implementar

## CodeRabbit Self-Healing

Apos implementar, Dex roda CodeRabbit automaticamente:
1. Review identifica issues
2. Dex corrige automaticamente
3. Re-review (max 2 iteracoes)

## Quando Usar

- Implementar qualquer feature ou fix
- Story Development Cycle — Fase 3 (Implement)
- Bug fixes (modo YOLO)
- Qualquer codigo novo

---

> Links: [[AIOX-CORE — Agentes]] · [[Cerebro 1 — Claude]]
