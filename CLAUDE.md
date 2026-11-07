# Projeto Jarvis — Claude Instructions

Before planning, investigating, modifying, debugging, or reviewing this repository, read **`JARVIS_MASTER.md`** in full.

`JARVIS_MASTER.md` is the shared canonical technical and operational context for Claude and Codex — both must work from exactly the same description of the Jarvis architecture, components, providers, agents, capabilities, endpoints, decisions, known issues, and roadmap. Do not duplicate that architecture in this file; this file only points to it and adds a few Claude-specific reminders.

Use the source hierarchy and status semantics defined in `JARVIS_MASTER.md` (comportamento/runtime comprovado > testes atuais > código atual > configuração operacional > documentação existente > relatórios/checkpoints > planos `⏳ PLANNED`). Respect its **CURRENT CHECKPOINT** section (§27): don't start anything listed under `DO NOT START` without an explicit request from the user, and don't mark something `✅ APPROVED` there without the evidence `JARVIS_MASTER.md` requires for that status.

If runtime/code/tests contradict `JARVIS_MASTER.md`, stop, report the drift explicitly, and reconcile it (fix the code, or correct the document only after validating the real state) — never silently assume either side is correct, and never silently keep working as if the document were right.

For any relevant validated change — architecture, a service, a relevant endpoint, a capability, an agent, a provider, a model, memory, persistence, operational configuration, roadmap, or a feature's status — update `JARVIS_MASTER.md` before declaring the task complete (see its §29 Update Protocol). An implementation without that update is an incomplete task.

Additional standing rules for this repository:

- **Preserve the worktree.** It is normal for this repo to carry a large amount of uncommitted, in-progress work. Never `git reset --hard`, `checkout -- .`, `clean -f`, or otherwise discard uncommitted changes to "clean up" unless explicitly asked.
- **No commit/push unless explicitly requested** in the current task — even if a previous task in the same conversation asked for one.
- **Respect `CURRENT CHECKPOINT` / `DO NOT START`** in `JARVIS_MASTER.md` — P3 (AgentRun real integration), the Power BI Specialist Agent, and the Finance Specialist Agent are explicitly not to be started without an explicit request, even if they seem like a natural next step.
