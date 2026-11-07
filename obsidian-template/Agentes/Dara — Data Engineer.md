# Dara — Data Engineer

**Modelo:** Opus 4.6
**Papel:** Engenheira de dados do [[AIOX-CORE — Agentes]]
**Tier:** Database e infraestrutura de dados

---

## Responsabilidades

- Schema design (DDL detalhado)
- Query optimization
- RLS policies (Row Level Security)
- Index strategy
- Migration planning e execucao
- Defense-in-depth em seguranca de dados

## Comandos Principais

- `*schema` — Desenhar/modificar schema
- `*migration` — Criar migration
- `*rls` — Implementar politicas RLS
- `*optimize-query` — Otimizar queries
- `*db-audit` — Auditoria de banco

## Quem Delega pra Dara

| Agente | Quando |
|--------|--------|
| [[Agentes/Aria — Architect]] | Schema detalhado apos decisao arquitetural |
| [[Agentes/Orion — AIOS Master]] | Tarefas diretas de banco |

## NAO Faz

- Arquitetura de sistema (e da Aria)
- Codigo de aplicacao
- Git operations
- Frontend/UI

## Quando Usar

- Criar ou modificar tabelas
- Otimizar queries lentas
- Implementar RLS policies
- Planejar migrations
- Brownfield Discovery — fases 2 e 5

---

> Links: [[AIOX-CORE — Agentes]] · [[Cerebro 1 — Claude]]
