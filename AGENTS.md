# Projeto Jarvis — Agent Instructions

Before any repository work (planning, investigating, modifying, debugging, or reviewing), read **`JARVIS_MASTER.md`** in full.

`JARVIS_MASTER.md` is the shared canonical technical and operational context for all coding agents working on this repository — Claude and Codex must receive exactly the same description of the Jarvis architecture, status, decisions, and roadmap. Do not duplicate that architecture here; this file only adds operational rules specific to how agents must behave in this repo.

Apply the same source hierarchy and status semantics defined in `JARVIS_MASTER.md` (comportamento/runtime comprovado > testes > código > configuração > documentação > relatórios > planos `⏳ PLANNED`). Respect `JARVIS_MASTER.md`'s **CURRENT CHECKPOINT** section (§27): don't start anything listed under `DO NOT START` without an explicit request, and don't declare something `APPROVED` there without the evidence it requires.

If runtime/code/tests contradict `JARVIS_MASTER.md`, report the drift and reconcile it (fix the code or correct the document after validating) — never silently assume either side is correct.

For any change that touches architecture, a service, a relevant endpoint, a capability, an agent, a provider, a model, memory, persistence, operational configuration, the roadmap, or a feature's status: update `JARVIS_MASTER.md` before declaring the task complete (see its §29 Update Protocol). Implementation without that update is an incomplete task.

Preserve the existing (possibly dirty) worktree — never `git reset`/`checkout`/`clean` to discard uncommitted work. Never commit or push unless explicitly asked to in the current request.

---

# PROTOCOLO OBRIGATÓRIO — JARVIS

Estas regras valem para Claude, Codex e qualquer agente dev.

## Arquivos principais

| Responsabilidade | Arquivo |
|-----------------|---------|
| HTML/UI principal | `public/index.html` |
| Backend FastAPI e composição de rotas | `app/main.py` |
| Rotas, comandos, voz, mídia, arquivos e integrações | `app/api/` |
| Frontend JS | `public/script.js` |
| CSS externo | `public/style.css` |
| CSS inline | `public/index.html` |

## Regras operacionais

1. Trabalhar somente nos arquivos principais reais.
2. Antes de alterar código, confirmar qual é o arquivo principal correspondente.
3. Fazer alterações cirúrgicas — não alterar fora do escopo solicitado.
4. Nunca criar backup, patch, rescue, fix, copy ou arquivo temporário.
5. Nunca criar `CODEX.md`.
6. Não declarar teste real de navegador se só testou headless ou não testou.
7. Não afirmar que executou ação se a ação não foi realmente executada.
8. Não afirmar que criou, editou ou salvou arquivos sem ter feito isso.

<!-- Removido em 2026-09-05 (confirmado por busca no repo antes de remover, ver JARVIS_MASTER.md changelog):
"Nunca editar public/_quarentena_backups" e "Nunca restaurar jarvis-rescue-bindings.js"
referenciavam caminhos que nao existem mais neste repositorio. -->

## Roteamento de voz, agentes e executores

1. A voz do Jarvis pode receber comandos e solicitações do usuário.
2. A voz pode abrir recursos quando o comando for explícito: YouTube, Spotify, Instagram, Excel, Power BI, arquivos, ERP, SaaS e outros sistemas autorizados.
3. A voz pode iniciar uma solicitação de análise, geração ou correção, mas não deve fazer alteração invisível.
4. Quando o pedido envolver análise técnica, erro, código, arquivo, planilha, PDF, ERP, SaaS ou automação, o Jarvis deve rotear a tarefa para o executor adequado.
5. O executor pode ser Claude, Codex ou outro agente definido no projeto.
6. Se a tarefa exigir alteração de código, o agente deve abrir no VSCode o arquivo principal real correspondente e editar diretamente esse arquivo.
7. HTML principal: `public/index.html`.
8. Backend FastAPI e composição de rotas: `app/main.py`; rotas, comandos, voz, mídia, arquivos, integrações, ERP e SaaS: `app/api/`.
9. Frontend JS: `public/script.js`.
10. CSS externo: `public/style.css`.
11. CSS inline: `public/index.html`.
12. Nunca criar backup, patch, rescue, fix, copy ou arquivo paralelo.
13. Nunca afirmar que uma ação foi executada sem execução real.
14. Para escrita de arquivos, criação de planilhas, geração de PDFs ou alteração de código, manter confirmação de segurança quando aplicável.
15. Pesquisas externas poderão usar ChatGPT, Google, Perplexity ou outra fonte definida posteriormente.
16. O Jarvis deve responder ao usuário com o resultado da tarefa ou com o próximo passo necessário.

<!-- Removido em 2026-09-05: "Nunca editar arquivos dentro de public/_quarentena_backups"
referenciava um caminho que nao existe mais neste repositorio (confirmado por busca). -->

## Resposta final obrigatória

Toda entrega deve terminar com:

1. Arquivo alterado.
2. Causa.
3. Correção feita.
4. Validação executada.
5. Resultado.

## Exceção autorizada — subsistema de memória do Jarvis

Esta exceção aplica-se exclusivamente a tarefas solicitadas explicitamente pelo proprietário para implementar, corrigir, testar ou diagnosticar as três camadas de memória do Jarvis:

1. Memória Local.
2. Obsidian.
3. Mega Brain.

Dentro desse escopo, fica autorizado:

- Editar os módulos FastAPI responsáveis pela memória em `app/`.
- Editar `public/index.html`.
- Editar `public/script.js`.
- Editar `public/style.css`.
- Editar `.gitignore`.
- Criar e editar `system/JARVIS-MEMORY.md`.
- Criar e editar módulos exclusivamente dentro de `integrations/node/memory/`.
- Criar armazenamento e índices exclusivamente dentro de `system/mega-brain/`.
- Criar testes exclusivamente dentro de `tests/memory/`.
- Criar fixtures exclusivamente dentro de `tests/fixtures/memory/`.
- Criar arquivos temporários transitórios somente para gravações atômicas.

Regras obrigatórias para arquivos temporários:

- Devem ser criados no mesmo diretório do arquivo final.
- Devem usar identificação inequívoca de arquivo temporário.
- Devem ser substituídos pelo arquivo final usando rename atômico.
- Devem ser removidos em caso de sucesso ou erro.
- Nunca podem permanecer no repositório.
- Nunca podem ser adicionados ao Git.

Regras de segurança:

- `system/JARVIS-MEMORY.md` deve permanecer local e ser protegido pelo `.gitignore`.
- O armazenamento e os índices gerados em `system/mega-brain/` devem permanecer locais e ser protegidos pelo `.gitignore`.
- Chaves, tokens, credenciais, conteúdos pessoais e dados de memória não podem ser expostos em endpoints, logs, testes ou Git.
- Não apagar, sobrescrever ou modificar `JARVIS-HISTORY.json`, `memory-embeddings.json` ou qualquer nota do Obsidian.
- Migrações devem preservar dados existentes.
- Não instalar dependências sem autorização.
- Não executar chamadas pagas para testar a memória.
- Não fazer commit, push, reset, checkout destrutivo ou troca de branch.
- Não alterar arquivos fora dos caminhos autorizados.
- Alterações existentes do usuário devem ser preservadas.
- Uma camada somente pode ser classificada como `operational` quando leitura, escrita, persistência e recuperação forem comprovadas por testes reais.
- Não inventar contagens, índices, projetos, timestamps ou estados operacionais.

Esta exceção não altera o protocolo para nenhuma outra funcionalidade do Jarvis. Fora do subsistema de memória, continuam valendo integralmente as restrições originais.
