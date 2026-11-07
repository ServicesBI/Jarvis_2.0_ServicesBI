# JARVIS MASTER

**Purpose:** Canonical technical and operational description of Projeto Jarvis.

**Last verified:** 2026-09-05

**Repository:** `D:\python\ServicesBI_Jarvis`

**Current branch (at last verification):** `correcao-voz-main` (worktree has ~121 uncommitted changed/new files — active, in-progress architecture work; nothing here has been committed or pushed)

**Canonical status:** ACTIVE

> Este arquivo é a fonte canônica compartilhada por Claude e Codex para o estado, arquitetura, funcionalidades, decisões e roadmap do Projeto Jarvis. Ambos devem ler este documento por inteiro antes de planejar, investigar, modificar, depurar ou revisar este repositório.

### Se este documento estiver desatualizado

Se o runtime, o código ou os testes atuais provarem que este documento diverge da realidade, a IA deve:

1. **parar** — não seguir cegamente a documentação;
2. **identificar a divergência** com evidência concreta (arquivo, linha, teste, comportamento real);
3. **corrigir o problema ou esclarecer o estado real** com o usuário;
4. **atualizar `JARVIS_MASTER.md`** depois que o estado real for validado.

Hierarquia de evidência (da mais forte para a mais fraca): **comportamento/runtime comprovado → testes atuais → código atual → configuração operacional → documentação existente → relatórios/checkpoints → planos futuros (`⏳ PLANNED`)**.

### Estados usados neste documento

| Símbolo | Estado | Significado |
|---|---|---|
| ✅ | **APPROVED** | Implementado + testes relevantes + validação real concluída |
| 🟡 | **IMPLEMENTED / VALIDATION PENDING** | Código existe, falta validação operacional/humana definitiva |
| 🔵 | **IN PROGRESS** | Trabalho atualmente em execução |
| ⏳ | **PLANNED** | Ainda não implementado |
| ❌ | **BLOCKED** | Existe impedimento conhecido |
| ⚫ | **LEGACY / DEPRECATED** | Existe só por compatibilidade/histórico; não é a arquitetura principal |

---

## 1. PRODUCT VISION

Jarvis é um **assistente pessoal e operacional local-first** para Windows: um backend FastAPI (`app/`) servindo um frontend HTML/JS single-page (`public/index.html` + `public/script.js`, o "cockpit") na porta local `127.0.0.1:8000`, com automações de desktop (abrir apps, criar/abrir arquivos Office, Power BI), voz em tempo real, um catálogo de 8 agentes especialistas com personas e um sistema de execução de tarefas rastreável.

O usuário interage por:
- **texto** — chat livre no cockpit, roteado por padrão/comando/executor;
- **voz** — captura de microfone, transcrição, roteamento de comando rápido ou chat completo, síntese de resposta (TTS);
- **desktop** — abertura de aplicativos e arquivos allowlisted (Word, Excel, Power BI, VS Code) através de "actions" bounded e verificadas, nunca shell livre;
- **arquivos** — resolução e abertura de documentos dentro de subpastas oficiais de um workspace (`D:\Jarvis` por padrão);
- **Power BI** — fluxo completo comando → Desktop → Service → Publish to Web;
- **agents** — 8 especialistas com persona e prompt operacional próprios, executáveis via `/api/agents/{id}/run`, mais um orquestrador (MORPHEUS) que planeja e sequencia os demais;
- **providers** — Codex e Claude como provedores de execução de IA (CLI), OpenAI API para voz/visão; a seleção de provider é independente do agente;
- **memória** — um conjunto de arquivos locais (histórico, embeddings, Obsidian) hoje majoritariamente estático/legado (ver seção 14);
- **segurança** — nenhuma ação shell arbitrária é permitida (`ActionRegistry` rejeita qualquer nome de ação contendo `"shell"`); todo acesso a arquivo passa por `PathPolicy` restrita a raízes explícitas; toda execução de app/arquivo usa allowlist de executáveis validados por caminho + assinatura de nome, nunca só por `PATH`.

### Fluxo objetivo de alto nível (arquitetural — nem tudo abaixo já existe ponta a ponta)

```
User
  → Jarvis (frontend/voice/API)
  → intent (ActionDispatcher / comando de voz / agente selecionado)
  → capability (Action Engine: app.open, file.*, word.create, excel.create, powerbi.open)
  → agent (opcional: 1 dos 8 especialistas, ou nenhum — chat direto)
  → provider de chat (Codex CLI / Claude CLI, conforme executor_mode) ou OpenAI API complementar
  → execution (ChatExecutor / ActionDefinition.handler)
  → validation (ActionDefinition.verifier — comprova o efeito, não confia no handler)
  → persistence (TaskManager — hoje arquivo JSON; PostgreSQL implementado mas não em produção)
  → response (streaming de texto / ActionResult / status de Task)
```

O que **já existe** desse fluxo ponta a ponta hoje: capabilities de desktop (`app.open`, `file.*`, `word.create`, `excel.create`, `powerbi.open`) com handler+verifier reais, execução de agente único via chat (`AgentExecutionService`), e uma primeira orquestração sequencial de MORPHEUS (`MorpheusOrchestrationService`, só etapas `analysis`+auto-aprovadas). O que é **planejado** e ainda não existe: registro real de `AgentRun` por tentativa de execução (ver seção 13), roteamento agente→provider mais rico, e os agentes especialistas de domínio (Power BI, Financeiro — seção 7).

---

## 2. SYSTEM ARCHITECTURE

```
Jarvis
├── Frontend (public/index.html, public/script.js, public/executor-status.js, public/style.css)
├── FastAPI app (app/main.py — monta todos os routers e o app.state)
│   ├── API routers (app/api/*.py — ver Catálogo de Endpoints, seção 19)
│   ├── Voice (app/api/voice.py + OpenAIGateway)
│   ├── Chat (app/chat/* — ChatService, executors, factory, action_dispatcher)
│   ├── Orchestration/Agents (app/agents/* — registry, models, execution, orchestration, runtime, state)
│   ├── Providers (app/providers/* — models, manager, factory, adapters/codex, credentials)
│   ├── Executors (app/executors/* — availability, service, model_registry, cli, claude_auth, codex_auth)
│   ├── Action Engine (app/actions/* — engine, registry, policy, models, + 6 ActionDefinitions)
│   ├── Tasks (app/tasks/manager.py)
│   ├── Persistence (app/db/* — models, repositories, repositories_postgres, repositories_memory, engine, uow, migrate_task_state; alembic/)
│   ├── Power BI (app/powerbi/* — desktop, catalog, browser)
│   ├── Automation (app/automation/excel.py + app/api/automation.py)
│   ├── OpenAI Balance (app/core/openai_costs_ledger.py — atual; app/core/openai_balance.py — legado)
│   └── Operational services (app/core/config.py, openai_gateway.py, startup_guard.py, diagnostics.py)
├── Node/Chrome integrations (integrations/node/*, integrations/chrome/openai-balance-bridge — legado)
├── Memory/Docs (system/*.json,*.md, obsidian-template/)
└── Launcher scripts (run.py, Ligar JARVIS.bat, scripts/*.ps1, scripts/*.js)
```

Para cada bloco, ver a seção dedicada correspondente deste documento (Frontend → §4, Providers/Executors → §5, Agents → §6, Actions → §8, Files/Workspace → §9, Power BI → §10, Tasks → §11, Persistence → §12/13, Memory → §14, Voice → §15, Balance → §16, Health → §17).

---

## 3. RUNTIME AND STARTUP

**Módulo 1 — Core / Runtime:** ✅ APPROVED
- **1A — Runtime / Lifecycle:** ✅ APPROVED (2026-09-07)
- **1B — Config / Health:** ✅ APPROVED (2026-09-07)

- **Entry point:** `run.py` — importa `app` de `app/main.py` (module-level `app = create_app()`), roda `uvicorn.Server` diretamente (`server.run()`), sem `reload`.
- **Host/porta:** autoridade única em `app/core/config.py`; `HOST`/`PORT` aceitam ambiente e `.env`, com defaults seguros `127.0.0.1:8000`. O host é validado como loopback (`127.0.0.1` ou `localhost`) e a porta como inteiro entre 1 e 65535.
- **Detecção de instância existente:** `app/core/startup_guard.run_preflight(host, port)` — nunca decide só pelo bind da porta:
  1. tenta `bind()` na porta; se livre → `START`;
  2. se ocupada, faz `GET /api/health` real e confirma o contrato (`components.server.status == "ok"`) → se confirmado, `ALREADY_RUNNING` (não sobe uma segunda instância, evita `WinError 10048`);
  3. se ocupada por outra coisa (não é um Jarvis saudável) → `PORT_OCCUPIED`, e **nunca mata o processo automaticamente** (só reporta `describe_port_owner`, best-effort via `netstat`/`psutil`).
- **Shutdown gracioso:** `POST /api/jarvis/shutdown` (`app/main.py`) agenda `_request_uvicorn_shutdown` como `BackgroundTask` (aguarda a resposta HTTP ser enviada, depois seta `server.should_exit = True`) — usado por esta própria auditoria para reiniciar o processo real sem `taskkill`.
- **Startup FastAPI:** `create_app()` monta `app.state` com todos os serviços (chat, agents, providers, executors, tasks, balance, notifications); `TaskManager.__init__()` apenas carrega o estado em memória, sem reconciliar ou persistir. A reconciliação de Tasks roda explicitamente no evento de `startup`, tanto no modo arquivo quanto no modo repository/Postgres, para que `app = create_app()` na importação do módulo não produza mutação operacional.
- **Como iniciar:** `Ligar JARVIS.bat` consulta `HOST`/`PORT` em `app/core/config.py` → chama `scripts/jarvis-python-control.ps1 -Action Check` (idempotente) → se necessário, `start "Jarvis Python" /D <root> .venv\Scripts\python.exe run.py` → espera `/api/health` responder (até 30s) → abre a URL local configurada em modo app do Chrome/Edge (`--app=...`) só para a UI local do próprio Jarvis (não relacionado a OpenAI).
- **Como desligar:** `Desligar JARVIS.bat` aciona `scripts/jarvis-python-control.ps1`, que confirma o contrato Jarvis em `/api/health` por `components.server.status == "ok"` (sem depender do status global), confirma o processo Python, solicita `POST /api/jarvis/shutdown` e aguarda de forma bounded a liberação da porta; não usa `Stop-Process -Force` no caminho normal.
- **Variáveis operacionais relevantes:** ver Catálogo de Configuração (seção 20).
- **Riscos conhecidos:** nenhum processo órfão documentado no backend Python em si; o risco real e comprovado nesta auditoria estava fora do processo Python — na extensão Chrome `openai-balance-bridge` (ver §16 e §25), que tem lifecycle próprio dentro do navegador do usuário e sobrevive a restarts do backend.

---

## 4. FRONTEND / HUD

Frontend estático (`public/index.html` + `public/script.js` + `public/executor-status.js`), sem framework, servido pelo próprio FastAPI (`StaticFiles`).

| Elemento visual | Fonte de dados | Arquivo/função |
|---|---|---|
| **SERVER ONLINE → API** (saldo US$) | `GET /api/openai-balance` | `public/script.js::updateOpenAIBalance()` |
| **SERVER ONLINE → EXECUTOR** (dot + texto, AUTO/CLAUDE/CODEX) | `GET /api/providers/health` via `window.ExecutorStatus.resolveExecutorStatus` | `public/executor-status.js`, consumido em `public/script.js::updateHealth()`/`setExecutorHudStatus()` |
| **VOZ** (MUTE/OUVINDO/PROCESSANDO/FALANDO) | estado local do cliente (WebRTC Realtime) | `public/script.js` (máquina de estados de voz) |
| **AIOX-CORE / AGENTS** (grid de 8 cards) | `GET /api/agents` — "sole runtime source" (comentário no próprio código) | `public/script.js::createAioxAgentCard`/`loadAioxAgents` |
| **AI MODELS** (MAX/PRO/FAST por provider) | `GET /api/executor/profiles` | `public/script.js::renderAiModelCatalog`/`renderModelProfiles` |
| **Monitor de Tasks** (card "Tasks" + painel expansível) | `GET /api/tasks/summary` | `public/script.js` (metrics-tasks-card) |

Semântica visual do dot/texto do executor (`formatProviderStatus` em `executor-status.js`):
- `status == "online"` → texto `ONLINE`, tom `online` (verde);
- `reason == "capability_not_validated"` (instalado+autenticado, mas nunca observado em execução real) → texto `CHECK`, tom `neutral` (nem verde nem vermelho) — **corrigido nesta mesma linha de trabalho**: antes dizia `READY` (contradição semântica com o dot não-verde), corrigido para `CHECK` (ver §18, §28);
- `offline`/`not_installed` → `OFF`; `not_authenticated` → `AUTH`; `entitlement_unavailable` → `PLAN`; outro erro → `ERROR`.

**Problema visual pendente registrado:** nenhum aberto no momento da última verificação — a inconsistência READY/dot-neutro foi corrigida e validada com execução real (ver §18).

---

## 5. PROVIDERS AND EXECUTORS

**Módulo 2 — Providers & Execution:** ✅ APPROVED
- **2A — Availability / API Coherence:** APROVADO (RED → GREEN e regressão bounded em 2026-09-07)
- **2B — Execution Contracts:** APROVADO (RED → GREEN e regressão bounded em 2026-09-07)

Separação conceitual confirmada no código:

- **PROVIDER** = um backend de IA/serviço com identidade própria (`app/providers/models.py::ProviderDefinition`): `codex`, `openai`, `claude`, `gemini`, `google-account`, `microsoft-account`, `powerbi`, `vscode`, `erp-generic` (catálogo estático em `app/providers/factory.py::PROVIDER_DEFINITIONS`). **Só `codex` tem um adapter real registrado** (`CodexProviderAdapter`, via `create_provider_manager(codex_adapter=...)`); os demais são definições estáticas sem adapter — ver ADR-002 e Known Issues.
- **AGENT** = uma persona/especialidade (`app/agents/models.py::AgentDefinition`), 8 no total (§6). Um agente **não é** um provider: ele executa reaproveitando o `ChatService` já configurado, então roda sobre **qualquer** provider que estiver ativo no `executor_mode` no momento.
- **EXECUTION MODE** = a seleção manual/automática de qual provider processa o chat: `auto | claude | codex` (`app/executors/service.py::VALID_EXECUTOR_MODES`), controlado por `ExecutorService` (estado em memória, `GET/POST /api/executor/mode`). OpenAI permanece integração complementar para voz/visão/APIs específicas, não um modo de chat.

### Fonte única de verdade de disponibilidade

`app/executors/availability.py::ProviderAvailabilityService` é a autoridade confirmada no código para: `installed`, `authenticated`/`connected`, `operational`, `eligible` (propriedade derivada: `installed and authenticated and operational and automatic_allowed`), `entitled`, `reason`. Consumida por `/api/providers`, `/api/providers/{id}`, `/api/providers/health`, `/api/health` (campo `claude`) e `/api/executor/profiles`. O `ProviderManager` permanece como catálogo/metadata; para Codex, Claude e OpenAI, suas rotas projetam diretamente o estado operacional canônico sem manter uma segunda verdade sincronizada.

`ExecutorService` (`app/executors/service.py`) é autoridade **só** para `execution_mode` (`get_mode`/`set_mode`) e `active_profile` (`get_profile`/`set_profile`, MAX/PRO/FAST) — nunca reimplementa health.

### CODEX

- **Discovery:** `ExecutorService.get_command("codex")` — ordem: `JARVIS_CODEX_CMD` → `codex` no `PATH` (`shutil.which`) → extensão VS Code bundled (`~/.vscode/extensions/openai.chatgpt-*/bin/windows-x86_64/codex.exe`, a mais recente por nome).
- **CODEX_HOME:** `codex_subprocess_environment()` — usa `CODEX_HOME` do ambiente se definido; senão `~/.codex`.
- **Autenticação:** `app/executors/codex_auth.py::CodexAuthService` — só executa `codex login/status/logout` oficiais, nunca manipula credenciais diretamente.
- **Probe de disponibilidade:** registrado em `app/main.py` com `authentication_implies_operational=True` — autenticação confirmada já implica `operational=True` (Codex é tratado como confiável assim que autenticado).
- **AUTO eligibility:** Codex é o primeiro da prioridade (`AUTO_PROVIDER_PRIORITY = ("codex", "claude")`).

### CLAUDE

- **CLI path:** `CLAUDE_CLI_PATH` → `JARVIS_CLAUDE_CMD` → `"claude"`; resolve para o binário nativo (`claude.exe` dentro de `node_modules/@anthropic-ai/claude-code/bin`) quando o comando aponta para um `.cmd`/`.bat`.
- **Autenticação:** `app/executors/claude_auth.py::ClaudeAuthService` — só `claude auth status/login/logout --json`.
- **Probe de disponibilidade:** registrado com `authentication_implies_operational=False` — autenticação **não** implica operacional; `operational` só vira `True` via `record_success()` após uma execução real bem-sucedida (ver §18).
- **AUTO eligibility:** segundo da prioridade, depois de Codex.

### Mapeamento de modelos (confirmado em `app/executors/model_registry.py::ModelRegistry.default()`)

| Provider | MAX | PRO (padrão) | FAST |
|---|---|---|---|
| CODEX | `gpt-5.6-sol` → "GPT-5.6 Sol" | `gpt-5.6-terra` → "GPT-5.6 Terra" | `gpt-5.6-luna` → "GPT-5.6 Luna" |
| CLAUDE | `opus` → "Opus 5" | `sonnet` → "Sonnet 5" | `haiku` → "Haiku 4.5" |

AUTO histórico confirmado no código: **Codex → Claude** (`AUTO_PROVIDER_PRIORITY`).

Contrato de fallback confirmado: `fallbackEnabled` é derivado de `ExecutorService.get_mode()` e só é `true` em `auto`; os modos manuais `codex` e `claude` não anunciam fallback automático. A rota FastAPI não usa detecção CLI legada: `ExecutorService.provider_health()` e `core.diagnostics.get_provider_health()` foram removidos por não possuírem callers ativos.

Nenhuma credencial é registrada neste documento.

---

## 6. AGENT SYSTEM

Fonte runtime única e ordenada: `app/agents/registry.py::CANONICAL_AGENT_DEFINITIONS` (8 agentes). **Não confiar em nenhuma outra lista** — há uma lista muito maior e diferente documentada no vault Obsidian (`obsidian-template/Agentes/`, 22 arquivos incluindo Aria, Atlas, Craft, Dara, Dex, Gage, Morgan, Orion, Pax, Quinn, River, Uma, Conclave-*) que **não corresponde** ao registry runtime — tratar como histórico/legado, não como fato atual (ver Known Issues §25). Há também um array morto e nunca usado em `public/index.html` (`AIOX=['ORION','ARIA',...]`) que não alimenta nenhum elemento visual real — o grid real (`#aiox-agents-grid`) é populado exclusivamente por `GET /api/agents`.

| agent_id | display_name | role | missão (descrição no registry) | persona doc |
|---|---|---|---|---|
| `morpheus` | MORPHEUS | ORCHESTRATOR | Planeja, decompõe, coordena especialistas, acompanha dependências e consolida resultados | `obsidian-template/Agentes/Morpheus — Orchestrator.md` |
| `oracle` | ORACLE | BUSINESS & SYSTEMS ANALYST | Analisa processos, requisitos, regras de negócio, ERP, critérios de aceite e KPIs | `.../Oracle — Business & Systems Analyst.md` |
| `nikita` | NIKITA | DATA & BI ENGINEER | Modela e processa dados, bancos, ETL, analytics, Power BI e modelos semânticos | `.../Nikita — Data & BI Engineer.md` |
| `athena` | ATHENA | SOLUTION ARCHITECT | Define arquitetura, stack, contratos, integrações, segurança, escalabilidade e padrões técnicos | `.../Athena — Solution Architect.md` |
| `neo` | NEO | SOFTWARE ENGINEER | Implementa, testa, refatora e depura software, integrações e documentação técnica | `.../Neo — Software Engineer.md` |
| `hephaestus` | HEPHAESTUS | PLATFORM & OPERATIONS | Prepara ambientes, entrega, observa, opera e recupera sistemas com segurança | `.../Hephaestus — Platform & Operations.md` |
| `apollo` | APOLLO | QUALITY ENGINEER | Define e executa testes, regressão, reprodução de bugs, reviews e verification gates | `.../Apollo — Quality Engineer.md` |
| `trinity` | TRINITY | PRODUCT DESIGNER | Projeta UX, UI, fluxos, design systems, acessibilidade e validação visual | `.../Trinity — Product Designer.md` |

Estado visual (`AgentStatus`: `idle|working|waiting|error`) é runtime puro, mantido por `app/agents/state.py::AgentRuntimeStateService` (dict em memória, thread-safe, default `idle`) — **não persiste** entre restarts e é distinto da definição imutável do registry.

### Como um agente executa (evidência: `app/agents/execution.py`, `app/agents/runtime.py`)

Cada um dos 7 especialistas (todos exceto MORPHEUS) tem um **operating profile runtime** fixo em código (`app/agents/runtime.py::_OPERATING_PROFILES`) com: `operating_prompt` (identidade+missão+regras específicas, ex.: NEO não pode "fingir que ações foram executadas"), `responsibilities`, `boundaries`, `completion_criteria`. `AgentExecutionService.run(agent_id, message)` monta um `ChatRequest(message=f"{operating_prompt}\n\n{message}", agent_id=agent_id)` e o envia pelo **mesmo** `ChatService`/executor configurado (`ModeAwareChatExecutor`) que o chat manual usa — **não existe um segundo motor de execução para agentes**; o provider ativo (Codex/Claude/OpenAI, conforme `executor_mode`) é quem realmente roda. Isso confirma a ADR-002 (`§23`): agentes e providers são camadas ortogonais.

MORPHEUS **não** é executável via `POST /api/agents/{id}/run` (não está em `_OPERATING_PROFILES`) — só via `POST /api/agents/morpheus/plan`, que usa `MorpheusOrchestrationService` (ver abaixo).

### Orquestração (MORPHEUS) — `app/agents/orchestration.py`

Primeira orquestração sequencial real (comentário no código: "Fase 5A"). MORPHEUS gera um `OrchestrationPlan` (JSON validado por Pydantic, `extra="forbid"`, rejeitado inteiramente se inválido — mesmo princípio de `ExcelGeneratedContent`): `objective`, `summary`, até 10 `steps` (cada um com `step_id`, `agent_id` restrito aos 7 especialistas — nunca `morpheus`/`zeus`/`conclave` —, `objective`, `phase` ∈ `{analysis, implementation, validation, operations}`, `requires_approval`). `MorpheusOrchestrationService._run_plan` executa em sequência **só** as etapas `auto_executable` (`phase == "analysis" and requires_approval is False`); no primeiro step que exigir aprovação, para e retorna `waiting_approval` — nunca implementa/opera sem parar para aprovação humana, mesmo que o plano inteiro seja "analysis".

Estado: ✅ **APPROVED** (implementado, testado; ver `app/agents/orchestration.py` docstring "Fase 5A" e testes correspondentes — sem paralelismo, sem DAG, sem persistência de plano).

---

## 7. PLANNED SPECIALIST AGENTS

### POWER BI SPECIALIST AGENT — ⏳ PLANNED

Objetivo: especialista dedicado em Power BI (abertura, análise, DAX, Power Query, modelagem, KPIs, refresh, troubleshooting, publicação, Service, Desktop).

**Não implementado.** Nenhum arquivo, `agent_id`, ou capability específica existe hoje para isso. A capability `powerbi.open` (§8, §10) já existe mas é uma **action determinística**, não um agente com raciocínio próprio.

### FINANCE SPECIALIST AGENT — ⏳ PLANNED

Objetivo: especialista dedicado em análise financeira (fluxo de caixa, contas a pagar/receber, conciliação, DRE, orçamento x realizado, forecast, aging, indicadores, anomalias, análise executiva).

**Não implementado.** Nenhum código relacionado existe no repositório hoje.

**Dependência arquitetural registrada:** avaliar a implementação de qualquer um dos dois **somente depois** da estabilização de `AgentRun`/P3 (§13) e do roteamento agente→provider mais rico — para reutilizar a mesma arquitetura de agent/provider (`ADR-010`, §23) em vez de criar um executor paralelo.

---

## 8. ACTION ENGINE AND CAPABILITIES

- **`app/actions/engine.py::ActionEngine`** — ponto único de submissão: resolve a definição (`ActionRegistry.resolve`, valida allowlist de `source`), valida argumentos (Pydantic `input_model`), autoriza (`ActionPolicy.authorize` — levanta `ConfirmationRequiredError` se `confirmation_required` e não `confirmed`), executa via `TaskManager.submit` (task rastreável, com timeout e `desktop_exclusive` por definição), e **exige verificação**: se `definition.verifier` existir e retornar `False`, levanta `ActionVerificationError` mesmo que o handler tenha retornado `ok=True` — o handler nunca é a fonte de verdade sozinho.
- **`app/actions/registry.py::ActionRegistry`** — allowlist pura; nomes têm que casar `^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$`; **qualquer ação com `"shell"` no nome é rejeitada estruturalmente** (`UnsafeActionError`), tanto no registro quanto na resolução.
- **`app/actions/policy.py`**:
  - `PathPolicy` — todo acesso a arquivo é validado contra `read_roots`/`write_roots` explícitos (resolvidos), nunca caminho livre;
  - `ActionPolicy.authorize` — gate de confirmação explícita;
  - `ActionPolicy._sanitize`/`persistent_result` — redige qualquer chave que contenha `token`, `secret`, `credential`, `password`, `api_key`, `clipboard`, `prompt` antes de persistir o resultado da action.
- **Dispatcher (`app/chat/action_dispatcher.py::ActionDispatcher`)** — classificação **determinística por regex** (não por LLM) do texto do chat/voz em: `ActionRequest` direto, `WordContentDraft`/`ExcelContentDraft` (quando o conteúdo precisa ser elaborado por um provider antes de virar `ActionRequest`), `FileOpenIntent`, ou `None`.

### Tabela de capabilities confirmadas

| Capability | Objetivo | Entrada | Risco | Confirmação | Handler | Estado | Testes principais |
|---|---|---|---|---|---|---|---|
| `app.open` | Abrir app allowlisted (vscode/word/excel/powerbi) | `application` (enum literal) | `DESKTOP` | não | `app/actions/app_open.py` | ✅ APPROVED | `tests/actions/` |
| `file.resolve` | Resolver filename literal nas subroots oficiais (Word/Excel/Power BI) | `name` (filename literal, sem path/wildcard) | `READ` | não | `app/actions/file_resolve.py` | ✅ APPROVED | idem |
| `file.open` | Abrir arquivo autorizado na subroot correspondente à extensão | `path` | `DESKTOP` | não | `app/actions/file_open.py` | ✅ APPROVED | idem |
| `word.create` | Criar `.docx` na workspace Word | `filename`, `content`, `title?`, `overwrite?` | `WRITE_FILE` | não | `app/actions/word.py` (via `python-docx`) | ✅ APPROVED | idem |
| `excel.create` | Criar `.xlsx` na workspace Excel | `filename?`, `headers?`, `rows?`, `sheet?`, `openFile?` | `WRITE_FILE` | não | `app/actions/excel.py` → `app/automation/excel.py::create_workbook` | ✅ APPROVED | idem |
| `powerbi.open` | Confirmar Desktop e então abrir Power BI Service (+ Publish to Web se cadastrado) | `name` | `EXTERNAL` | não | `app/actions/powerbi_open.py` | ✅ APPROVED (ver ressalvas §10) | `tests/powerbi/` |

Todas as 6 exigem `verifier` (`requires_verification=True` por padrão) — nenhuma é considerada bem-sucedida só pelo retorno do handler.

Nenhuma capability shell/arbitrária existe ou é permitida por desenho.

---

## 9. FILE AND WORKSPACE SYSTEM

Raiz operacional: `WORKSPACE_ROOT` (`app/core/config.py::_workspace_root()`), padrão `D:\Jarvis`, sobrescrevível por `JARVIS_WORKSPACE_ROOT` — **nunca pode ser um volume inteiro** (validação estrutural: `if root == Path(root.anchor): raise ValueError`).

Subpastas confirmadas no código:

| Subpasta | Constante | Extensões aceitas |
|---|---|---|
| `D:\Jarvis\Word` | `WORD_WORKSPACE` | `.docx` |
| `D:\Jarvis\Excel` | `EXCEL_WORKSPACE` | `.xlsx`, `.xlsm` |
| `D:\Jarvis\Power BI` | `POWERBI_WORKSPACE` | `.pbix` |
| `D:\Jarvis\VS Code` | `VSCODE_WORKSPACE` | (referenciada, sem capability de arquivo própria hoje) |

- **Resolução de nomes:** `file.resolve` aceita só um filename literal (`name`, sem `/`, `\`, `:`, `*`, `?`, `[`, `]`); se o nome não tiver extensão, procura em todas as 3 raízes pelo *stem*; se tiver extensão, restringe à raiz correspondente. Resultado: `found` (exatamente 1 match) | `not_found` (0) | `ambiguous` (>1, retorna a lista de candidatos — nunca escolhe sozinho).
- **Ambiguidade:** nunca resolvida automaticamente — sempre devolvida ao chamador como `ambiguous` + candidatos.
- **`PathPolicy`:** todo caminho é `Path(...).expanduser().resolve()` e comparado contra as raízes autorizadas (`==` ou ancestral); leitura exige `path.exists()`.
- **Abertura:** `file.open` resolve o app correto pela extensão (`EXTENSION_APPLICATIONS`), valida o executável (`resolve_application` + `_safe_executable`: nome exato + `.exe` + dentro de uma raiz confiável do Registro do Windows/Program Files), e só então chama `subprocess.Popen([executável, arquivo], shell=False)`. Rejeita explicitamente caminhos de rede/UNC (`\\...`).
- **Criação:** `word.create`/`excel.create` só escrevem dentro da raiz correspondente (`PathPolicy(write_roots=(root,))`), com sanitização de nome de arquivo e checagem de `overwrite`.
- **Associação app/extensão:** `EXPECTED_EXECUTABLES` (`app/actions/app_open.py`) — `vscode→Code.exe`, `word→WINWORD.EXE`, `excel→EXCEL.EXE`, `powerbi→PBIDesktop.exe`; resolução por Registro do Windows (`App Paths`) → caminhos conhecidos (Program Files) → `PATH`, sempre revalidada contra raízes confiáveis antes do lançamento.

---

## 10. POWER BI

Arquitetura real de `powerbi.open` (`app/actions/powerbi_open.py`, `app/powerbi/{desktop,catalog,browser}.py`):

```
comando natural do chat ("abra o dashboard X")
  → ActionDispatcher._powerbi_open_request (regex)
  → PowerBIOpenInput.normalize_name (bloqueia extensões .docx/.xlsx/.xlsm; trata alias oficial
    "Real X Meta (Recomendações)" → "Real X Meta (Recomendações).pbix")
  → file_resolver: resolve_file_name() na workspace Power BI (found/not_found/ambiguous)
  → catalog_lookup: find_report_link() no catálogo local
    (%LOCALAPPDATA%\ServicesBI_Jarvis\powerbi\reports.json — read-only, fail-closed, máx. 1MB,
    schema estrito {version, reports[]}, cada report com local_file/connection_id/workspace_id/
    report_id/publish_to_web_src opcional)
  → validate_file_path() confirma o .pbix real na workspace
  → desktop_opener: open_powerbi_desktop()
      • abre por associação do Windows (os.startfile) — nunca hardcoda o caminho do PBIDesktop.exe
      • ANTES de abrir, tira um snapshot de processos+janelas (via ctypes/EnumWindows) e verifica se
        já existe uma janela "<nome> - Power BI Desktop" visível/respondendo → status ALREADY_OPEN
      • se não, lança e faz polling (até timeout=90s, passo 0.5s) até a janela aparecer → OPENED
      • se não aparecer no timeout → FAILED, error_code="report_not_loaded"
  → se Desktop não abriu/confirmou: FALHA (outcome="failed"), não tenta o Service
  → catalog.status precisa ser "found" (vínculo online cadastrado); senão FALHA
  → browser_opener: open_powerbi_report() — resolve um Chrome confiável (Registro/Program Files,
    nunca "which" livre sem revalidação) e abre https://app.powerbi.com/groups/<workspace>/reports/<report>
    (URL validada estruturalmente, esquema/host/porta/path exatos — sem query, sem fragment)
  → se catalog.link.publish_to_web_src existir: open_powerbi_publish_to_web() também abre esse link
    (validado: https://app.powerbi.com/view?r=..., sem porta/user/pass/fragment)
  → outcome final: "full" (Desktop+Service+Publish todos ok), "partial" (Desktop+Service ok, sem
    Publish configurado), "failed" (qualquer estágio obrigatório falhou)
```

Regra especial confirmada: para o relatório **"Real X Meta (Recomendações)"**, o Publish to Web é **obrigatório** (`publish_required`) — se não abrir, o resultado inteiro vira `failed` mesmo que Desktop+Service tenham funcionado.

Importante (documentado no próprio docstring de `browser.py`): `OPENED` significa apenas que uma URL canônica válida foi entregue a um executável Chrome validado sem erro de lançamento — **não** prova que a aba renderizou, que o relatório carregou, ou que o usuário está autenticado no Power BI Service. A prova real de sucesso pára no Desktop (via detecção de janela); Service/Publish são "melhor esforço" documentado.

Critérios de sucesso do E2E (conforme `verifier` de `powerbi_open.py`): `desktop_opened=True`, `browser_opened=True`, estágio `desktop` em `{opened, already_open}`, estágio `service` == `opened`, estágio `publish_to_web` em `{opened, not_configured}`.

**Estado: ✅ APPROVED** (handler+verifier reais, testes em `tests/powerbi/`). Nenhuma URL sensível de workspace/report real foi incluída aqui — o catálogo (`reports.json`) fica fora do repositório, em `%LOCALAPPDATA%`.

---

## 11. TASK SYSTEM

`app/tasks/manager.py::TaskManager` — único ponto de criação/transição/consulta de tarefas, com dois backends intercambiáveis (nunca os dois ao mesmo tempo: `__init__` exige exatamente um de `state_path` ou `task_repository`).

### Lifecycle

Estados públicos: `pending → running → {completed | failed | cancelled | timeout}`. Transições válidas (`VALID_TRANSITIONS`): de `pending` só para `{running, cancelled, failed}`; de `running` só para `{completed, failed, cancelled, timeout}` — qualquer outra transição levanta `TaskTransitionError`.

**Task ≠ AgentRun** (confirmado estruturalmente: nenhuma tabela/objeto liga uma Task genérica a uma tentativa de agente hoje, exceto o FK opcional `agent_id`/`agent_runs` no schema Postgres — ver §13). Uma Task é "o trabalho solicitado"; hoje ela é criada tanto por Actions (`ActionEngine.submit`) quanto pelo chat de agente (`AvailabilityObservedExecutor`, task type `"chat.provider"`).

Regras de recuperação confirmadas no código:
- **timeout legado** (modo arquivo) → `status="failed"`, mapeado de volta para o público como `"timeout"` quando reconstruído (`_record_to_public`); no schema Postgres, isso vira `TaskStatus.FAILED` + `failure_code="timeout"` (não existe status `timeout` nativo no banco — decisão documentada no próprio `app/db/models.py`).
- **`running` após restart** → no modo arquivo, `_load_and_reconcile()` marca como `failed` com erro `"Execution interrupted by application restart."`; no modo repository, `TaskManager.reconcile()` (chamado explicitamente no `startup` do FastAPI, nunca no `__init__`) faz o mesmo, com `failure_code="interrupted_by_restart"`.
- **`pending`** → permanece `pending` em ambos os modos (nunca é tocado pela reconciliação).
- **`interrupted`** (só existe no formato legado antigo) → migrado para `failed` na carga.

### Modo arquivo (legado) vs. modo repository (Postgres)

- **Arquivo (`state_path`):** `system/task-state.json` (571.989 bytes na última verificação — histórico real acumulado), escrita atômica (`temp + os.replace`), dict em memória (`self._tasks`) como cache/verdade em runtime.
- **Repository (`task_repository`):** delega tudo a `TaskRepository`/`PostgresTaskRepository` (ver §12); nenhum estado em memória além do necessário para jobs `asyncio` em execução.

`TaskManager.summary()` alimenta `GET /api/tasks/summary` (usado pelo card "Tasks" do HUD): `tasks` (ativas), `total`, `failed`, `executor` (idle/nome/"multi"), `last_task`, `active_tasks`.

`TaskManager.shutdown()` cancela toda Task `pending`/`running` no encerramento gracioso.

**Estado: ✅ APPROVED** (código+testes robustos), mas **rodando hoje em modo arquivo em produção** — ver §12 para a prova de que o cutover para Postgres ainda não ocorreu.

---

## 12. POSTGRESQL / PERSISTENCE

- **SQLAlchemy:** `app/db/models.py` — `Base(DeclarativeBase)`, `TaskRecord` (tabela `tasks`) e `AgentRunRecord` (tabela `agent_runs`), únicas duas entidades mapeadas nesta fase (docstring explícito: "escopo desta fase: somente Task e AgentRun").
- **Enums:** `TaskStatus`/`AgentRunStatus` mapeados com `SAEnum(..., native_enum=False)` — gera `VARCHAR` + `CHECK` constraint, não um `ENUM` nativo do Postgres (decisão documentada: evoluir um `CHECK` é uma migration comum; evoluir um `ENUM` nativo exige `ALTER TYPE ... ADD VALUE`, mais arriscado num schema jovem).
- **IDs:** `UUID` nativo do Postgres (`postgresql.UUID(as_uuid=True)`); compatível com o `task_id` legado (`uuid.uuid4().hex`, um UUID válido sem hífens).
- **`timeout`** não é um status persistente — vira `status=failed` + `failure_code="timeout"`.
- **Constraints confirmadas:** `UniqueConstraint(task_id, attempt_number)` e `UniqueConstraint(execution_key)` em `agent_runs` (impede duplicar tentativa ou reprocessar a mesma chave de execução); índices em `status`, `agent_id+status`, `created_at` nas duas tabelas.
- **Alembic:** `alembic/versions/0001_create_tasks_and_agent_runs.py` (cria as duas tabelas — escrita manualmente, sem `--autogenerate`, porque "nenhum banco de destino está configurado nesta fase") + `0002_add_status_check_constraints.py` + `0003` (`agent_runs.agent_id` passa a aceitar `NULL` — chat comum/AUTO sem persona associada cria `AgentRun` sem `agent_id`; downgrade documentado e testado no cenário limpo).
- **Repositories:** `app/db/repositories.py` (contratos/exceções: `TaskNotFoundError`, `DuplicateAttemptError`, `DuplicateExecutionKeyError`), `app/db/repositories_postgres.py` (`PostgresTaskRepository`, `PostgresAgentRunRepository` — implementação real via SQLAlchemy Session, com modo "independente" ou "participante" de uma transação externa via `app/db/uow.py::unit_of_work`), `app/db/repositories_memory.py` (fake em memória, para testes).
- **Importer:** `app/db/migrate_task_state.py` — migração controlada, idempotente e não-destrutiva de `system/task-state.json` para o schema novo.
- **Variáveis de ambiente:** `JARVIS_DATABASE_URL` (banco operacional) e `JARVIS_TEST_DATABASE_URL` (banco de teste, **isolado**, nunca o mesmo do operacional — os testes de integração Postgres fazem *skip* explícito sem ela).

### Estado real confirmado nesta auditoria (evidência, não suposição)

```
app/main.py: operational_database_url = get_setting("JARVIS_DATABASE_URL") if owns_task_manager else None
             elif operational_database_url: ... PostgresTaskRepository ...
             else: ... TaskManager(PROJECT_ROOT / "system" / "task-state.json", ...)  # legado
```

`.env` real do projeto **não contém `JARVIS_DATABASE_URL`** (nem vazio — a chave simplesmente não existe), só `JARVIS_TEST_DATABASE_URL`. Logo:

- **P2 código/testes:** ✅ **APPROVED** (models, repositories, migrations, unit-of-work implementados e testados isoladamente). **Revalidado localmente em 2026-09-07** contra PostgreSQL real de teste (`jarvis_test`, `localhost:5432`), incluindo a migration 0003 (`agent_runs.agent_id` nullable): `tests.db.test_models`, `test_repositories_memory`, `test_repositories_postgres`, `test_check_constraints`, `test_agent_run_agent_id_nullable_migration`, `test_migrate_task_state_postgres`, `test_task_manager_postgres_repository` — **61 testes, 0 failures, 0 errors, 0 skips**. Nenhum banco de produção foi acessado; nenhum cutover foi executado.
- **DECISÃO DE PRODUTO (2026-09-05, usuário, DEFINITIVA — não reabrir):** banco operacional = `jarvis`, host `127.0.0.1`, porta `5432`, role dedicada = `jarvis_app`. `jarvis_test`/`jarvis_test_user` seguem exclusivamente para teste (nunca elevar `jarvis_test_user` a `CREATEDB`). Nenhum banco de outro sistema (`servicesbi`, `sige_servicesbi`, `site-oficial`, `postgres`) pode ser usado como operacional.
- **P2 cutover operacional:** ⏳ **PENDENTE — ainda não executado, não por incapacidade do ambiente.** `EXECUTION_ENVIRONMENT_NO_LOCALHOST` foi o bloqueador real quando a única sessão disponível era Cowork (cloud, sem rota de rede até `127.0.0.1:5432`/`127.0.0.1:8000` — ver §31). **Isso deixou de ser o bloqueador atual em 2026-09-07**: uma sessão Claude Code local (Windows) confirmou empiricamente acesso a `127.0.0.1:5432` e executou 61 testes reais contra `jarvis_test` com 0 failures/0 errors/0 skips (ver §12 "P2 código/testes" acima). `.env` ainda não contém `JARVIS_DATABASE_URL`; o `TaskManager` real em produção **continua em modo arquivo** (`system/task-state.json`, 1052 tasks na última verificação). A automação completa do cutover já existe em `scripts/cutover-p2.ps1` (guard-railed, idempotente, implementa as 24 etapas documentadas em `JARVIS_HANDOFF.md`) — falta só ser **executada**, a partir de um worker com acesso local real (Codex Desktop ou Claude Code local; Cowork continua sem essa rota de rede — ver §31). Ver JARVIS_HANDOFF.md para o próximo passo exato.

Nenhuma senha/URL com credencial é reproduzida aqui.

---

## 13. AGENTRUN

Separação de conceito (documentada nos próprios comentários de `app/agents/execution.py` e no schema): **Task = o trabalho solicitado; AgentRun = uma tentativa de um agente/provider executar parte ou toda a Task.**

```
task
├── agent_run (attempt_number=1, execution_key único, agent_id, provider?, model_profile?, status)
├── agent_run (attempt_number=2, ...)
└── ...
```

Campos reais do modelo (`AgentRunRecord`, `app/db/models.py`): `id`, `task_id` (FK), `attempt_number`, `execution_key` (único), `agent_id`, `provider`, `model_profile`, `status` (`AgentRunStatus`), `input_text`, `context_json`, `operating_instructions_ref`, `output_text`, `structured_result_json`, `summary`, `error_text`, `failure_code`, `started_at`, `finished_at`, `created_at`, `updated_at`.

`PostgresAgentRunRepository` (§12) já implementa `create` (com `TaskNotFoundError` se a task pai não existir, e tratamento de `IntegrityError` para as duas `UniqueConstraint`), `get`, `list_for_task`, `get_by_execution_key`, `next_attempt_number` (usa `SELECT ... FOR UPDATE` na Task pai — só é realmente serializado contra escrita concorrente dentro da mesma transação), `update_status`.

### Estado real confirmado nesta auditoria

```bash
grep -rn "AgentRunRepository|PostgresAgentRunRepository|agent_run_repository" app/
# → só aparece dentro de app/db/ (models, repositories, repositories_postgres, repositories_memory)
```

**Nenhum ponto do fluxo de execução real** (`AgentExecutionService`, `AvailabilityObservedExecutor`, `TaskManager`, qualquer router de `app/api/`) instancia ou chama `AgentRunRepository`/`PostgresAgentRunRepository`. O objeto simplesmente não é usado fora da própria camada de dados.

- **Estrutura/repository:** ✅ **APPROVED** (implementados e presumivelmente testados isoladamente em `tests/db/`).
- **Integração real com o fluxo de execução:** ⏳ **P3 NOT STARTED** — confirmado por ausência total de wiring, não por suposição.

---

## 14. MEMORY SYSTEM

| Memória | Objetivo | Formato | Localização | Writer | Reader | Status |
|---|---|---|---|---|---|---|
| `system/JARVIS-HISTORY.json` | Histórico bruto de mensagens user/jarvis | JSON array `{role, content, ts}` | `system/` | `integrations/node/memory/memory-system.js` (histórico — **hoje não é chamado por nenhum processo ativo**) | `app/api/workspace.py::memory_status` (só existência/tamanho) | ⚫ LEGACY (dados de 2026-08-24/25; escritor não está wired no runtime atual) |
| `system/JARVIS-MEMORY.md` | Resumo textual arquivado do histórico | Markdown | `system/` | idem | idem | ⚫ LEGACY |
| `system/memory-embeddings.json` | Embeddings pré-calculados (563 KB) | JSON | `system/` | idem (não confirmado ativo) | `memory_status` (só existência) | ⚫ LEGACY |
| `system/mega-brain/index.json` | Índice do "Mega Brain" (187 KB) | JSON | `system/mega-brain/` | idem | `memory_status` | ⚫ LEGACY |
| `system/mega-brain/proofs.json` | Metadados de reindexação (`reindexedAt`, `indexedItems`, `reloadedByInstance`) | JSON | `system/mega-brain/` | idem | não exposto por API hoje | ⚫ LEGACY |
| `system/task-state.json` | Persistência **operacional real** do `TaskManager` em modo arquivo | JSON (`{version, tasks[]}`) | `system/` | `app/tasks/manager.py::TaskManager._persist` | `TaskManager` (leitura própria) | ✅ **APPROVED e ativo** — não é memória conversacional, é o backend de Task real hoje |
| Obsidian vault (`obsidian-template/` ou `OBSIDIAN_VAULT`) | Documentação/persona/conhecimento navegável | Markdown + wikilinks `[[...]]` | configurável | usuário/edição manual + `POST /api/obsidian/ingest` | `GET /api/obsidian/{stats,tree,graph,note}` | 🟡 parcial — só stats/tree/graph/note leitura+ingest simples; grafo é derivado 100% do vault (`_build_graph`), sem catálogo paralelo |
| `AgentRuntimeStateService` | Status runtime (`idle/working/waiting/error`) dos 8 agentes | dict em memória | processo Python | `AgentExecutionService`/`MorpheusOrchestrationService` | `GET /api/agents` | ✅ APPROVED, mas **não persiste** — reseta a cada restart |

**Importante:** `integrations/node/memory/memory-system.js` (`JarvisMemorySystem`) implementa toda a lógica de escrita/leitura desses arquivos (histórico, mega-brain, proofs, tokenização), mas **só é referenciado pelo próprio teste** (`tests/memory/memory-system.test.js`) — nenhum script de produção o importa ou executa hoje. Os dados existentes em `system/*.json` são um **snapshot congelado de 2026-08-24/25**, não uma memória viva sendo atualizada pelo runtime atual.

**Nada foi migrado para PostgreSQL** — nem histórico conversacional, nem embeddings, nem mega-brain. O único dado "memória" que já é Postgres-*ready* (mas não cutover) é o `TaskManager`/`AgentRun` (§12).

Separação clara: **Task memory** (`system/task-state.json`, ativo) ≠ **AgentRun memory** (schema existe, zero dado real, §13) ≠ **Cérebro 1/histórico conversacional** (`JARVIS-HISTORY.json`/`JARVIS-MEMORY.md`, congelado) ≠ **Mega Brain** (`mega-brain/*.json`, congelado) ≠ **Obsidian** (vivo, mas é documentação/persona, não memória de conversa) ≠ **runtime in-memory state** (`AgentRuntimeStateService`, não persiste).

---

## 15. VOICE SYSTEM

- **Captura:** MIC no cockpit (frontend) → WebRTC Realtime (`POST /api/realtime/session` cria a sessão efêmera via `OpenAIGateway.create_realtime_session`, modelo `OPENAI_REALTIME_MODEL` default `gpt-realtime-2.1`).
- **Transcrição (STT):** `POST /api/stt` — multipart, mínimo 2000 bytes de áudio, tenta inglês primeiro e refaz em português se detectar alucinação (`_is_hallucination`: texto curto demais, padrões conhecidos como "obrigado por assistir", ou repetição excessiva de palavras).
- **Síntese (TTS):** `POST /api/tts` — vozes válidas `{alloy, ash, coral, echo, fable, nova, onyx, sage, shimmer}`, default `nova` (BR) / `onyx` (outros idiomas).
- **Realtime:** vozes específicas para Realtime (`REALTIME_VOICES`, conjunto maior, incluindo `marin`/`cedar`), idiomas `{BR, ES, EN}`.
- **Roteamento de comando de voz:** `POST /api/voice-command-router` — primeiro tenta `ActionDispatcher.resolve` (comando determinístico vira `ActionRequest`/Task real); senão cai no "fast path" (`_fast_command`, ~15 famílias de comando: saudação, status, hora, abrir site conhecido, Spotify/YouTube por busca, mapas, pesquisa Google, timer, volume, abrir programa/pasta local) — comandos que mencionam tela/planilha são explicitamente desviados para o chat completo (`SCREEN_PATTERN`/`SHEET_PATTERN` → `{"handled": False, "reason": "chat_required"}`).
- **Visão:** `POST /api/analyze-screen[-fast]` — envia uma imagem (`image_url`) + pergunta para o gateway OpenAI (`gpt-4o-mini` via `complete()`).
- **Tradução:** `POST /api/translate`.
- **Cowork:** `POST /api/cowork/{start,stop}` + `GET /api/cowork/status` — flag simples em `app.state.cowork_active`.

Estados de voz desejados (MUTE/OUVINDO/PROCESSANDO/FALANDO) são geridos no **frontend** (máquina de estados JS, cobertos por `tests/test_fastapi_frontend_parity.py::test_voice_state_machine_uses_only_official_states_and_starts_muted` e testes irmãos) — o backend não tem conceito de "estado de voz", só endpoints request/response e a sessão Realtime.

**Estado: ✅ APPROVED** para os fluxos acima (com testes de frontend parity e endpoints). Nenhum problema conhecido pendente registrado nesta auditoria para Voice em si.

---

## 16. OPENAI API BALANCE

### Arquitetura atual (operacional)

```
OpenAICostsLedgerService (app/core/openai_costs_ledger.py)
  → GET https://api.openai.com/v1/organization/costs  (Bearer OPENAI_ADMIN_KEY; paginado via has_more/next_page)
  → soma em Decimal os custos desde baseline_at
  → calculated_balance_usd = baseline_balance_usd - custos_desde_baseline
  → system/openai-balance-ledger.json  (baseline_balance_usd, baseline_at, last_cost_sync_at,
                                          calculated_balance_usd, source, stale, error)
  → GET /api/openai-balance  (app/api/compatibility.py — lê application.state.openai_costs_ledger_service)
  → frontend (public/script.js::updateOpenAIBalance — só consulta o backend, nunca chama OpenAI direto)
```

- `source` confirmado: `"official_costs_ledger"`.
- Baseline é **dado operacional**, não constante de código — persistida em `system/openai-balance-ledger.json` (autoridade em runtime; `.env` só semeia na primeira vez, se o JSON ainda não existir).
- Erros explícitos, nunca mascarados como saldo zero: `BALANCE_BASELINE_REQUIRED` (sem baseline), `BALANCE_ADMIN_KEY_REQUIRED` (sem `OPENAI_ADMIN_KEY`), `COSTS_API_UNAUTHORIZED`/`COSTS_API_UNAVAILABLE`/`COSTS_API_ERROR` (falha da API — preserva o último valor conhecido como `stale=true`).
- `OPENAI_ADMIN_KEY` é usada só pelo backend, nunca exposta ao frontend; nenhum valor é registrado neste documento.

### Caminhos legados (não operacionais)

- **Puppeteer/scraping de `platform.openai.com/home`** (`app/core/openai_balance.py::collect_openai_balance`, `scripts/openai-balance-read.js`, `integrations/node/openai-balance-browser.module.js`): ⚫ **LEGACY / NOT OPERATIONAL PATH**. `OpenAIBalanceService` (a classe que sabia rodar isso) continua existindo, mas hoje é instanciada **sem collector** em `app/main.py` — nunca dispara Puppeteer sozinha. Bloqueado independentemente por Cloudflare (`cf-mitigated: challenge`) contra navegação headless, mesmo com sessão previamente autenticada — decisão consciente de abandonar esse caminho, não uma falha a corrigir.
- **Extensão Chrome `integrations/chrome/openai-balance-bridge`**: ⚫ **LEGACY / PASSIVE / NOT REQUIRED**. Suas rotas de ingest/heartbeat (`POST /api/openai-balance/ingest`, `/heartbeat`, `GET /bridge-status`) continuam existindo e funcionais, mas escrevem só no `OpenAIBalanceService` legado, que **não alimenta** `GET /api/openai-balance` (esse endpoint lê exclusivamente `OpenAICostsLedgerService`). A extensão não precisa estar instalada para o saldo funcionar.

### Correção feita nesta linha de trabalho (auto-open)

Causa raiz comprovada (evidência: leitura de código + telemetria do próprio Chrome, `serviceworkerevents: ["alarms.onAlarm","runtime.onInstalled","runtime.onStartup"]`, + reprodução ao vivo durante o teste, disparo às 18:50:19 e novamente às 18:55:20, exatos 5min01s depois): `integrations/chrome/openai-balance-bridge/background.js` tinha uma função `ensureHomeTab()` chamada em `onInstalled`, `onStartup`, e um alarme `jarvis-balance-sync` a cada 5 minutos, que recriava a aba `https://platform.openai.com/home` sempre que nenhuma existisse — **totalmente independente do processo Python**, rodando dentro do Chrome do usuário mesmo com o Jarvis parado.

**Correção aplicada:** removidos `ensureHomeTab()`, os três listeners (`onInstalled`/`onStartup`/`onAlarm`) e a criação do alarme; `manifest.json` não pede mais as permissões `alarms`/`tabs`. A extensão agora só reage passivamente a mensagens de um content script já rodando numa aba que o usuário abriu manualmente.

**Estado: ✅ APPROVED (validado em 2026-09-05T19:53Z).** Confirmado que a extensão foi recarregada no Chrome real do usuário: o próprio `Secure Preferences` do perfil `Default` mostra `service_worker_registration_info.version: "1.0.2"` (o manifest corrigido) e `last_update_time` correspondente a `2026-09-05T19:00:35Z`. Desde esse reload até a verificação (**53+ minutos**, acima dos 5 minutos exigidos), `serviceworkerevents` está **vazio** (`[]`) — nenhum disparo de `alarms.onAlarm`/`runtime.onInstalled`/`runtime.onStartup` ocorreu, e `active_permissions.api` está vazio (as permissões `alarms`/`tabs` não estão mais em uso, embora Chrome mantenha o histórico em `granted_permissions`). `GET /api/openai-balance/bridge-status` no processo real também confirma zero atividade da extensão (`extension_seen: false`) enquanto `GET /api/openai-balance` segue saudável (`source: official_costs_ledger`, `balance_usd: 4.06`). Evidência obtida sem abrir Chrome/Puppeteer — só leitura do arquivo de preferências do próprio navegador e chamadas HTTP ao backend real.

---

## 17. HEALTH AND DIAGNOSTICS

| Endpoint | Finalidade | Fonte/autoridade | Cache |
|---|---|---|---|
| `GET /api/health` | Contrato de saúde "PASSO 0A" (server/openai/claude/chrome/pools) + `capabilities` | `openai_gateway.configured`, `ProviderAvailabilityService.get_state("claude")` | nenhum (calculado por request) |
| `GET /api/providers/health` | Saúde autoritativa de Codex/Claude + modo do executor, sem executar chat/modelo | `ProviderAvailabilityService.refresh()` + `ExecutorService.get_mode()` | `refresh()` só reavalia probes registrados, nunca dispara execução real |
| `GET /api/providers`, `GET /api/providers/{id}` | Catálogo estático combinado com disponibilidade operacional canônica | `ProviderManager` (definição/metadata) + `ProviderAvailabilityService.get_state()` (estado operacional) | nenhum; leitura direta por request |
| `GET /api/executor/profiles` | Catálogo MAX/PRO/FAST por provider + status propagado do provider pai | `ModelRegistry.catalog()` + `ProviderAvailabilityService.get_state()` | nenhum |
| `GET /api/executor/mode` / `POST .../mode` | Ler/setar `execution_mode` (auto/claude/codex) | `ExecutorService` | em memória |

O status global de `GET /api/health` representa a saúde do núcleo servidor e permanece `ok` quando componentes opcionais estão indisponíveis. `components.server.status == "ok"` continua sendo o contrato de identidade do backend Jarvis; OpenAI e Claude mantêm seus estados diagnósticos, e Chrome é informado como opcional e `not_checked`, sem erro sintético.

**Decisão confirmada no código:** `ProviderAvailabilityService` é a fonte única para `installed`, `authenticated`/`connected`, `operational`, `eligible`, `entitled`, `reason` — usada por `/api/providers`, `/api/providers/{id}`, `/api/health`, `/api/providers/health` e `/api/executor/profiles` (todas leem do mesmo `request.app.state.provider_availability`). `ExecutorService` é autoridade só para `execution_mode`/`active_profile`; `ProviderManager` fornece somente definição/metadata ao catálogo. **Nenhuma fonte paralela de health é usada por essas rotas** — confirma a ADR-003.

---

## 18. CLAUDE HEALTH / MODEL INDICATORS

### Semântica formal de disponibilidade (definida em 2026-09-05, Etapa 2)

| Estado | Condição (`ProviderAvailability`/`_provider_status`) | Dot AI MODELS | Dot/texto EXECUTOR (só do provider selecionado) |
|---|---|---|---|
| **ONLINE** | `status == "online"` (installed+authenticated+operational) | `active` (verde) | `ONLINE` (verde) |
| **CHECKING / UNKNOWN** | `reason == "capability_not_validated"` (instalado+autenticado+entitled, nunca executado com sucesso) → `status == "unknown"` | `idle` (neutro) | `CHECK` (neutro) |
| **OFFLINE** | `status` ∈ `{offline, not_authenticated, entitlement_unavailable}` ou qualquer outro erro | `error` (vermelho) | `OFF`/`AUTH`/`PLAN`/`ERROR` (vermelho) |
| **RATE_LIMITED** | ⏳ ainda não modelado — escopo da Etapa 6 (handoff automático de provider); hoje uma falha de rate limit cai em `execution_failed`/`timeout` genérico via `record_failure` | — | — |

**Executor selecionado (`execution_mode`) é ortogonal à disponibilidade real de um provider — confirmado empiricamente, não só por leitura de código.** Teste ao vivo nesta sessão, contra o processo real do Jarvis: (1) Claude comprovado operacional via execução real (`record_success`); (2) executor trocado para CODEX; (3) `GET /api/executor/profiles` continuou mostrando Claude com `status="online"`, `availability=true`, `reason="operational"` para os 3 profiles (MAX/PRO/FAST) — o painel AI MODELS **não** "desliga" Claude visualmente só porque outro executor está selecionado. Repetido também para `AUTO` (ambos `codex`/`claude` `online`) e para `CLAUDE` selecionado (dot `ONLINE`, coerente com `providers/health`). Regressão travada em `tests/test_fastapi_executors.py::test_ai_models_panel_reflects_proven_claude_even_when_codex_is_selected`.

**Conclusão da Etapa 2:** nenhum bug foi encontrado na separação `AI MODELS` (disponibilidade real, por provider) vs. `EXECUTOR` (o que rodaria agora, por `execution_mode`) — a arquitetura já satisfazia o requisito antes desta investigação. O que existia (e permanece, ver seção abaixo) era a semântica textual `READY→CHECK`, já corrigida em sessão anterior. Nenhuma alteração de código foi necessária nesta etapa; só testes de regressão foram adicionados para travar o comportamento correto.

### Histórico (correção já aprovada em sessão anterior)

> **Nota de hierarquia de evidência:** as instruções originais desta tarefa de documentação assumiam este item como ainda não resolvido. Uma sessão de trabalho **anterior, dentro desta mesma conversa**, investigou, corrigiu e validou este ponto com E2E real e aprovação explícita do usuário. Por comportamento/runtime comprovado ter precedência sobre o texto do prompt, este documento registra o estado **real e mais recente**, não a suposição do template.

### Causa raiz (confirmada, não hipótese)

Claude é registrado com `authentication_implies_operational=False` (`app/main.py`) — diferente de Codex (`True`) — porque `claude auth status --json` só confirma login local, não capacidade real de execução. Por isso, `operational` fica `False` e `reason="capability_not_validated"` até uma execução real bem-sucedida chamar `ProviderAvailabilityService.record_success("claude")`. Isso é comportamento **intencional**, não um bug a remover.

### O bug real (corrigido)

`public/executor-status.js::formatProviderStatus` mostrava o texto **`READY`** para esse estado (`reason == "capability_not_validated"`), junto de um dot **neutro** (não verde) — uma contradição semântica: o texto afirmava "pronto" enquanto o indicador visual dizia "ainda não confirmado". Corrigido para mostrar **`CHECK`** (mesmo tom neutro, sem inventar verde) nesse estado; só vira `ONLINE`/verde quando `status == "online"` de fato.

### Validação E2E real (evidência)

Antes de qualquer execução: `{"operational": false, "eligible": false, "reason": "capability_not_validated"}` → frontend mostra `CHECK`/dot neutro. Depois de uma execução real e bounded pelo Claude (mensagem "Responda apenas com a palavra OK", resposta recebida "OK"): `{"operational": true, "eligible": true, "reason": "operational", "status": "online"}` → frontend mostra `ONLINE`/dot verde. Transição comprovada programaticamente com `ExecutorStatus.formatProviderStatus`.

**Estado: ✅ APPROVED** — semântica corrigida (texto nunca mais contradiz o dot), fonte única de verdade preservada (nenhum verde hardcoded), E2E real comprovou a transição `CHECK → ONLINE`, aprovado explicitamente pelo usuário ("CLAUDE HEALTH UI = APROVADO"). **Instrução vigente: não alterar mais este fluxo** sem pedido explícito.

---

## 19. API / ENDPOINT CATALOG

| METHOD | PATH | PURPOSE | SOURCE OF TRUTH | STATUS |
|---|---|---|---|---|
| POST | `/api/chat` | Chat/streaming principal (roteia para action, elaboração de conteúdo, ou executor de provider) | `app/api/chat.py` | ✅ |
| GET/POST | `/api/executor/mode` | Ler/definir executor (auto/claude/codex); OpenAI é rejeitado antes da execução | `ExecutorService` | ✅ |
| GET/POST | `/api/executor/profiles` | Catálogo de modelos MAX/PRO/FAST + status | `ModelRegistry` + `ProviderAvailabilityService` | ✅ |
| GET | `/api/health` | Health legado/HUD | `ProviderAvailabilityService`, `OpenAIGateway` | ✅ |
| GET | `/api/providers/health` | Health autoritativo Codex/Claude | `ProviderAvailabilityService` | ✅ |
| GET | `/api/providers`, `/api/providers/{id}` | Catálogo read-only combinado com estado operacional canônico | `ProviderManager` (metadata) + `ProviderAvailabilityService` (disponibilidade) | ✅ |
| GET | `/api/agents` | Catálogo canônico de agentes + status runtime | `AgentRegistry` + `AgentRuntimeStateService` | ✅ |
| POST | `/api/agents/{id}/run` | Executar 1 dos 7 especialistas | `AgentExecutionService` | ✅ |
| POST | `/api/agents/morpheus/plan` | Orquestração sequencial MORPHEUS | `MorpheusOrchestrationService` | ✅ |
| GET | `/api/tasks`, `/api/tasks/summary`, `/api/tasks/{id}` | Consulta de Tasks | `TaskManager` | ✅ |
| POST | `/api/tasks/{id}/cancel` | Cancelar Task | `TaskManager` | ✅ |
| POST | `/api/tasks` | Criar Task `excel.create` via API direta | `ActionEngine` | ✅ |
| GET | `/api/openai-balance` (+ alias `/api/agenda/balance`) | Saldo OpenAI atual | `OpenAICostsLedgerService` | 🟡 (ver §16) |
| POST | `/api/openai-balance/ingest`, `/heartbeat`; GET `/bridge-status` | Bridge legado (Chrome extension) | `OpenAIBalanceService` (legado) | ⚫ |
| GET/POST | `/api/claude-auth/*`, `/api/codex-auth/*` (`status`/`connect`/`disconnect`) | Autenticação oficial dos CLIs | `ClaudeAuthService`/`CodexAuthService` | ✅ |
| POST | `/api/realtime/session`, `/api/stt`, `/api/tts`, `/api/translate`, `/api/voice-command-router`, `/api/analyze-screen[-fast]` | Voz/visão | `OpenAIGateway` | ✅ |
| POST/GET | `/api/cowork/*` | Flag de sessão cowork | `app.state.cowork_active` | ✅ |
| GET | `/api/files`, `/api/files/download`, `/api/files/view` | Deliverables em `Documents and Projects/` | `app/api/workspace.py` | ✅ |
| POST | `/api/attach` | Upload de anexo de chat | idem | ✅ |
| GET/POST | `/api/obsidian/*` | Stats/tree/graph/note/ingest do vault | idem | ✅ (leitura); 🟡 (ingest simples) |
| GET | `/api/memory/status` | Status agregado das 3 camadas de memória | idem | ✅ (só relata existência/tamanho, ver §14) |
| POST | `/api/jarvis/shutdown` | Encerramento gracioso do processo | `app/main.py` | ✅ |
| GET | `/api/stats`, `/api/system-stats`, `/api/notifications` | Diagnóstico/telemetria local | `app/api/diagnostics.py`, `notifications.py` | ✅ |
| GET/POST | `/api/automation/*` (read-file, find-file, excel-live, screenshot, clipboard, computer-use, browser-control, workflow, pdf) | Automação de desktop diversa | `app/api/automation.py` | 🟡 CORRIGIDO em 2026-09-05 (§22/§25): shell arbitrário (`action_shell`) e JS arbitrário (`execute_js`) **removidos** (RED/GREEN, ver §21); `workflow`/`computer-use/task` agora com allowlist de `type`; `browser-control`/`navigate` agora via `is_allowed_navigation_url()` (só `http`/`https`). Ainda sem autenticação em nenhuma rota (mitigado só por bind `127.0.0.1`+CORS, §22); `read-file`/`find-file` ainda usam `Path.home()` inteiro como raiz (risco menor, só leitura — fora do escopo aprovado nesta sessão). |

---

## 20. CONFIGURATION AND ENVIRONMENT

| Variável | Finalidade | Obrigatória? | Consumidor | Secreto? |
|---|---|---|---|---|
| `HOST`, `PORT` | Bind local do backend; ambiente → `.env` → defaults `127.0.0.1:8000`, com validação de loopback e faixa da porta | não | `app/core/config.py` | não |
| `OPENAI_API_KEY` | Voz/visão/TTS/STT (OpenAI API tradicional) | sim, para voz | `OpenAIGateway` | **sim** |
| `OPENAI_REALTIME_MODEL` | Modelo do Realtime | não (default `gpt-realtime-2.1`) | `voice.py` | não |
| `CLAUDE_CLI_PATH` / `JARVIS_CLAUDE_CMD` | Caminho do CLI Claude | não | `ExecutorService.get_command` | não |
| `CLAUDE_PLAN` | (reservada, não lida hoje no código auditado) | — | — | não |
| `JARVIS_CODEX_CMD` | Caminho do CLI Codex | não | `ExecutorService.get_command` | não |
| `CODEX_HOME` | Diretório de config do Codex CLI | não (default `~/.codex`) | `codex_subprocess_environment` | não |
| `JARVIS_EXECUTOR_MODE` | Modo inicial do executor | não (default `auto`) | `ExecutorService._initial_mode` | não |
| `JARVIS_WORKSPACE_ROOT` | Raiz do workspace de arquivos | não (default `D:\Jarvis`) | `app/core/config.py` | não |
| `OBSIDIAN_VAULT` | Caminho do vault Obsidian | não (default `obsidian-template/`) | `workspace.py::_vault` | não |
| `OPENAI_ADMIN_KEY` | Autenticação na Organization Costs API | **sim**, para saldo | `OpenAICostsLedgerService` | **sim** |
| `OPENAI_CREDIT_BASE_USD` / `OPENAI_CREDIT_BASE_AT` | Seed inicial da baseline do ledger (só usada se o JSON ainda não existir) | não, após 1º boot | `BalanceLedgerStore._seed_from_environment` | não (valor monetário, não credencial) |
| `OPENAI_BALANCE_REFRESH_MS` | Intervalo de refresh do saldo | não (default 300000 = 5min) | `OpenAICostsLedgerService` | não |
| `JARVIS_DATABASE_URL` | Ativa o cutover para Postgres (Task/AgentRun) | não — **ausente hoje** | `app/main.py` | **sim** (contém credencial) |
| `JARVIS_TEST_DATABASE_URL` | Banco isolado só para testes de integração | não | suíte de testes | **sim** |
| `JARVIS_UPDATE_GITHUB_TOKEN` | (reservada, update automático) | não | não confirmado nesta auditoria | **sim** |

Nenhum valor de variável secreta foi impresso ou registrado neste documento.

---

## 21. TESTING STRATEGY

- **Python (`pytest`/`unittest`):** 62 arquivos `tests/test_*.py` no nível superior, mais subpastas `tests/{actions,connections,db,launcher,memory,openai-balance,powerbi,ui,voice}`. Rodados via `.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"`.
- **Node (`node --test`):** 9 arquivos `*.test.js` (parser de saldo, bridge, executor-status, memory-system, connections).
- **Integração PostgreSQL:** faz *skip* explícito sem `JARVIS_TEST_DATABASE_URL` configurada — nunca roda contra o banco operacional.
- **E2E:** cobertos caso a caso (Power BI via detecção real de janela/processo; saldo via chamada real à Costs API; Claude health via execução real bounded) — não há um framework de E2E único.
- **Validação manual real:** exigida explicitamente para qualquer alegação de comportamento **visual/operacional** (ex.: dot verde, saldo exibido, aba de navegador) — testes unitários que só validam a lógica isolada **não bastam** para marcar esse tipo de item como `APPROVED`.

**Regra vigente (confirmada em uso nesta própria conversa):** teste unitário sozinho não basta para aprovar comportamento visual/operacional quando existe E2E real necessário — a autoridade final é o comportamento observado pelo usuário, não a suíte de testes.

### Execução isolada confirmada (2026-09-05, ambiente Cowork — venv Linux descartável, NÃO o `.venv` real do projeto)

`pip install -r requirements.txt` (já corrigido, ver §25/§28) + `python -m unittest discover -s tests -p "test_*.py"`: **742 testes, 736 passaram**, 4 erros e 2 falhas — todos explicados por diferença de ambiente, não regressão de código:
- 4 erros (`db.test_check_constraints`, `db.test_migrate_task_state_postgres`, `db.test_repositories_postgres`, `db.test_task_manager_postgres_repository`): `setUpClass` tenta conectar em `JARVIS_TEST_DATABASE_URL` (`127.0.0.1:5432`) — inalcançável a partir do ambiente Cowork (ver §31). Não são falhas de teste, são a integração Postgres fazendo exatamente o que deveria (tentar conectar) num ambiente sem rede até o banco.
- 2 falhas (`test_environment_override_routes_extensions_and_restores_official_root`, `test_environment_override_rejects_an_entire_drive_root`): ambas dependem de `Path(r"D:\Jarvis")` se comportar como caminho Windows (drive `D:`, `.anchor == "D:\\"`) — confirmado por leitura de `app/core/config.py::_workspace_root()` que isso é *esperado* falhar num Linux/POSIX (onde `\` não é separador de path, `.anchor` fica vazio) e **passaria normalmente no Windows real**, onde o Jarvis de fato roda. Não é uma regressão.

`node --test tests/**/*.test.js`: **54 testes, 52 passaram**, 2 falhas — ambas por `Could not find Chrome` (Puppeteer sem binário do Chrome instalado nesta VM Linux descartável), não por lógica de código.

**Conclusão:** nenhuma regressão real encontrada nesta rodada de testes isolados — a base de código está saudável frente à própria suíte de testes existente.

---

## 22. SECURITY AND SAFETY

- **`ActionPolicy`/`ActionRegistry`:** nenhuma ação com `"shell"` no nome pode ser registrada ou resolvida (bloqueio estrutural, não convenção); toda ação exige `input_model` Pydantic (`extra="forbid"` na maioria); confirmação explícita via `confirmation_required`/`ConfirmationRequiredError` quando aplicável.
- **`PathPolicy`:** todo acesso a arquivo (leitura ou escrita) é validado contra raízes explícitas e resolvidas — nunca um caminho arbitrário do usuário é usado diretamente.
- **Sanitização de persistência:** `ActionPolicy._sanitize` redige `token`, `secret`, `credential`, `password`, `api_key`, `clipboard`, `prompt` antes de qualquer resultado de action ser persistido.
- **Resolução de executáveis:** app abertos (Word/Excel/PowerBI/VSCode/Chrome) são sempre resolvidos por caminho + nome exato + extensão `.exe` + pertencimento a uma raiz confiável (Registro do Windows ou Program Files) — nunca só por `PATH`/nome.
- **Credenciais:** nenhum serviço deste projeto manipula segredo de Claude/Codex diretamente — só chama os comandos oficiais `auth status/login/logout` dos próprios CLIs.
- **Banco de dados:** credenciais só via variável de ambiente (`JARVIS_DATABASE_URL`/`JARVIS_TEST_DATABASE_URL`), nunca hardcoded; teste e produção são explicitamente bancos diferentes.
- **DECISÃO ARQUITETURAL DE SEGURANÇA (2026-09-05, usuário, APPROVED após correção + testes — não reabrir sem pedido explícito):**
  ```
  ARBITRARY SHELL VIA API        = FORBIDDEN
  ARBITRARY JAVASCRIPT VIA API   = FORBIDDEN
  BROWSER AUTOMATION             = ALLOWED THROUGH BOUNDED OPERATIONS
  ACTION ENGINE / ACTION POLICY  = caminho de execução autoritativo preferido
  ```
  "Localhost only" (`app/core/config.py::HOST = "127.0.0.1"`) reduz a superfície de exposição de rede (um site remoto não consegue disparar essas rotas via `fetch()` do navegador — requisição JSON é preflighted e CORS bloqueia, ver `LOCAL_ORIGINS`), **mas nunca foi e não é justificativa para aceitar shell/JS arbitrário como capability** — qualquer outro processo/script rodando na mesma máquina podia (antes da correção abaixo) chamar essas rotas livremente, sem autenticação alguma (nenhum `Depends`/middleware de auth existe em `app/main.py`).
- **Browser automation — corrigido em 2026-09-05:** `POST /api/browser-control` (`system/browser-control.py`) tinha `execute_js` (`Runtime.evaluate` sobre qualquer `code` do payload) — **removida** (função `cmd_execute_js` e entrada em `COMMANDS` deletadas, não só desativadas). `navigate` agora passa por `is_allowed_navigation_url()` (única policy de URL de navegação do projeto — não duplicar): só `http`/`https` absolutos com host; `javascript:`, `file:`, `data:`, `vbscript:`, esquema desconhecido ou URL sem esquema são bloqueados **antes** de qualquer chamada CDP (provado por teste com `cdp_send` mockado, ver §21/§25). Operações bounded preservadas sem alteração: `connect`, `list_tabs`, `navigate` (com policy), `get_dom`, `click`, `fill`, `get_text`, `wait_for`, `screenshot` — todas já usavam `Runtime.evaluate` só com strings escapadas via `json.dumps` (nunca código livre), então não precisavam de mudança. A abertura de Power BI Service/Publish to Web continua sendo um fluxo determinístico separado e validado (§10), não afetado por nada disso.
- **Shell execution — corrigido em 2026-09-05:** `system/ui-automation.py::action_shell` (`subprocess.Popen(cmd, shell=True)` com o comando vindo direto do payload JSON, reachable via `POST /api/workflow` e `POST /api/computer-use/task`/`/v2`) foi **removida inteiramente** (função deletada, não só desregistrada de `HANDLERS`). Nenhuma outra chamada `subprocess.*(shell=True)` existe no arquivo (confirmado por análise estática do AST, não grep superficial — ver teste `test_no_subprocess_call_uses_shell_true` em §21). Defesa em profundidade adicionada em `app/api/automation.py`: `_validate_workflow_actions()`/`_validate_browser_control_cmd()` allowlist quais nomes de action/cmd podem sequer chegar aos scripts (400 imediato para qualquer coisa fora da lista, incluindo `"shell"`, `"powershell"`, ou `execute_js`) — isso é checagem de NOMES permitidos, não uma segunda policy de conteúdo de URL paralela à de `browser-control.py`. Todas as demais 14 ações bounded de `ui-automation.py` (`app_focus/close/minimize/maximize`, `key`, `type`, `click`, `scroll`, `wait`/`wait_for`, `screenshot`, `uia_click/set_value/get_text/tree`) foram preservadas sem alteração — nenhuma delas executa comando textual livre.
  - **Metodologia (RED→GREEN, ver §21):** `tests/test_automation_security.py` foi escrito e rodado ANTES da correção (12 falhas + 27 erros, exatamente nas vulnerabilidades acima) e DEPOIS (34/34 passando), além de confirmar zero regressão na suíte completa (742→776 testes, mesmos 2 falhas/4 erros de sempre, todos explicados por ambiente — ver §21).
- **Desktop actions:** sempre com `verifier` que comprova o efeito real (processo detectado, arquivo existente com tamanho/conteúdo esperado, janela visível) — o handler nunca é aceito sozinho como prova de sucesso.

---

## 23. ARCHITECTURAL DECISIONS

| ADR | Decisão | Status frente ao código atual |
|---|---|---|
| ADR-001 | Task ≠ AgentRun | ✅ confirmado — schema e comentários de código são explícitos; ver §11/§13 |
| ADR-002 | Claude/Codex são providers, não agents | ✅ confirmado — agentes executam sobre o `ChatService`/executor configurado, sem motor próprio; ver §6 |
| ADR-003 | `ProviderAvailabilityService` é authority de provider health | ✅ confirmado — única fonte operacional lida por `/api/providers`, `/api/providers/{id}`, `/api/health`, `/api/providers/health`, `/api/executor/profiles` |
| ADR-004 | AUTO prioriza Codex → Claude | ✅ confirmado — `AUTO_PROVIDER_PRIORITY = ("codex", "claude")` |
| ADR-005 | OpenAI API tradicional não participa do AUTO nem é modo manual de chat | ✅ confirmado — `VALID_EXECUTOR_MODES = ("auto", "claude", "codex")`; OpenAI permanece disponível apenas para capacidades complementares |
| ADR-006 | Task persistence target = PostgreSQL | 🟡 código pronto, cutover **pendente** (§12) |
| ADR-007 | OpenAI Balance operacional = Costs API + ledger local | ✅ confirmado e em produção (§16) |
| ADR-008 | Puppeteer não participa do caminho operacional do balance | ✅ confirmado — `OpenAIBalanceService` roda hoje sem collector |
| ADR-009 | Chrome Bridge não é dependência do balance | ✅ confirmado — rotas isoladas, não alimentam `/api/openai-balance` |
| ADR-010 | Agentes especializados devem reutilizar arquitetura agent/provider, não criar executores paralelos | ⏳ ainda não testado na prática (nenhum agente de domínio novo foi implementado); registrado como restrição de desenho para §7 |

---

## 24. IMPLEMENTED FEATURES

| FEATURE | STATUS | MAIN COMPONENT | LAST VERIFIED | NOTES |
|---|---|---|---|---|
| Chat multi-provider (auto/claude/codex) | ✅ APPROVED | `app/chat/*` | 2026-09-07 | OpenAI API permanece complementar, fora dos modos de chat |
| 8 agentes especialistas + execução individual | ✅ APPROVED | `app/agents/{registry,execution,runtime}.py` | 2026-09-05 | |
| Orquestração sequencial MORPHEUS (Fase 5A) | ✅ APPROVED | `app/agents/orchestration.py` | 2026-09-05 | só etapas analysis/auto-aprovadas; para no 1º gate |
| Action Engine + 6 capabilities (app.open/file.*/word.create/excel.create/powerbi.open) | ✅ APPROVED | `app/actions/*` | 2026-09-05 | todas com verifier obrigatório |
| Power BI E2E (Desktop→Service→Publish) | ✅ APPROVED | `app/powerbi/*`, `app/actions/powerbi_open.py` | 2026-09-05 | |
| Task lifecycle (arquivo) | ✅ APPROVED | `app/tasks/manager.py` | 2026-09-05 | em produção, modo arquivo |
| Task/AgentRun schema Postgres | ✅ APPROVED (código/testes) | `app/db/*`, `alembic/` | 2026-09-05 | não cutover |
| P2 cutover operacional (Postgres em produção) | ⏳ PENDING (decisão APPROVED, automação pronta) | `app/main.py`, `scripts/cutover-p2.ps1` | 2026-09-07 | decisão de banco/role ENCERRADA (jarvis/jarvis_app); `EXECUTION_ENVIRONMENT_NO_LOCALHOST` não é mais o bloqueador atual (Claude Code local confirmou acesso a `127.0.0.1:5432` em 2026-09-07) — falta só ser executado |
| AgentRun integrado ao fluxo real (P3) | ⏳ NOT STARTED | — | 2026-09-05 | zero wiring fora de `app/db/` |
| Voice (Realtime/STT/TTS/comando rápido) | ✅ APPROVED | `app/api/voice.py` | 2026-09-05 | |
| OpenAI Balance via Costs API + ledger | ✅ APPROVED | `app/core/openai_costs_ledger.py` | 2026-09-05 | |
| OpenAI Balance auto-open fix (extensão Chrome) | ✅ APPROVED | `integrations/chrome/openai-balance-bridge/background.js` | 2026-09-05 | validado via telemetria do próprio Chrome, 53+ min sem disparo |
| Claude health CHECK/ONLINE semantics | ✅ APPROVED | `public/executor-status.js` | 2026-09-05 | E2E real validado nesta conversa |
| AI MODELS independente de execution_mode selecionado | ✅ APPROVED | `app/api/executors.py`, `app/executors/availability.py` | 2026-09-05 | investigado e confirmado por evidência real (Etapa 2); nenhum código mudou, só regressão travada |
| Puppeteer scraping de saldo | ⚫ LEGACY | `app/core/openai_balance.py` | 2026-09-05 | bloqueado por Cloudflare; abandonado por decisão |
| Chrome Balance Bridge (extensão) | ⚫ LEGACY / PASSIVE | `integrations/chrome/openai-balance-bridge/` | 2026-09-05 | não necessária para o saldo funcionar |
| Power BI Specialist Agent | ⏳ PLANNED | — | 2026-09-05 | depende de P3/roteamento |
| Finance Specialist Agent | ⏳ PLANNED | — | 2026-09-05 | depende de P3/roteamento |

---

## 25. KNOWN ISSUES

- **`requirements.txt` — bug real corrigido em 2026-09-05:** listava `httpx2` (pacote PyPI legítimo, mas distinto de `httpx`, sem nenhuma chamada a `alias_httpx()` em lugar algum do repo) no lugar de `httpx`. `app/api/compatibility.py`, `app/core/openai_costs_ledger.py`, `app/core/openai_gateway.py`, `app/core/startup_guard.py` e `tests/test_openai_*.py` fazem `import httpx` direto. O `.venv` atual só funciona porque `httpx==0.28.1` já estava instalado nele por fora do `requirements.txt` (confirmado: `.venv/Lib/site-packages/httpx-0.28.1.dist-info` presente ao lado de `httpx2-2.12.0.dist-info`) — um `pip install -r requirements.txt` limpo (venv novo, CI, disaster recovery) quebraria os 4 módulos acima com `ModuleNotFoundError`. Corrigido para `httpx==0.28.1` (versão já validada em uso). `httpx2` não é referenciado em nenhum lugar do código — era ruído.
- **P2 operational cutover pendente (NÃO é mais decisão ambígua)** — `TaskManager` real roda em modo arquivo (`system/task-state.json`); `JARVIS_DATABASE_URL` não está configurada. Decisão de produto (banco `jarvis`, role `jarvis_app`) APROVADA e ENCERRADA em 2026-09-05; automação pronta em `scripts/cutover-p2.ps1`. Bloqueio atual é só `EXECUTION_ENVIRONMENT_NO_LOCALHOST` — precisa de um worker com acesso local real ao Windows/Postgres para executar o script. Ver §12, §27, `JARVIS_HANDOFF.md`.
- **Catálogo de agentes (RESOLVIDO/confirmado, 2026-09-05):** o vault Obsidian (`obsidian-template/Agentes/`) lista 22 personas históricas, mas o `AgentRegistry` runtime reconhece só os 8 canônicos (`morpheus, oracle, nikita, athena, neo, hephaestus, apollo, trinity`) — **confirmado pelo usuário como o conjunto correto e único que importa hoje** (foram os últimos 8 alterados/adotados). O vault permanece só como histórico/aspiracional, não é um bug e não precisa de correção.
- **Array morto em `public/index.html` (RESOLVIDO, 2026-09-05):** `AIOX=['ORION','ARIA',...]` (linha ~3209, dentro da IIFE `obsidianBrain()`) foi confirmado sem nenhum uso (grid real vem de `GET /api/agents`) e removido.
- **Catálogo de providers em `ProviderManager` é majoritariamente estático** — só `codex` tem um `ProviderAdapter` registrado; `openai`, `claude`, `gemini`, `google-account`, `microsoft-account`, `powerbi`, `vscode`, `erp-generic` existem como `ProviderDefinition` sem adapter funcional via esse catálogo. Desde o 2A, `/api/providers` combina essas definições com a disponibilidade canônica de Codex/Claude/OpenAI vinda do `ProviderAvailabilityService`; providers puramente estáticos continuam declarativos.
- **`app/api/automation.py` — shell arbitrário e JS arbitrário: RESOLVIDO em 2026-09-05 (decisão arquitetural e detalhes da correção em §22; RED/GREEN em §21):**
  - `POST /api/workflow` e `POST /api/computer-use/task` (alias `/v2`): `action_shell` (`subprocess.Popen(cmd, shell=True)` com `cmd` vindo direto do payload JSON) foi **removida inteiramente** de `system/ui-automation.py` (função deletada, não só desregistrada). `app/api/automation.py` agora valida o `type` de cada action contra um allowlist (`_validate_workflow_actions`) antes de repassar ao script — 400 imediato para qualquer `type` fora da lista (incluindo `"shell"`/`"powershell"`).
  - `POST /api/browser-control`: `execute_js` (`Runtime.evaluate` sobre `code` arbitrário do payload) foi **removida inteiramente** de `system/browser-control.py`. `navigate` agora exige `is_allowed_navigation_url()` (única policy de URL de navegação do projeto): só `http`/`https` absolutos com host — `javascript:`, `file:`, `data:`, `vbscript:`, esquema desconhecido ou URL sem esquema são bloqueados antes de qualquer chamada CDP. `app/api/automation.py` também valida o `cmd` de `/browser-control` contra um allowlist (`_validate_browser_control_cmd`).
  - **Não corrigido nesta sessão (risco menor, fora do escopo aprovado pelo usuário — não é regressão, é escopo):** `read-file`/`find-file` (mesmo arquivo) ainda aceitam `Path.home()` inteiro como raiz permitida (só leitura de texto, não execução, §9 tem `PathPolicy` mais restrita para o resto do sistema). Nenhuma rota de `/api/automation/*` tem autenticação — mitigado só por bind `127.0.0.1:8000` (§3) + CORS restritivo a origens locais (§22), não protege contra outro processo/script na mesma máquina.

---

## 26. ROADMAP

```
FOUNDATION
  ✅ Tasks (código+testes Postgres)          → ⏳ cutover operacional PENDING
  ⏳ AgentRun real (P3)                       → NOT STARTED
  ⏳ Agent routing (agente→provider mais rico) → depende de P3
  ⏳ Specialized agents (Power BI, Finance)    → depende de P3 + routing
  ⏳ Memory evolution (unificar/persistir)     → não iniciado, hoje é snapshot congelado + Obsidian vivo
  ⏳ Automation/orchestration mais rica        → MORPHEUS Fase 5A é o primeiro passo real
```

- **P2 código/testes:** ✅ APPROVED — revalidado localmente em 2026-09-07 contra Postgres real de teste (61/61 testes).
- **P2 operational cutover:** ⏳ PENDENTE execução local (decisão APPROVED, automação pronta em `scripts/cutover-p2.ps1`)
- **P3 AgentRun real:** ⏳ NOT STARTED — bloqueado transitivamente por P2 operational cutover
- **Módulo 3 — Tasks & Orchestration:** PRECISA AJUSTE. Bloco **3A — Task / AgentRun Execution Tracking**: BLOQUEADO POR P2 OPERATIONAL CUTOVER.
- **Depois de P3/agent routing:** Power BI Specialist Agent (⏳ PLANNED), Finance Specialist Agent (⏳ PLANNED)

Nenhuma numeração de fase anterior a P2 foi encontrada documentada de forma confirmável nesta auditoria além do que está registrado nos comentários de código já citados (ex.: "Fase 5A" da orquestração MORPHEUS, "PASSO 0A" do health) — não inventar outras fases.

---

## 27. CURRENT CHECKPOINT

**LAST APPROVED:**
- P2 código/testes (§12/§13): revalidado localmente em 2026-09-07 contra PostgreSQL real de teste (`jarvis_test`, `localhost:5432`), incluindo a migration 0003 (agent_id nullable) — 61 testes, 0 failures, 0 errors, 0 skips. Nenhum acesso a produção, nenhum cutover executado. Essa dependência de persistência foi descoberta e comprovada durante o Módulo 3 — Tasks & Orchestration (bloco 3A — Task / AgentRun Execution Tracking).
- Módulo 2 — Providers & Execution: blocos 2A Availability/API Coherence e 2B Execution Contracts aprovados por RED → GREEN e regressão bounded em 2026-09-07.
- Módulo 1 — Core / Runtime: blocos 1A Runtime/Lifecycle e 1B Config/Health aprovados por RED → GREEN e regressão bounded em 2026-09-07.
- OpenAI Costs Ledger operacional (baseline real, cálculo correto, sem Puppeteer/Chrome no caminho normal) — testado e validado com chamada real à Costs API.
- Claude health CHECK/ONLINE semantics (texto nunca mais contradiz o dot) — validado com execução real E2E, aprovado explicitamente pelo usuário.
- OpenAI auto-open corrigido e **validado**: extensão recarregada no Chrome real (`service_worker_registration_info.version: "1.0.2"`), 53+ minutos sem nenhum `serviceworkerevents` (nenhum disparo de alarme/onInstalled/onStartup) — ver §16.

**VALIDATION PENDING:**
- (nenhum item pendente de validação humana no momento desta atualização)

**KNOWN PENDING:**
- P2 cutover operacional (Postgres) — código E automação prontos (`scripts/cutover-p2.ps1`), não executado. Bloqueio = ambiente de execução, não decisão.
- Módulo 3 — Tasks & Orchestration: PRECISA AJUSTE. Bloco 3A — Task / AgentRun Execution Tracking: BLOQUEADO POR P2 OPERATIONAL CUTOVER — não retomar 3A nem iniciar outra etapa do Módulo 3 antes do cutover concluir.
- Drift entre o catálogo de agentes do Obsidian e o `AgentRegistry` runtime (documentado, não corrigido — correção não fazia parte do escopo desta auditoria).

**NEXT ARCHITECTURAL STEP — BLOQUEADO por ambiente de execução, NÃO por decisão humana pendente:**
- Decisão de produto ENCERRADA em 2026-09-05: banco operacional = `jarvis` (host `127.0.0.1:5432`), role dedicada = `jarvis_app`, `jarvis_test`/`jarvis_test_user` seguem só para teste. Não perguntar de novo ao usuário sobre isso.
- P2 operational cutover não pode prosseguir a partir de uma sessão Cowork (sem rota de rede até `127.0.0.1:5432`/`127.0.0.1:8000` — confirmado empiricamente). Precisa de um worker com acesso local real (Codex Desktop ou Claude Code local) executando `scripts/cutover-p2.ps1`. Ver §12, `JARVIS_HANDOFF.md` e §31 (matriz de capacidades de ambiente) para o que cada tipo de worker consegue fazer.

**DO NOT START (sem pedido explícito do usuário):**
- P3 AgentRun real (também bloqueado transitivamente: exige P2 `APPROVED` primeiro).
- P2 operational cutover — não iniciar automaticamente após a aprovação de P2 código/testes; exige pedido explícito do usuário.
- Marcar `P2 OPERATIONAL CUTOVER = APPROVED` sem um relatório `outcome: SUCCESS` real de `scripts/cutover-p2.ps1` executado de fato (não inferir a partir só do código/script existir).
- Retomar 3A — Task / AgentRun Execution Tracking antes do P2 operational cutover concluir.
- Power BI Specialist Agent.
- Finance Specialist Agent.
- Multi-agent orchestration completa.

> A auditoria que gerou este documento pode ser ajustada por trabalho futuro — sempre revalidar contra o código antes de agir.

---

## 28. CHANGELOG — RECENT ARCHITECTURAL CHANGES

**2026-09-07 (pré-cutover P2 — validação read-only, correção de drift documental)**
- **Component:** Documentação — `JARVIS_MASTER.md` (§12, §24). **Change:** o texto ainda apresentava `EXECUTION_ENVIRONMENT_NO_LOCALHOST` como o bloqueador ATUAL do P2 cutover operacional — verdade quando escrito (2026-09-05, sessão Cowork), mas desatualizado desde que uma sessão Claude Code local confirmou acesso real a `127.0.0.1:5432` em 2026-09-07 (61 testes reais contra `jarvis_test`). Corrigido para deixar claro que o ambiente local já é capaz; P2 operational cutover permanece `⏳ PENDENTE` só porque ainda não foi executado, não por limitação de ambiente. Nenhum código/teste/banco alterado; §31 (matriz de capacidades) não foi reescrita, pois continua correta para sessões Cowork. **Validation:** ✅ leitura direta do texto anterior confirmou a afirmação desatualizada antes da correção.

**2026-09-07 (normalização de nomenclatura)**
- **Component:** Documentação — `JARVIS_MASTER.md`, `JARVIS_HANDOFF.md`. **Change:** a verificação local anterior desta mesma data havia introduzido os rótulos "Módulo 5A" / "5A1" / "5A2" como se fossem uma nova estrutura modular oficial, paralela à sequência canônica do projeto (`Módulo 1 — Core/Runtime → Módulo 2 — Providers & Execution → Módulo 3 — Tasks & Orchestration → Módulo 4 — Action Engine → Módulo 5 — Persistence & State → Módulo 6 — Interface & Interaction → Módulo 7 — Agents & Knowledge`). Por pedido explícito do usuário, essa numeração paralela foi removida; "5A/5A1/5A2" era só um rótulo operacional temporário para a dependência de persistência descoberta durante o Módulo 3. Toda a evidência técnica foi preservada, só renomeada de volta para a nomenclatura já existente do projeto: **P2 código/testes** (= antigo "5A1") e **P2 operational cutover** (= antigo "5A2"); o bloco afetado do Módulo 3 é **3A — Task / AgentRun Execution Tracking**, hoje **BLOQUEADO POR P2 OPERATIONAL CUTOVER**. **Validation:** ✅ nenhuma mudança de código/teste/banco — só correção documental; nenhuma evidência técnica foi removida.

**2026-09-07 (verificação local adicional)**
- **Component:** P2 código/testes (§12/§13). **Change:** nenhuma alteração de código; verificação de regressão local pedida pelo usuário, executada por Claude Code local contra o PostgreSQL real de teste (`jarvis_test`, `localhost:5432`), confirmando que a suíte de persistência (models, repositories memory/postgres, check constraints, migration 0003 `agent_id` nullable, importer, `TaskManager` via repository) continua correta, incluindo a migration 0003 ainda não documentada nesta seção antes desta verificação. Essa dependência de persistência foi descoberta durante o trabalho do Módulo 3 — Tasks & Orchestration, bloco 3A — Task / AgentRun Execution Tracking. **Validation:** ✅ `tests.db.test_models`, `test_repositories_memory`, `test_repositories_postgres`, `test_check_constraints`, `test_agent_run_agent_id_nullable_migration`, `test_migrate_task_state_postgres`, `test_task_manager_postgres_repository` — 61 testes, 0 failures, 0 errors, 0 skips. Produção não foi acessada; nenhum cutover (P2 operacional) foi executado.

**2026-09-07**
- **Component:** Módulo 2B — Execution Contracts. **Change:** modos públicos de chat reduzidos aos executores padrão reais (`auto`, `claude`, `codex`); seleção manual `openai` passa a ser rejeitada deterministicamente antes do chat, sem remover `OpenAIGateway` ou capacidades complementares. `/api/providers/health.executor.fallbackEnabled` agora deriva de `ExecutorService.get_mode()` e só é verdadeiro em AUTO. Removidos `ExecutorService.provider_health()` e `core.diagnostics.get_provider_health()`, sem callers ativos, eliminando a detecção CLI legada paralela. **Validation:** ✅ RED direcionado: 8 testes, 6 falhas corretas; GREEN direcionado: 8/8; regressão bounded de modos/AUTO/diagnostics/providers/chat/health/profiles/OpenAI complementar/voz: 173 testes, 0 falhas. Módulo 2 aprovado; Módulo 3 não iniciado.
- **Component:** Módulo 2A — Availability / API Coherence. **Change:** `/api/providers` e `/api/providers/{id}` passaram a combinar metadata estática do `ProviderManager` com o estado operacional canônico do `ProviderAvailabilityService`; refresh de startup/autenticação e observação de chat de Codex/Claude atualizam somente a autoridade canônica, sem exigir adapter Claude nem duplicar estado operacional no catálogo. **Validation:** ✅ testes RED bounded comprovaram divergência entre catálogo e health; GREEN + regressão bounded de providers/auth/executors/modelos/AUTO/chat/diagnostics/health: 188 testes, 0 falhas. Naquele checkpoint, o Módulo 2 permanecia `PRECISA AJUSTE`, com 2B pendente.

**2026-09-05**
- **Component:** Segurança — `system/ui-automation.py`, `system/browser-control.py`, `app/api/automation.py`. **Change:** decisão arquitetural do usuário APROVADA (`ARBITRARY SHELL VIA API = FORBIDDEN`, `ARBITRARY JAVASCRIPT VIA API = FORBIDDEN`, `BROWSER AUTOMATION = ALLOWED THROUGH BOUNDED OPERATIONS`, ver §22) implementada em duas camadas: (1) `action_shell` removida inteiramente de `system/ui-automation.py`; `cmd_execute_js` removida inteiramente de `system/browser-control.py`; `cmd_navigate` agora valida contra `is_allowed_navigation_url()` (só `http`/`https` absolutos com host). (2) Defesa em profundidade em `app/api/automation.py`: `_validate_workflow_actions`/`_validate_browser_control_cmd` allowlist de `type`/`cmd` antes de repassar aos scripts. Nenhuma capability bounded preexistente foi removida (14 ações de `ui-automation.py` + `connect/list_tabs/navigate/get_dom/click/fill/get_text/wait_for/screenshot` de `browser-control.py` preservadas). **Validation:** ✅ `tests/test_automation_security.py` (34 testes) RED antes da correção (12 falhas + 27 erros, exatamente as vulnerabilidades) → GREEN depois (34/34); suíte completa Python re-rodada sem regressão nova (742→776 testes, mesmos 2 falhas/4 erros de ambiente de sempre); suíte JS re-rodada sem regressão (54 testes, mesmas 2 falhas de ambiente `Could not find Chrome`). Ver §19/§21/§22/§25.
- **Component:** `AGENTS.md`. **Change:** removidas 3 regras obsoletas que referenciavam `public/_quarentena_backups` e `jarvis-rescue-bindings.js` — confirmado por busca no repositório (`find`) que nenhum dos dois paths existe. **Validation:** ✅ busca confirmou ausência antes da remoção.
- **Component:** `requirements.txt`. **Change:** corrigido `httpx2` → `httpx==0.28.1` — `httpx2` é um pacote PyPI real mas distinto (fork/sucessor de `httpx` com API idêntica), nunca referenciado em nenhum import do código; um venv novo instalado estritamente a partir de `requirements.txt` teria quebrado 4 módulos que fazem `import httpx` direto. **Validation:** ✅ confirmado por grep no código-fonte + inspeção do `.venv` existente (`httpx-0.28.1.dist-info` já presente ao lado de `httpx2-2.12.0.dist-info`, provando que o `httpx` real veio de fora do requirements.txt).
- **Component:** Segurança — `app/api/automation.py`. **Change:** auditoria solicitada pelo usuário revelou que `POST /api/workflow`/`POST /api/computer-use/task` executam shell arbitrário via `system/ui-automation.py::action_shell` (`subprocess.Popen(cmd, shell=True)`, comando vindo direto do payload HTTP) e `POST /api/browser-control` executa JS/navega para URL arbitrária via CDP (`system/browser-control.py`) — nenhuma dessas rotas tem allowlist, verifier ou autenticação; isso contradiz a garantia estrutural de "nenhuma ação shell/browser livre" que §8/§22 descreviam, mas que na prática só vale para `ActionRegistry`/`ActionEngine`. Nenhum código foi alterado (decisão de produto/risco de segurança escalada ao usuário, não decidida unilateralmente). **Validation:** ✅ confirmado por leitura direta do código-fonte (`grep`/leitura de `system/ui-automation.py` e `system/browser-control.py`), não é suposição.
- **Component:** P2 Postgres cutover — decisão e automação. **Change:** usuário aprovou definitivamente banco `jarvis`/role `jarvis_app`/host `127.0.0.1:5432` (jarvis_test/jarvis_test_user seguem só teste); `JARVIS_HANDOFF.md` reescrito para remover qualquer indicação de decisão pendente; criado `scripts/cutover-p2.ps1` (24 etapas guard-railed/idempotentes); adicionada §31 (matriz de capacidades de ambiente) após confirmar empiricamente que a sessão Cowork não alcança `127.0.0.1:5432`/`127.0.0.1:8000` do host Windows. **Validation:** 🟡 decisão confirmada pelo usuário; script escrito mas NÃO executado/validado nesta sessão (sem acesso local) — validação real pendente de um worker local rodar `scripts/cutover-p2.ps1` e revisar o relatório JSON gerado.
- **Component:** Documentação (§25/§6). **Change:** catálogo de agentes confirmado como não-issue — usuário validou explicitamente que os 8 agentes canônicos do `AgentRegistry` são o conjunto correto (últimos alterados); vault Obsidian (22 personas) permanece só histórico. **Validation:** ✅ confirmação explícita do usuário nesta conversa.
- **Component:** Frontend — `public/index.html`. **Change:** removido o array morto `AIOX=[...]` (linha ~3209, dentro de `obsidianBrain()`), confirmado sem nenhum uso real (grid vem de `GET /api/agents`). **Validation:** ✅ grep confirmou zero referências além da declaração antes da remoção.
- **Component:** OpenAI Balance. **Change:** substituído o scraping via Puppeteer/`platform.openai.com` por `OpenAICostsLedgerService` (Organization Costs API oficial + ledger local `system/openai-balance-ledger.json`). **Validation:** ✅ testado unitariamente + E2E real com chamada autêntica à Costs API.
- **Component:** OpenAI Balance — baseline. **Change:** baseline operacional rebased de `0.09`/2026-08-25 para `4.06`/2026-09-05T10:49:00-03:00, via `BalanceLedgerStore` (sem hardcode no código). **Validation:** ✅ persistência confirmada através de restart real do processo.
- **Component:** OpenAI Balance — caminho legado. **Change:** Puppeteer removido do caminho operacional padrão (`OpenAIBalanceService` sem collector); rotas de bridge (`ingest`/`heartbeat`) mantidas mas isoladas do endpoint principal. **Validation:** ✅.
- **Component:** Extensão Chrome `openai-balance-bridge`. **Change:** removido o auto-open de `platform.openai.com/home` (`ensureHomeTab`, alarme de 5min, listeners `onInstalled`/`onStartup`); permissões `alarms`/`tabs` retiradas do manifest. **Validation:** 🟡 pendente confirmação humana pós-reload (ver §16, §25, §27).
- **Component:** Frontend — `executor-status.js`. **Change:** texto `READY` (para estado `capability_not_validated`) trocado por `CHECK`, eliminando a contradição com o dot neutro. **Validation:** ✅ E2E real (transição `CHECK → ONLINE` comprovada com execução Claude real), aprovado pelo usuário.
- **Component:** Documentação. **Change:** criados `JARVIS_MASTER.md`, `CLAUDE.md`, `AGENTS.md` como fonte canônica única compartilhada entre Claude e Codex. **Validation:** ✅ (esta própria auditoria).
- **Component:** OpenAI auto-open — validação final. **Change:** confirmado, via telemetria do próprio Chrome (`Secure Preferences`), que a extensão corrigida foi recarregada (`v1.0.2`) e não disparou nenhum evento de alarme/lifecycle em 53+ minutos. **Validation:** ✅ status elevado de `VALIDATION PENDING` para `APPROVED`.
- **Component:** AI MODELS / Claude health (Etapa 2). **Change:** investigado empiricamente se `execution_mode` afeta a disponibilidade exibida de um provider não selecionado — confirmado que NÃO afeta (Claude comprovado operacional continua `online` no painel AI MODELS mesmo com CODEX selecionado). Semântica formal ONLINE/CHECKING-UNKNOWN/OFFLINE documentada; RATE_LIMITED deferido para a Etapa 6. **Validation:** ✅ nenhuma mudança de código necessária; regressão nova travada em `tests/test_fastapi_executors.py`.

**Anterior (P2, conforme evidência de código/testes já existente no repositório):**
- Schema SQLAlchemy + Alembic para `tasks`/`agent_runs`, repositories Postgres/memory, unit-of-work, importer de `task-state.json` — código e testes existentes; **cutover operacional ainda pendente** (ver §12, §26).

---

## 29. UPDATE PROTOCOL

**Toda alteração arquitetural/funcional relevante no Jarvis deve atualizar `JARVIS_MASTER.md`.**

Fluxo obrigatório:
1. A IA lê `JARVIS_MASTER.md` por inteiro antes de trabalhar.
2. A IA investiga o código real (nunca assume só pelo prompt ou pela documentação existente).
3. A IA executa a tarefa.
4. Testes são executados.
5. Validação operacional é feita quando necessária (comportamento visual/E2E real — teste unitário não basta sozinho, ver §21).
6. **Só depois** a IA atualiza o status correspondente em `JARVIS_MASTER.md`.
7. Nenhuma feature vira `✅ APPROVED` sem evidência suficiente (testes + validação real quando aplicável).

**Regra:** implementação sem atualização do `JARVIS_MASTER.md` = tarefa incompleta, para mudanças que alterem: arquitetura, serviço, endpoint relevante, capability, agent, provider, modelo, memória, persistence, configuração operacional, roadmap, ou status de uma feature.

Correções internas sem impacto arquitetural podem só atualizar o changelog (§28), se necessário.

---

## 30. RULES FOR AI WORKERS

**ANTES de qualquer alteração:**
1. Ler `JARVIS_MASTER.md` por inteiro.
2. Localizar o componente afetado (seção correspondente deste documento).
3. Verificar o status atual (não assumir `APPROVED` sem checar evidência).
4. Verificar as decisões arquiteturais relevantes (§23) — não contradizê-las sem justificar explicitamente.
5. Verificar dependências (ex.: não implementar agentes de domínio antes de P3, ver §7/§26).
6. Não iniciar itens marcados `DO NOT START` (§27) sem pedido explícito do usuário.

**DEPOIS:**
1. Testar (unitário + integração conforme aplicável).
2. Validar (operacional/E2E real quando o item for visual ou comportamental — ver §21).
3. Atualizar `JARVIS_MASTER.md` (§29).
4. Reportar divergências encontradas entre código/teste/documentação em vez de escondê-las (ver Fase 2/3 desta auditoria — registrar como `KNOWN ISSUE / DOCUMENTATION DRIFT` ou investigar até determinar o estado real).

---

## 31. EXECUTION ENVIRONMENT CAPABILITIES

Adicionado em 2026-09-05 depois de uma sessão Cowork ter perdido tempo real tratando um bloqueio de AMBIENTE como se fosse uma decisão de produto pendente (ver JARVIS_HANDOFF.md). Objetivo: qualquer worker (humano ou IA) que pegar uma Task deve primeiro checar esta tabela para saber se o ambiente onde está rodando consegue terminá-la, antes de tentar e travar no meio.

**Regra:** não inventar capacidade — cada linha abaixo é confirmada empiricamente (por um worker que rodou naquele ambiente) ou explicitamente marcada como não confirmada/herdada.

| Capacidade | COWORK (cloud, ponte de dispositivo) | CODEX DESKTOP / WORKSPACE LOCAL | CLAUDE CODE LOCAL |
|---|---|---|---|
| Ler/editar arquivos do repositório | ✅ CONFIRMADO (2026-09-05, via ponte de pasta montada) | ✅ assumido (workspace local nativo) | ✅ assumido (workspace local nativo) |
| Rodar `git status`/editar arquivos sem rede | ✅ CONFIRMADO | ✅ assumido | ✅ assumido |
| Testes Python/JS isolados (venv próprio, sem tocar Postgres/Jarvis real) | ✅ CONFIRMADO (Python 3.10 + acesso a PyPI disponíveis na VM da ponte; `.venv` do projeto em si é Windows-only, não executável na VM Linux da ponte) | ✅ assumido | ✅ assumido |
| Controle de processo Windows (start/stop do `python run.py` real) | ❌ CONFIRMADO QUE NÃO — sem acesso ao SO Windows do host, só a uma VM Linux isolada com a pasta montada | ✅ assumido (é o próprio ambiente operacional do Jarvis) | ✅ assumido |
| `127.0.0.1:8000` (Jarvis rodando de verdade) | ❌ CONFIRMADO QUE NÃO (2026-09-05: `curl`/`/dev/tcp` recusam conexão; `/proc/net/route` da VM da ponte não tem rota até a rede do host) | ✅ assumido | ✅ assumido |
| `127.0.0.1:5432` (PostgreSQL local real) | ❌ CONFIRMADO QUE NÃO (mesma evidência acima) | ✅ assumido | ✅ assumido |
| Ler telemetria real do Chrome do usuário (`Secure Preferences` etc.) | ❌ não tentado nesta sessão (provavelmente não, mesma limitação de rede/SO) | ✅ assumido (evidência: Etapa 1 de uma sessão anterior leu isso de verdade) | ✅ assumido |

**Como isso deve orientar a escolha de worker por Task:**
- Task só de código/documentação/testes isolados (sem tocar Postgres/processo real) → qualquer worker, incluindo Cowork.
- Task que precisa parar/subir o processo Jarvis real, rodar migration real contra Postgres real, ou validar comportamento visual/E2E no navegador real do usuário → **exige** Codex Desktop ou Claude Code local. Uma sessão Cowork que receber uma Task assim deve preparar tudo que puder (script, plano, documentação) e devolver o bloqueio como `EXECUTION_ENVIRONMENT_NO_LOCALHOST` — nunca como decisão pendente do usuário, e nunca inventar uma forma de contornar a falta de rede.
