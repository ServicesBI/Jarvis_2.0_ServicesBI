# Warm Pool

Processos Claude CLI pre-spawned para reduzir latencia de inicializacao.

---

## Configuracao

| Modelo | Processos Pre-Spawned | Uso |
|--------|----------------------|-----|
| **Opus** | 1 | Decisoes estrategicas, arquitetura |
| **Sonnet** | 3 | Dev, UX, PM, analise |
| **Haiku** | 4 | Queries rapidas, templates, SM |

**Total:** 8 processos prontos em standby.

## Como Funciona

1. Na inicializacao do JARVIS, spawna os processos Claude CLI
2. Processos ficam em standby aguardando input
3. Quando uma tarefa chega, pega um processo do pool (sem espera de spawn)
4. Apos uso, repoe o processo no pool

## Impacto na Latencia

| Sem Warm Pool | Com Warm Pool |
|--------------|---------------|
| ~2-3s spawn + ~2-5s resposta | ~0ms spawn + ~2-5s resposta |

O spawn do CLI e eliminado completamente.

## Gerenciamento

- Processos que morrem sao re-spawned automaticamente
- Pool e ajustado conforme uso (mais Sonnet se muita dev)
- Cada processo mantem contexto isolado

---

> Links: [[Tecnologias/Claude Code CLI]] · [[Execucao de Tarefas]]
