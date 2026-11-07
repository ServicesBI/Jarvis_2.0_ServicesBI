# Cerebro 1 — Claude

**Tipo:** Motor de raciocinio + execucao
**Natureza:** Efemero (vive na sessao)

---

## O que e

Claude e o motor do JARVIS. E ele que pensa, raciocina, escreve codigo e executa. Quando o usuario fala com o JARVIS, e o Claude que processa tudo.

## O que ele faz

- Raciocina sobre o pedido
- Escreve e executa codigo
- Spawna processos (Claude Code CLI)
- Interage com APIs
- Responde por voz

## Modelos

| Modelo | Quando |
|--------|--------|
| Opus | Problemas complexos, arquitetura |
| Sonnet | Codigo, build, maioria das tarefas |
| Haiku | Coisas rapidas e simples |

## AIOX-CORE — Agentes como Papeis do Claude

Os agentes nao sao entidades separadas — sao **personas que o Claude veste** pra focar em tarefas especificas. Claude se torna @dev quando precisa codar, @architect quando precisa projetar.

Ver [[AIOX-CORE — Agentes]]

## Delivery System

Como o Claude executa tudo:

| Tier | Quando | Padrao |
|------|--------|--------|
| INSTANT | 1 arquivo, claro | Executa imediatamente |
| FAST | Multi-arquivo | Pre-flight -> paralelo |
| STRATEGIC | Arquitetura, risco | [[Conclave]] -> plano -> paralelo -> QA |
| EPIC | Sistema completo | Spec -> squad -> paralelo -> QA -> ship |

## Limitacao

Esquece tudo quando a sessao acaba. Depende do [[Cerebro 3 — Obsidian]] pra lembrar e do [[Cerebro 2 — Mega-Brain]] pra sabedoria acumulada.
