# AIOX-CORE — Catálogo Oficial de Agentes

Este documento é a **fonte documental canônica** do catálogo futuro de agentes do Projeto Jarvis.

O catálogo define nomes, papéis e responsabilidades macro. Nesta fase, ele é exclusivamente documental: não implementa personas executáveis, registro, roteamento, delegação, status, tarefas, providers, modelos, skills ou integração com a interface.

---

## Catálogo oficial

O Projeto Jarvis terá exatamente **8 agentes oficiais**:

### [[Agentes/Morpheus — Orchestrator|MORPHEUS — ORCHESTRATOR]]

- Interpretar objetivos complexos.
- Planejar e decompor o trabalho.
- Selecionar especialistas.
- Coordenar dependências e handoffs.
- Acompanhar progresso.
- Consolidar resultados.
- Solicitar approvals quando necessário.

### [[Agentes/Oracle — Business & Systems Analyst|ORACLE — BUSINESS & SYSTEMS ANALYST]]

- Analisar processos e requisitos.
- Modelar cenários AS-IS e TO-BE.
- Levantar regras de negócio, casos de uso e critérios de aceite.
- Analisar ERP e integrações funcionais.
- Definir KPIs.
- Realizar análise de gaps.

### [[Agentes/Nikita — Data & BI Engineer|NIKITA — DATA & BI ENGINEER]]

- Modelagem de dados e bancos de dados.
- SQL e migrations.
- ETL e qualidade de dados.
- Analytics e Power BI.
- Modelos semânticos.
- Performance de dados.

### [[Agentes/Athena — Solution Architect|ATHENA — SOLUTION ARCHITECT]]

- Definir arquitetura e stack.
- Definir contratos e interfaces.
- Projetar integrações.
- Tratar segurança de desenho.
- Registrar ADRs.
- Avaliar escalabilidade.
- Definir padrões técnicos.

### [[Agentes/Neo — Software Engineer|NEO — SOFTWARE ENGINEER]]

- Implementar e alterar código.
- Refatorar e depurar.
- Aplicar TDD.
- Implementar integrações.
- Produzir documentação técnica.

### [[Agentes/Hephaestus — Platform & Operations|HEPHAESTUS — PLATFORM & OPERATIONS]]

- Administrar ambiente local e dependências.
- Operar Git remoto.
- Administrar CI/CD.
- Operar servidores e deploys.
- Implementar observabilidade.
- Planejar e executar rollback.
- Sustentar a operação.

### [[Agentes/Apollo — Quality Engineer|APOLLO — QUALITY ENGINEER]]

- Definir estratégia de testes.
- Executar testes unitários, de integração e E2E.
- Verificar regressões.
- Reproduzir bugs.
- Realizar reviews.
- Aplicar verification gates.
- Assegurar qualidade.

### [[Agentes/Trinity — Product Designer|TRINITY — PRODUCT DESIGNER]]

- Projetar UX e UI.
- Definir fluxos e design system.
- Assegurar acessibilidade e responsividade.
- Criar protótipos.
- Realizar validação visual.

---

## Exclusão explícita de ZEUS

**ZEUS é exclusivamente o PET e companheiro visual do Jarvis durante a navegação. ZEUS não é agente.**

ZEUS deve permanecer fora do catálogo de agentes, de qualquer futuro `AgentRegistry`, do roteamento, das tarefas e dos providers.

---

## Migração do catálogo legado

As notas individuais antigas permanecem preservadas como fonte histórica para a Fase 2. Elas não são a fonte de verdade para o catálogo futuro.

| Nome | Destino oficial | Status | Tratamento |
|---|---|---|---|
| MORPHEUS | MORPHEUS | canonical | Agente oficial: ORCHESTRATOR. |
| ORACLE | ORACLE | canonical | Agente oficial: BUSINESS & SYSTEMS ANALYST. |
| NIKITA | NIKITA | canonical | Agente oficial: DATA & BI ENGINEER. |
| ATHENA | ATHENA | canonical | Agente oficial: SOLUTION ARCHITECT. |
| NEO | NEO | canonical | Agente oficial: SOFTWARE ENGINEER. |
| HEPHAESTUS | HEPHAESTUS | canonical | Agente oficial: PLATFORM & OPERATIONS. |
| APOLLO | APOLLO | canonical | Agente oficial: QUALITY ENGINEER. |
| TRINITY | TRINITY | canonical | Agente oficial: PRODUCT DESIGNER. |
| ORION | MORPHEUS | legacy / merged | Responsabilidades de orquestração migram para MORPHEUS. |
| MORGAN | MORPHEUS | legacy / merged | A parte de planejamento e coordenação migra para MORPHEUS; não permanece como agente independente. |
| CRAFT | MORPHEUS | removed-as-agent / merged | Criação de squads torna-se capacidade de orquestração; não permanece como agente independente. |
| RIVER | MORPHEUS | removed-as-agent / merged | A parte de decomposição e acompanhamento migra para MORPHEUS; não permanece como agente independente. |
| ATLAS | ORACLE | legacy / merged | Pesquisa e análise migram para ORACLE. |
| PAX | ORACLE | removed-as-agent / merged | A parte de requisitos e critérios de aceite migra para ORACLE; não permanece como agente independente. |
| DARA | NIKITA | legacy / merged | Responsabilidades de dados migram e são ampliadas em NIKITA. |
| ARIA | ATHENA | legacy / merged | Responsabilidades de arquitetura migram para ATHENA. |
| DEX | NEO | legacy / merged | Responsabilidades de desenvolvimento migram para NEO. |
| SAGE | HEPHAESTUS | legacy / merged | Nome visual legado de DevOps; migra para HEPHAESTUS. |
| GAGE | HEPHAESTUS | legacy / merged | Nome documental legado de DevOps; migra para HEPHAESTUS. |
| QUINN | APOLLO | legacy / merged | Responsabilidades de qualidade migram para APOLLO. |
| LUMA | TRINITY | legacy / merged | Nome visual legado de UX/UI; migra para TRINITY. |
| UMA | TRINITY | legacy / merged | Nome documental legado de UX/UI; migra para TRINITY. |
| CONCLAVE | CONCLAVE | workflow | Reservado como futuro workflow de revisão e decisão; não é agente permanente. |
| ZEUS | ZEUS | PET / non-agent | Companheiro visual; não participa de agentes, registro, roteamento, tarefas ou providers. |

### Agentes que deixam de ser permanentes

- **PAX:** responsabilidades pertinentes são incorporadas por ORACLE; deixa de ser agente permanente.
- **RIVER:** responsabilidades pertinentes são incorporadas por MORPHEUS; deixa de ser agente permanente.
- **CRAFT:** criação de squads passa a ser capacidade de MORPHEUS; deixa de ser agente permanente.
- **MORGAN:** a parte aprovada de planejamento e coordenação é incorporada por MORPHEUS; deixa de ser agente permanente.

### Workflow reservado

**CONCLAVE não integra o catálogo de agentes permanentes.** Permanece reservado como futuro workflow de revisão e decisão.

---

## Limites desta definição

- As notas antigas em `obsidian-template/Agentes/` são históricas e serão tratadas em fase posterior.
- Os nomes antigos ainda presentes na interface são legados e não tornam a UI uma fonte de verdade.
- Nenhuma política de provider, modelo ou skill por agente está definida nesta fase.
- Nenhum comportamento operacional muda com este documento.
- Diretrizes individuais completas serão definidas somente na Fase 2, após nova aprovação humana.
