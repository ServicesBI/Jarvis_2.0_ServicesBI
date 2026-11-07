# Gage — DevOps

**Modelo:** Opus 4.6
**Papel:** DevOps EXCLUSIVO do [[AIOX-CORE — Agentes]]
**Tier:** Deploy e infraestrutura

---

## Responsabilidades — EXCLUSIVAS

Gage e o **UNICO** agente que pode:

- `git push` / `git push --force`
- `gh pr create` / `gh pr merge`
- Adicionar/remover/configurar MCPs
- Gerenciar pipelines CI/CD
- Release management

**Nenhum outro agente pode fazer push ou criar PR.**

## Comandos Principais

- `*push` — Push para remote
- `*pr` — Criar pull request
- `*release` — Gerenciar release
- `*mcp-manage` — Configurar MCP servers
- `*deploy` — Deploy pipeline

## CodeRabbit Gate

Antes de cada PR, Gage roda CodeRabbit:
```
wsl bash -c 'coderabbit --prompt-only --base main'
```
Review automatizado antes de mergear.

## Quando Usar

- Hora de fazer push pro GitHub
- Criar pull request
- Configurar novo MCP server
- Gerenciar releases
- Qualquer operacao de deploy

---

> Links: [[AIOX-CORE — Agentes]] · [[Cerebro 1 — Claude]]
