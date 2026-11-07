# Skill — Delivery System

Velocidade maxima com qualidade maxima. Parte do [[Cerebro 2 — Mega-Brain]].

---

## Principio Core

> Avaliar e executar **simultaneamente**. Nunca pausar pra planejar.

## Tiers de Execucao

| Tier | Trigger | Padrao |
|------|---------|--------|
| INSTANT | 1 arquivo, claro, sem risco | Executa imediatamente |
| FAST | Multi-arquivo, moderado | Pre-flight -> paralelo |
| STRATEGIC | Arquitetura, risco | [[Conclave]] -> plano -> paralelo -> QA |
| EPIC | Feature completa, sistema novo | Spec -> squad -> paralelo -> QA -> ship |

## Assessment (0 segundos)

Roda EM PARALELO com a primeira acao:
1. Qual e o entregavel? -> comeca imediatamente
2. O que pode ser paralelizado? -> despacha simultaneo
3. Qual e o risco? -> endereca inline
4. Done = funcionando e usavel, nao planejado

## Execucao Paralela

```
Independentes -> roda TODOS ao mesmo tempo
Dependentes   -> sequencial, passa output adiante
```

## Padroes de Despacho

| Padrao | Fluxo |
|--------|-------|
| Research + Build | Atlas pesquisa ENQUANTO Dex constroi |
| Conclave + Execute | Debate -> decisao -> execucao imediata |
| Full Squad | Morgan spec -> squad paralelo -> Quinn -> Gage |
| Fast Fix | Dex corrige -> Quinn spot-check |

## Quality Gates

| Gate | Pergunta | Obrigatorio a partir de |
|------|----------|------------------------|
| Correctness | Faz o que foi pedido? | Todos |
| No regression | Quebrou algo? | FAST+ |
| Completeness | Falta algo? | FAST+ |
| Performance | Vai ser lento? | STRATEGIC+ |

## 6 Principios de Velocidade

1. **Modelo certo** — Opus so pra complexo, Haiku pra simples
2. **Paralelo > Sequencial** — sempre
3. **Pre-flight > Rework** — pensar antes evita refazer
4. **Entrega incremental** — pequeno e frequente > grande e raro
5. **Comprimir output** — denso, sem enrolacao
6. **Reuse before rebuild** — checar skills antes de criar do zero

## Anti-patterns

- Executar agentes em sequencia quando poderiam ser paralelos
- Over-explain (explicar demais em vez de entregar)
- Pular QA pra ir mais rapido
- Usar Opus pra tudo (caro e lento quando desnecessario)
