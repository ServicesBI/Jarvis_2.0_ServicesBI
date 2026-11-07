# Voz em Tempo Real

Como o JARVIS fala e ouve. Capacidade do [[Cerebro 1 — Claude]]. Expertise detalhada em [[Skill — Voice Realtime]].

---

## Arquitetura Hybrid

```
Microfone -> Web Speech API (STT, 0ms) -> Servidor -> Claude/GPT -> TTS streaming -> Alto-falante
```

**Latencia total:** ~600ms

| Etapa | Tecnologia | Latencia |
|-------|-----------|----------|
| STT | Web Speech API | 0ms (browser nativo) |
| Processamento | Claude Code CLI / GPT-4o | ~300ms |
| TTS | OpenAI TTS streaming | ~150ms (primeira sentenca) |

## Configuracao de Audio

- **Formato:** 64kbps WebM Opus
- **Echo cancellation:** OFF (causa cortes)
- **Noise suppression:** OFF
- **Auto gain control:** ON
- **Wake word:** configuravel

## VAD (Voice Activity Detection)

- **Silencio:** 1800ms antes de parar gravacao
- **Threshold:** 8 (sensibilidade)
- **Gravacao minima:** 1200ms
- **Modo continuo:** Loop com 1.5s pausa entre respostas

## Vozes TTS

| Idioma | Voz | Caracteristica |
|--------|-----|----------------|
| EN | ash | Deep, authoritative |
| BR | nova | Natural, warm |

## Fast-path (~100ms)

Comandos instantaneos que NAO passam pelo Claude:
- Abrir programas (Chrome, Excel, VS Code...)
- Que horas sao / que dia e hoje
- Timer / alarme
- Volume (subir, descer, mudo)
- Abrir URLs

## Smart fast-path (~500ms)

GPT-4o-mini gera shell command para acoes complexas que nao precisam do Claude completo.

## Fallback

Se Web Speech falhar -> Whisper API (upload do audio WebM)
