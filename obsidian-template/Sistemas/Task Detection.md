# Task Detection

Sistema de deteccao de tarefas via matching de palavras em Set.

---

## Como Funciona

### Set-Based Word Matching (primario)
`_taskWords` Set contem ~300 formas verbais em PT/EN/ES que indicam uma tarefa:

```javascript
_taskWords = new Set([
  "cria", "crie", "criar", "criando",
  "faz", "faca", "fazer", "fazendo",
  "create", "make", "build", "write",
  "abre", "abra", "abrir",
  // ... ~300 formas verbais
])
```

O input e tokenizado e cada palavra e checada contra o Set. **O(1)** por lookup.

### Regex Fallback (secundario)
`TASK_PATTERN` regex para patterns mais complexos que o Set nao pega:

```javascript
TASK_PATTERN = /^(por favor|please)?\s*(cri|faz|abr|escrev|mand|envi).*/i
```

## Fluxo

```
Input do usuario
  +-- Tokeniza em palavras
  +-- Alguma palavra esta no _taskWords Set? -> E tarefa
  +-- Match no TASK_PATTERN regex? -> E tarefa
  +-- Nenhum match? -> E pergunta/conversa
```

## Por Que Set e Nao So Regex

- Set lookup e O(1) — instantaneo
- Regex fica complexo demais com 300+ formas verbais
- Set e facil de manter e expandir
- Regex serve como fallback para patterns compostos

---

> Links: [[Execucao de Tarefas]]
