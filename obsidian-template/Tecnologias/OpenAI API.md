# OpenAI API

**Modelos usados:** GPT-4o Realtime, GPT-4o Vision, Whisper, TTS

## O que e

A API da OpenAI fornece acesso a modelos de linguagem, visao, fala-para-texto (STT) e texto-para-fala (TTS). O JARVIS usa multiplos modelos para diferentes capacidades.

## Como o JARVIS usa

### GPT-4o Realtime (Voz)
- Conexao WebSocket bidirecional para conversa em tempo real
- Audio-in -> audio-out com latencia minima
- Suporta function calling para executar acoes durante conversa
- Modelo principal de interacao por voz

### GPT-4o Vision (Visao de Tela)
- Recebe screenshots codificados em base64
- Analisa o conteudo visual da tela do usuario
- Usado para descrever o que esta na tela e guiar acoes de [[Computer Use]]

### Whisper (STT Fallback)
- Speech-to-text como fallback quando [[Tecnologias/Web Speech API]] falha
- Maior precisao que STT nativo, mas com latencia de rede
- Suporta pt-BR, en-US, es-ES

### TTS Streaming
- Texto-para-fala em streaming para respostas longas
- Audio comeca a tocar antes da resposta completa ser gerada

## Gotchas

- API key precisa estar configurada como variavel de ambiente
- Realtime API usa WebSocket separado da REST API
- Screenshots grandes em base64 consomem tokens de visao rapidamente
- Rate limits podem afetar uso intenso de vision + voice simultaneos

## Links

- [[Voz em Tempo Real]]
- [[Visao de Tela]]
