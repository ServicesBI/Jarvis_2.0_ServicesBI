# Claude Code CLI

**Tipo:** Motor de execucao de tarefas baseado em IA

## O que e

Claude Code CLI e a interface de linha de comando da Anthropic que permite executar tarefas complexas de programacao e automacao. No JARVIS, funciona como o "cerebro executor" — recebe tarefas e as completa de forma autonoma.

## Como o JARVIS usa

- **Motor de execucao:** Recebe tarefas do usuario via interface e delega ao Claude Code
- **Warm pool:** Mantem processos pre-aquecidos prontos para execucao instantanea
  - Opus x 1 (tarefas complexas, arquitetura)
  - Sonnet x 3 (codigo, design, produto)
  - Haiku x 4 (tarefas rapidas, templates)
- Processos sao spawnados pelo [[Tecnologias/Node.js]] como child processes
- Output e streamed de volta para o frontend em tempo real
- Suporta execucao paralela de multiplas tarefas

## Warm Pool

O warm pool mantem instancias do Claude Code ja inicializadas na memoria. Quando uma tarefa chega, um processo do pool e imediatamente designado, eliminando o tempo de cold start.

## Gotchas

- Processos do warm pool consomem memoria mesmo ociosos
- Precisa do Claude Code instalado globalmente (`npm install -g @anthropic-ai/claude-code`)
- Timeout de processos precisa ser gerenciado para evitar processos zumbis
- Context window dos modelos limita tarefas muito longas

## Links

- [[Cerebro 1 — Claude]]
- [[Execucao de Tarefas]]
