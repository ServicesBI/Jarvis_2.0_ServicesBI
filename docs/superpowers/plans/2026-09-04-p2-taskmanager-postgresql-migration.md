# P2 — TaskManager → TaskRepository/PostgreSQL + Migração Controlada do JSON

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and execute this plan task-by-task.

**Goal:** Make `TaskManager` able to persist through `TaskRepository`/PostgreSQL instead of `system/task-state.json`, migrate the 818 legacy records into `jarvis_test` in a controlled, idempotent, non-destructive way, and prove everything end-to-end — without flipping production over (no operational Jarvis database exists yet, so cutover stays pending).

**Architecture:** `TaskManager` gains an optional `task_repository=` constructor mode (mutually exclusive with `state_path=`). In that mode every method (`create/get/list/transition/cancel/summary/shutdown`) delegates to the injected `TaskRepository`/`AgentRunRepository`-shaped contracts from `app/db/repositories.py` instead of the in-memory dict + JSON file. The legacy `status="timeout"` value (not part of the new `TaskStatus` enum) is preserved at the public-API boundary by mapping it to `TaskStatus.FAILED` + `failure_code="timeout"` on write, and reconstructing `"timeout"` on read whenever `failure_code == "timeout"`. `task_id` stays a 32-char hex string (`uuid.UUID(...).hex`), fully compatible with the existing format. File-mode behavior is untouched (same code path, same tests). `app/main.py` picks repository mode over file mode only when `JARVIS_DATABASE_URL` is configured — which it is not today, so runtime behavior does not change until a human sets it.

**Tech Stack:** Python 3.14, SQLAlchemy 2.x, Alembic, existing `app/db/*` from P0/P1/P1.5.

**Spec:** User-approved P2 brief (this session).

## Global constraints

- No AgentRun persistence in the real chat flow. No P3, Projects, Orchestration persistence, Approvals, Decisions, AuditEvent, Morpheus/5B changes, frontend changes beyond nothing.
- No commit/push. No touching SIGE/postgres/servicesbi/site-oficial. No new operational database/role without explicit human authorization.
- `system/task-state.json` is never deleted or overwritten by the migration.
- Cutover of production traffic to PostgreSQL only happens if `JARVIS_DATABASE_URL` already points at a dedicated Jarvis operational database — it doesn't, so this plan stops at "code/tests complete, migration validated in `jarvis_test`, cutover pending".

---

### Task 1 (Precondição A): CHECK constraints for status enums

- [ ] New Alembic migration `0002_add_status_check_constraints.py` (down_revision `0001`) adding CHECK constraints on `tasks.status` and `agent_runs.status` matching the approved enum values (`timeout` excluded from both).
- [ ] RED: real test against `jarvis_test` inserting an invalid status via raw SQL, expect rejection. Apply migration, GREEN.

### Task 2 (Precondição B): repeatable integration-test teardown

- [ ] Change `tests/db/test_repositories_postgres.py` fixture from `Base.metadata.create_all/drop_all` to running the real Alembic migrations (idempotent `upgrade head`) plus a table `TRUNCATE` for a clean slate — never drops schema, never desyncs `alembic_version`.
- [ ] RED/GREEN: run the integration suite twice consecutively, both green, no manual resync.

### Task 3 (Precondição C): no operational DB I/O from `app.main` import

- [ ] Move Postgres-mode reconciliation out of `TaskManager.__init__` into an explicit `reconcile()` method; `create_database_engine()`/repository construction stay side-effect-free (SQLAlchemy engines are lazy). `app/main.py` wires `reconcile()` as a FastAPI startup-event handler only when repository mode is active — mirroring the existing `refresh_codex_provider` pattern.
- [ ] RED/GREEN: importing `app.main` (module-level `app = create_app()`) with `JARVIS_DATABASE_URL` unset never touches any repository; a unit test confirms no DB call happens at import time even when `JARVIS_TEST_DATABASE_URL` is set (only `JARVIS_DATABASE_URL` controls the switch).

### Task 4: `TaskManager` repository mode

- [ ] RED: new tests covering create/get/list/transition/restart-recovery/reconciliation/no-JSON-write, against both the in-memory fake repository and real `jarvis_test`.
- [ ] GREEN: implement the repository branch in `app/tasks/manager.py`, preserving every existing public method signature and the file-mode code path unchanged.
- [ ] Backward-compat tests: ActionEngine, AvailabilityObservedExecutor, `/api/tasks`, cancel/timeout semantics, ID format — all against repository mode.

### Task 5: JSON → PostgreSQL migration script

- [ ] `app/db/migrate_task_state.py` — reads `system/task-state.json`, validates, maps legacy fields (`timeout` → `failed`+`failure_code`), writes in one transaction, idempotent reruns, full rollback on any invalid record, prints a report (counts, checksum, timestamps), never touches the source file, requires an explicit `--database-url`/target flag (no silent default to production).
- [ ] RED/GREEN with a synthetic corrupted record proving rollback; dry-run mode; idempotent-rerun test.

### Task 6: validate in `jarvis_test`

- [ ] Run migrations, run the importer for real against `jarvis_test`, compare counts (818 total, 2 timeout→failed, 736 chat.provider, 0 truthy agent_id) against the read-only stats from the P0/P1 report.

### Task 7: regression + report

- [ ] Full suite, integration tests x2, Node, compileall, alembic current/heads, git diff --check/status.
- [ ] Final report — explicitly state no operational Jarvis DB exists, `JARVIS_DATABASE_URL` stays unset, cutover pending, P3 not authorized.
