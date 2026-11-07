# Web Speech API

**Tipo:** API nativa do browser para reconhecimento de fala (STT)
**Latencia:** ~0ms (processamento local)

## O que e

Web Speech API e uma API nativa dos browsers modernos (Chrome, Edge) que converte fala em texto diretamente no dispositivo, sem enviar audio para servidores externos.

## Como o JARVIS usa

- **STT principal** — Reconhecimento de fala com latencia praticamente zero
- Processa audio localmente no browser (sem round-trip de rede)
- Idiomas suportados: **pt-BR**, **en-US**, **es-ES**
- Resultados parciais (interim) exibidos em tempo real enquanto o usuario fala
- **Fallback:** Quando falha ou nao disponivel, usa [[Tecnologias/OpenAI API]] Whisper

## Hierarquia de STT

```
1. Web Speech API (0ms latencia, local)
   | fallback
2. Whisper via OpenAI API (maior precisao, latencia de rede)
```

## Gotchas

- **So funciona em Chrome/Edge** — Firefox tem suporte limitado, Safari parcial
- Precisa de permissao de microfone do browser
- Pode parar de funcionar silenciosamente apos inatividade prolongada — precisa reiniciar o recognition
- Resultados interim podem ser imprecisos e mudar retroativamente
- Em ambientes ruidosos, precisao cai drasticamente comparado ao Whisper
- Nao funciona em HTTP (apenas HTTPS ou localhost)
- No Electron, depende da build do Chromium incluida

## Links

- [[Voz em Tempo Real]]
