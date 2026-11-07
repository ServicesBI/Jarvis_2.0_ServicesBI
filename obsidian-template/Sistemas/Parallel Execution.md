# Parallel Execution

Sistema de deteccao e execucao paralela de multiplas tarefas.

---

## Como Funciona

### Deteccao
`detectParallelTasks()` analisa o input e identifica tarefas independentes:

```
"cria o site, a planilha e a apresentacao"
  -> Tarefa 1: criar site
  -> Tarefa 2: criar planilha
  -> Tarefa 3: criar apresentacao
```

### Execucao
3 processos Claude CLI sao spawned simultaneamente, cada um com sua tarefa:

```
spawn("cria o site")          --> resultado 1
spawn("cria a planilha")      --> resultado 2  (paralelo)
spawn("cria a apresentacao")  --> resultado 3
```

### Resultado
Todos os resultados sao coletados e apresentados juntos ao usuario.

## Regras

| Tipo | Comportamento |
|------|--------------|
| Tarefas independentes | Executar em paralelo |
| Tarefas dependentes | Executar em sequencia, feed output forward |
| Tarefa unica | Execucao normal |

## Impacto

| Serial | Paralelo |
|--------|---------|
| 3 tarefas x 30s = 90s | 3 tarefas em paralelo = ~35s |

---

> Links: [[Execucao de Tarefas]] · [[Skills/Skill — Delivery System]]
