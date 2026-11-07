# Fast-Path

Sistema de comandos instantaneos que bypassa o LLM para acoes comuns.

---

## Como Funciona

### Fast-Path Direto (~100ms)
Regex patterns pre-definidos que executam imediatamente sem chamar nenhum modelo:

| Pattern | Acao |
|---------|------|
| "abre/open {programa}" | Abre programa via spawn |
| "que horas sao" | Retorna hora atual |
| "timer {X} minutos" | Inicia timer |
| "volume {X}%" | Ajusta volume do sistema |

### Smart Fast-Path (~500ms)
Quando o regex nao match mas a tarefa e simples, usa **GPT-4o-mini** para interpretar rapidamente antes de executar.

## Fluxo de Decisao

```
Input do usuario
  +-- Regex match? -> Executa direto (~100ms)
  +-- Smart match? -> GPT-4o-mini -> Executa (~500ms)
  +-- Complexo?    -> Claude/Mega-Brain (~2-5s)
```

## Por Que Existe

Sem fast-path, ate "que horas sao" passaria pelo Claude (2-5s). Com fast-path, a resposta e instantanea.

---

> Links: [[Execucao de Tarefas]] · [[Arquitetura]]
