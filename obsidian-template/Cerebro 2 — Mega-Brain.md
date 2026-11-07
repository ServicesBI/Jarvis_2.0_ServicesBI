# Cerebro 2 — Mega-Brain

**Tipo:** Sabedoria acumulada + decisao estrategica
**Natureza:** Persistente (skills salvos em arquivos)

---

## O que e

O Mega-Brain e a camada de **inteligencia acumulada** do JARVIS. Nao e um motor de execucao — e um reservatorio de expertise, padroes aprendidos e um sistema de decisao estrategica.

Enquanto o [[Cerebro 1 — Claude]] pensa no momento e o [[Cerebro 3 — Obsidian]] lembra pra sempre, o Mega-Brain e a **sabedoria** — saber COMO fazer as coisas da melhor forma.

## Componentes

### [[Conclave]] — Decisao Estrategica

O sistema de debate interno pra decisoes de alto risco:

| Agente | Papel |
|--------|-------|
| @conclave-critico | Audita logica, exige provas |
| @conclave-advogado | Ataca o plano, worst-cases |
| @conclave-sintetizador | Integra tudo, decide |

Ativado quando: arquitetura, risco, mudancas irreversiveis, escolhas complexas.

### Skills — Expertise Acumulada

Conhecimento especializado documentado no vault do Obsidian:

| Skill | O que contem |
|-------|-------------|
| [[Skill — Frontend Master]] | CSS 2026, animacoes, performance, acessibilidade, design tokens |
| [[Skill — Voice Realtime]] | Arquiteturas de voz, VAD, streaming TTS, latencia |
| [[Skill — Delivery System]] | Tiers de execucao, parallelismo, quality gates, speed principles |

Cada skill e um manual completo que torna o Claude **melhor** do que um LLM base. Sao padroes testados e validados.

### Quality Gates — Validacao Automatica

Toda entrega passa por:

| Gate | Pergunta |
|------|----------|
| Correctness | Faz o que foi pedido? |
| No regression | Quebrou algo? |
| Completeness | Falta algo? |
| Performance | Vai ser lento ou caro? |

## Como alimenta os outros cerebros

```
Mega-Brain (skills + conclave)
    | alimenta
Claude (usa skills pra executar melhor)
    | aprende
Obsidian (salva o que funcionou)
    | retroalimenta
Mega-Brain (skills atualizados)
```
