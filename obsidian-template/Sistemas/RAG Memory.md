# RAG Memory

Sistema de memoria de longo prazo baseado em embeddings e busca semantica.

---

## Capacidade

- **2000 embeddings** maximos
- **6 categorias** de memoria
- Busca semantica por similaridade de cosseno

## Categorias

| Categoria | O Que |
|-----------|-------|
| `conversation` | Contexto de conversas anteriores |
| `project` | Detalhes de projetos em andamento |
| `preference` | Preferencias do usuario (tom, formato, ferramentas) |
| `decision` | Decisoes tecnicas tomadas |
| `skill` | Habilidades aprendidas |
| `fact` | Fatos gerais sobre o usuario/ambiente |

## Features

### Temporal Relevance Boosting
Memorias recentes recebem boost na busca. Uma decisao de ontem tem mais peso que uma de 3 meses atras.

### Chunking
Textos longos sao divididos em chunks menores para embeddings mais precisos.

### Busca Semantica
```
Query: "como configurar supabase?"
-> Busca por similaridade nos 2000 embeddings
-> Retorna top-K mais relevantes
-> Aplica temporal boosting
-> Injeta no contexto do LLM
```

---

> Links: [[Cerebro 3 — Obsidian]] · [[Arquitetura]]
