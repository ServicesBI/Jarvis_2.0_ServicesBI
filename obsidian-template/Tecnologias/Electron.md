# Electron

**Tipo:** Framework para apps desktop com tecnologias web

## O que e

Electron permite criar aplicacoes desktop usando HTML, CSS e JavaScript. Combina Chromium (para renderizacao) com [[Tecnologias/Node.js]] (para acesso ao sistema).

## Como o JARVIS usa

- **Launcher** — Aplicacao portable
- Abre o frontend do JARVIS em uma janela desktop nativa
- Sem necessidade de browser externo
- GPU cache desabilitado para reduzir uso de disco
- Configurado como single-instance (so uma janela por vez)
- Cross-platform (Windows principal, potencial Mac/Linux)

## Configuracoes

- `--disable-gpu-cache` — Evita acumulo de cache de GPU no disco
- Portable — nao requer instalacao, roda direto do executavel
- Aponta para `http://127.0.0.1:8000`, servido pelo backend FastAPI

## Gotchas

- ~71MB e o tamanho minimo por incluir Chromium inteiro
- GPU cache pode crescer indefinidamente se nao desabilitado
- Atualizacoes precisam substituir o executavel inteiro (sem auto-update configurado)
- Em maquinas com pouca RAM, Chromium do Electron + Chrome do [[Tecnologias/Puppeteer]] competem por memoria

## Links

- [[Arquitetura]]
