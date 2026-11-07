# Execucao de Tarefas

Como o JARVIS transforma pedidos em entregas.

---

## Fluxo

```
Pedido por voz -> Detecta tarefa -> Roteia para modelo -> Claude CLI executa -> Resultado
```

## Deteccao de Tarefas

Set-based word matching com ~300 formas verbais em PT/EN/ES:
- "cria", "criando", "crie", "create", "creating"
- "abre", "abra", "open", "opening"
- "edita", "modifica", "altera", "update", "change"
- etc.

## Warm Pool

Processos Claude CLI pre-spawned prontos pra usar:

| Modelo | Quantidade | Uso |
|--------|-----------|-----|
| Opus | 1 | Arquitetura, decisoes criticas |
| Sonnet | 3 | Build, design, codigo |
| Haiku | 4 | Rapido, simples, templates |

## Execucao Paralela

`detectParallelTasks()` divide multi-tarefas:
- "cria o site, a planilha e a apresentacao" -> 3 spawns simultaneos
- Cada um roda em paralelo
- Resultados agregados no final

## Tiers de Execucao

| Tier | Quando | Padrao |
|------|--------|--------|
| INSTANT | 1 arquivo, escopo claro | Executa imediatamente |
| FAST | Multi-arquivo, moderado | Pre-flight -> paralelo |
| STRATEGIC | Arquitetura, risco | [[Conclave]] -> plano -> paralelo -> QA |
| EPIC | Feature completa | Spec -> squad -> paralelo -> QA -> ship |
