# PostgreSQL P0/P1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the PostgreSQL foundation (engine/session/config) and `Task`/`AgentRun` repositories (contracts + in-memory fake + PostgreSQL implementation) as new, isolated infrastructure. No existing runtime component (`TaskManager`, `AgentExecutionService`, `AvailabilityObservedExecutor`, MORPHEUS, frontend) is modified to use it yet.

**Architecture:** New `app/db/` package: `engine.py` (engine/session factory, explicit-error-only-on-instantiation), `models.py` (SQLAlchemy 2.x declarative models for `tasks`/`agent_runs` only, Python enums for status, `native_enum=False` for evolvability), `uow.py` (minimal `unit_of_work` context manager, only to prove Task+AgentRun atomicity), `repositories.py` (Protocol contracts + shared domain exceptions), `repositories_memory.py` (in-memory fakes for unit tests), `repositories_postgres.py` (SQLAlchemy-backed implementations). Alembic lives at project root (`alembic.ini`, `alembic/`), migration `0001` creates only `tasks` + `agent_runs`. Config additions (`JARVIS_DATABASE_URL`, `JARVIS_TEST_DATABASE_URL`) go through the existing `app.core.config.get_setting()` — no new config mechanism.

**Tech Stack:** Python 3.14 (project venv), SQLAlchemy 2.0.52 (sync), Alembic 1.19.2, psycopg 3.3.5 (`psycopg[binary]`, sync driver) — chosen over asyncpg because the project has no async-DB-justifying pattern today (FastAPI routes are `async def` but call synchronous business logic directly, e.g. `TaskManager`'s synchronous file I/O; adding a sync DB call is consistent with the existing pattern, not a regression).

**Spec:** User-approved P0/P1 brief (this session) building on the prior read-only persistence audit. Approved entities this phase: `Task`, `AgentRun` only.

## Global Constraints

- `TaskManager` keeps using `system/task-state.json` — untouched. No runtime wiring to PostgreSQL.
- No `Project`/`Milestone`/`OrchestrationSession`/`OrchestrationStep`/`Approval`/`Decision`/`AuditEvent` tables.
- `timeout` is not a persisted `TaskStatus`/`AgentRunStatus` value — mapped conceptually to `failed` + `failure_code="timeout"` (schema supports `failure_code`, no migration of legacy data).
- IDs: existing `TaskManager.task_id` is already `uuid.uuid4().hex` (UUID-compatible, just hyphen-less) — new `tasks.id`/`agent_runs.id` use PostgreSQL native `UUID` type, so no incompatibility is introduced (accepts hex-without-hyphens input).
- No SQLite anywhere, not even as a test double — schema tests use SQLAlchemy `Table` metadata introspection (no engine/connection needed); DB-enforced-constraint tests and PostgreSQL repository tests run only against `JARVIS_TEST_DATABASE_URL`, and SKIP explicitly (not silently pass, not fall back) when that variable is absent — which it is in this environment today.
- `.env` real file is not modified. `.env.example` gets safe placeholder keys only.
- No commit, no push.

---

### Task 1: RED — config contract for JARVIS_DATABASE_URL / JARVIS_TEST_DATABASE_URL

**Files:**
- Create: `tests/test_db_config.py`

**Interfaces:**
- Consumes: existing `app.core.config.get_setting`.
- Produces: executable expectations for the wished-for `app.db.engine` module.

- [x] Write tests: URL readable via `get_setting("JARVIS_DATABASE_URL")` when env var set; `create_database_engine()` raises `DatabaseNotConfiguredError` when unset; `create_database_engine("sqlite:///x.db")` raises `ValueError` (no SQLite ever); `create_app()` still boots with no `JARVIS_DATABASE_URL` set (regression, proves P0 doesn't break current runtime).
- [x] Run and record RED caused by missing `app.db`.

### Task 2: GREEN — `app/db/engine.py`

**Files:**
- Create: `app/db/__init__.py`
- Create: `app/db/engine.py`

- [x] Implement `DatabaseNotConfiguredError`, `create_database_engine(url: str | None = None) -> Engine`, `create_session_factory(engine) -> sessionmaker`.
- [x] Run Task 1 tests to GREEN.

### Task 3: RED — models schema contract (no engine/connection)

**Files:**
- Create: `tests/db/__init__.py`
- Create: `tests/db/test_models.py`

- [x] Write tests against `Table`/`Enum` metadata only (`TaskRecord.__table__`, `AgentRunRecord.__table__`): column names/nullability, `TaskStatus`/`AgentRunStatus` enum values (six/five approved values, `timeout` absent), `UniqueConstraint("task_id","attempt_number")`, `UniqueConstraint("execution_key")`, FK `agent_runs.task_id -> tasks.id`, expected indexes present.
- [x] Run and record RED caused by missing `app.db.models`.

### Task 4: GREEN — `app/db/models.py`

**Files:**
- Create: `app/db/models.py`

- [x] Implement `Base`, `TaskStatus`, `AgentRunStatus` (str Enums), `TaskRecord`, `AgentRunRecord` with the fields/constraints/indexes from the approved brief; `native_enum=False` (documented decision: VARCHAR + CHECK constraint, safer/cheaper to evolve than PG native enum type which needs `ALTER TYPE` outside transactions on older PostgreSQL).
- [x] Run Task 3 tests to GREEN.

### Task 5: RED — repository contracts + in-memory fakes

**Files:**
- Create: `tests/db/test_repositories_memory.py`

- [x] Write the full RED list items 12–20 from the brief against the wished-for `InMemoryTaskRepository`/`InMemoryAgentRunRepository`: create/get/list/update Task; create/get AgentRun; list AgentRuns for a Task; two attempts (1,2) coexist; duplicate attempt rejected (`DuplicateAttemptError`); duplicate `execution_key` rejected (`DuplicateExecutionKeyError`); AgentRun for unknown Task rejected (`TaskNotFoundError`).
- [x] Run and record RED caused by missing `app.db.repositories*`.

### Task 6: GREEN — `app/db/repositories.py` + `app/db/repositories_memory.py`

**Files:**
- Create: `app/db/repositories.py`
- Create: `app/db/repositories_memory.py`

- [x] Implement `TaskRepository`/`AgentRunRepository` as `typing.Protocol` contracts plus shared exceptions (`TaskNotFoundError`, `DuplicateAttemptError`, `DuplicateExecutionKeyError`).
- [x] Implement `InMemoryTaskRepository`/`InMemoryAgentRunRepository` (dict-backed, `threading.Lock`, enforce the same uniqueness/FK-existence rules a real DB would).
- [x] Run Task 5 tests to GREEN.

### Task 7: RED — PostgreSQL repositories + Alembic migration (integration, explicit SKIP without `JARVIS_TEST_DATABASE_URL`)

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_create_tasks_and_agent_runs.py`
- Create: `tests/db/test_repositories_postgres.py`

- [x] Write RED list items 21–27 as `unittest` tests gated by `@unittest.skipUnless(os.getenv("JARVIS_TEST_DATABASE_URL"), "requires JARVIS_TEST_DATABASE_URL")`: migration creates only `tasks`+`agent_runs`; create/get Task; create/get AgentRun; FK enforced; unique attempt enforced; unique execution_key enforced; rollback via `unit_of_work` leaves no partial state.
- [x] Run: confirm tests SKIP (not pass, not fail) since `JARVIS_TEST_DATABASE_URL` is unset in this environment — record this as the RED/evidence state for this task (skip is the correct, honest outcome per the brief).

### Task 8: GREEN — `app/db/repositories_postgres.py` + `app/db/uow.py`

**Files:**
- Create: `app/db/repositories_postgres.py`
- Create: `app/db/uow.py`

- [x] Implement `unit_of_work(session_factory)` context manager (commit on success, rollback+reraise on exception).
- [x] Implement `PostgresTaskRepository`/`PostgresAgentRunRepository` (constructor accepts either `session_factory` for independent-transaction-per-call, or an explicit `session` to participate in a caller-managed `unit_of_work`); translate `IntegrityError` (unique/FK violations) into the domain exceptions from Task 6; `next_attempt_number` implemented via row lock on the parent `tasks` row (`SELECT ... FOR UPDATE`) to serialize concurrent attempt creation.
- [x] Re-run Task 7 tests: confirm still a clean, explicit SKIP (no import errors, no false pass) — this is the GREEN state achievable without a provisioned test database.

### Task 9: Config wiring + `.env.example`

**Files:**
- Modify: `.env.example`

- [x] Add `JARVIS_DATABASE_URL=` and `JARVIS_TEST_DATABASE_URL=` placeholder keys (no real credentials). Do not touch the real `.env`.

### Task 10: `requirements.txt`

**Files:**
- Modify: `requirements.txt`

- [x] Append pinned `sqlalchemy==2.0.52`, `alembic==1.19.2`, `psycopg[binary]==3.3.5` under a new commented section, matching the file's existing style.

### Task 11: Full regression + legacy JSON read-only stats + final report

- [x] Run full existing suite (`TaskManager`, `/api/tasks`, agent execution, Morpheus orchestration, chat/provider, `create_app`/startup) — confirm no pre-existing test newly touches production `system/task-state.json` because of this change (none of the new code is wired into `create_app`).
- [x] `python -m py_compile` over all new/modified `.py` files.
- [x] `alembic` config sanity check (`alembic check`/`alembic history` against the offline script, no DB connection).
- [x] Read-only stats over `system/task-state.json` for the future P2 migration note (count, `task_id` shape, `timeout` count, `agent_id` presence count, `chat.provider` count, fields not recoverable retroactively).
- [x] `git diff --check`, `git status --short` (compare to the P0-start baseline).
- [x] Write the 42-item final report in Portuguese. Do not start P2. Stop.
