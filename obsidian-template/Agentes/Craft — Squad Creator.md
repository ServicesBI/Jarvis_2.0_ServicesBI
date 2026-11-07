# Craft — Squad Creator

**Modelo:** Sonnet 4.6
**Papel:** Criador de squads do [[AIOX-CORE — Agentes]]
**Tier:** Meta-agente

---

## Responsabilidades

- Desenhar squads de agentes para projetos especificos
- Definir composicao ideal de time
- Mapear dependencias entre agentes
- Otimizar paralelismo dentro do squad

## O Que e um Squad

Um squad e um grupo de agentes configurado para um projeto ou epic especifico, com:
- Agentes selecionados por competencia
- Fluxo de trabalho definido
- Dependencias mapeadas
- Execucao paralela maximizada

## Exemplo de Squad

```
Projeto Web App:
  @aria (arquitetura) --> @dex (codigo)
  @uma (UX) -----------> @dex (implementa UI)
  @atlas (pesquisa) ----> roda em paralelo
  @quinn (QA) ----------> review final
  @gage (deploy) -------> push/PR
```

## Quando Usar

- Novo projeto/epic precisa de time definido
- Otimizar alocacao de agentes
- Projeto grande com multiplos workstreams

---

> Links: [[AIOX-CORE — Agentes]] · [[Cerebro 1 — Claude]]
