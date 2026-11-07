# Rate Limiter

Controle de taxa de chamadas a OpenAI API para prevenir erros 429 (Too Many Requests).

---

## Configuracao

| Parametro | Valor |
|-----------|-------|
| Intervalo minimo entre chamadas | **500ms** |
| Retries | **3** |
| Backoff (progressivo) | 3s -> 6s -> 12s |

## Como Funciona

```
Chamada OpenAI
  +-- Ultima chamada < 500ms atras? -> Aguarda diferenca
  +-- Resposta 429? -> Retry 1 (espera 3s)
  +-- Ainda 429? -> Retry 2 (espera 6s)
  +-- Ainda 429? -> Retry 3 (espera 12s)
  +-- Ainda 429? -> Erro final, loga e notifica
```

## Por Que Existe

Sem rate limiter, chamadas rapidas em sequencia (ex: parallel execution de 3 tarefas) causavam 429 da OpenAI. O intervalo de 500ms e backoff exponencial resolveram completamente.

## Onde e Usado

- Todas as chamadas a OpenAI API (TTS, STT, GPT-4o-mini, embeddings)
- Smart fast-path
- Geracao de embeddings para RAG

---

> Links: [[Tecnologias/OpenAI API]] · [[Arquitetura]]
