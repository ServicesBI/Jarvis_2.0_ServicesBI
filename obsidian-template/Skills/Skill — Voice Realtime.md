# Skill — Voice Realtime (2026)

Expertise em voz AI em tempo real. Parte do [[Cerebro 2 — Mega-Brain]].

---

## Arquiteturas Conhecidas

| Tipo | Latencia | Como funciona |
|------|----------|---------------|
| Cascading | 1-3s | STT -> LLM -> TTS (sequencial) |
| Real-Time S2S | 300-800ms | WebRTC, speech-to-speech direto |
| **Hybrid (nosso)** | **~600ms** | Web Speech (0ms) + streaming LLM + sentence TTS |

## Implementacao

```
Mic -> Web Speech API (0ms) -> Server -> Claude/GPT (300ms) -> TTS streaming (150ms) -> Speaker
```

Total: ~600ms voice-to-voice. Melhor custo-beneficio.

## VAD Tuning

| Parametro | Valor | Efeito |
|-----------|-------|--------|
| VAD_SILENCE_MS | 1800ms | Tempo de silencio antes de parar gravacao |
| SPEECH_THRESHOLD | 8 | Sensibilidade de deteccao de fala |
| MIN_RECORD_MS | 1200ms | Gravacao minima (evita cliques falsos) |

## Streaming TTS

- Dispara na **primeira sentenca completa** (15+ chars com `.!?`)
- Nao espera resposta inteira — comeca falando enquanto gera o resto
- Sentence-chunked: cada frase vira um audio separado

## Modo Continuo

Loop hands-free:
1. Ouve -> 2. Processa -> 3. Fala -> 4. Pausa 1.5s -> 5. Volta a ouvir

## Qualidade de Audio

- 64kbps WebM Opus (leve, rapido)
- echoCancellation: OFF (causa cortes)
- noiseSuppression: OFF
- autoGainControl: ON

## Vozes

| Idioma | Voz | Personalidade |
|--------|-----|---------------|
| EN | ash | Deep, authoritative |
| BR | nova | Natural, warm |

## Upgrade Path

OpenAI Realtime API -> 300-500ms voice-to-voice direto. Mais rapido, mais caro.

## Anti-patterns

- Esperar resposta completa antes de falar
- 128kbps (lento demais pro upload)
- Bloquear UI durante processamento
- Echo cancellation ON (corta a fala)
