# Visao de Tela

O JARVIS ve o que esta no monitor. Capacidade do [[Cerebro 1 — Claude]], trabalha junto com [[Computer Use]].

---

## Como Funciona

1. **Screenshot completo:** `system/screenshot.py` captura todos monitores, stitcha em 1 imagem
2. **Foco no cursor:** `system/screenshot-cursor.py` captura 800x600 ao redor do mouse
3. **Analise:** Imagem enviada para GPT-4o vision API
4. **Resposta:** Descreve o que ve ou toma acao

## Ativacao

Frases que ativam visao:
- "o que tem na minha tela?"
- "voce consegue ver?"
- "olha meu monitor"
- "o que eu to vendo?"

## Multi-Monitor

- Captura TODOS os monitores
- Stitcha lado a lado
- Labels com numero do monitor
- Suporta resolucoes diferentes

## Endpoints

- `POST /api/screenshot` — captura tela
- `POST /api/computer-use` — acao unica (click, type, etc.)
- `POST /api/computer-use/task` — tarefa complexa multi-step

Parte da [[Arquitetura]] do JARVIS. Ver tambem [[Habilidades]].
