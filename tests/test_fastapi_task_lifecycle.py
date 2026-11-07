from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.tasks.manager import TaskManager, TaskTransitionError


class TaskManagerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "task-state.json"
        self.manager = TaskManager(self.state_path)

    async def asyncTearDown(self) -> None:
        await self.manager.shutdown()
        self.temp_dir.cleanup()

    async def test_create_starts_pending_then_runs_and_completes(self) -> None:
        release = asyncio.Event()

        async def operation() -> dict[str, object]:
            await release.wait()
            return {"ok": True, "value": 42}

        task = self.manager.submit("test", "complete", operation)
        self.assertEqual(task["status"], "pending")
        await asyncio.sleep(0)
        self.assertEqual(self.manager.get(task["task_id"])["status"], "running")

        release.set()
        finished = await self.manager.wait(task["task_id"])
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["result"], {"ok": True, "value": 42})

    async def test_exception_finishes_failed(self) -> None:
        async def operation() -> dict[str, object]:
            raise RuntimeError("known failure")

        task = self.manager.submit("test", "fail", operation)
        finished = await self.manager.wait(task["task_id"])

        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error"], "known failure")

    async def test_cancel_pending_while_waiting_for_desktop_lock(self) -> None:
        first_release = asyncio.Event()
        second_started = asyncio.Event()

        async def first_operation() -> dict[str, object]:
            await first_release.wait()
            return {"ok": True}

        async def second_operation() -> dict[str, object]:
            second_started.set()
            return {"ok": True}

        first = self.manager.submit("test", "first", first_operation)
        await asyncio.sleep(0)
        second = self.manager.submit("test", "second", second_operation)
        await asyncio.sleep(0)

        cancelled = await self.manager.cancel(second["task_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertFalse(second_started.is_set())

        first_release.set()
        await self.manager.wait(first["task_id"])

    async def test_cancel_running_interrupts_job_and_late_result_cannot_overwrite(self) -> None:
        started = asyncio.Event()
        cancellation_seen = asyncio.Event()

        async def cancellation_resistant_operation() -> dict[str, object]:
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancellation_seen.set()
                return {"ok": True, "late": True}

        task = self.manager.submit("test", "cancel", cancellation_resistant_operation)
        await started.wait()
        cancelled = await self.manager.cancel(task["task_id"])
        await cancellation_seen.wait()
        await asyncio.sleep(0)

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.manager.get(task["task_id"])["status"], "cancelled")
        self.assertIsNone(self.manager.get(task["task_id"])["result"])

    async def test_timeout_finishes_timeout(self) -> None:
        async def operation() -> dict[str, object]:
            await asyncio.Future()

        task = self.manager.submit("test", "timeout", operation, timeout=0.01)
        finished = await self.manager.wait(task["task_id"])

        self.assertEqual(finished["status"], "timeout")
        self.assertIn("0.01s", finished["error"])

    async def test_cancel_cancelled_is_idempotent_and_concurrent(self) -> None:
        blocker = asyncio.Event()

        async def operation() -> dict[str, object]:
            await blocker.wait()
            return {"ok": True}

        task = self.manager.submit("test", "cancel twice", operation)
        results = await asyncio.gather(
            self.manager.cancel(task["task_id"]),
            self.manager.cancel(task["task_id"]),
        )

        self.assertEqual([item["status"] for item in results], ["cancelled", "cancelled"])
        self.assertEqual(self.manager.get(task["task_id"])["status"], "cancelled")

    async def test_terminal_states_refuse_cancel_and_all_further_transitions(self) -> None:
        for terminal in ("completed", "failed", "timeout"):
            with self.subTest(terminal=terminal):
                task = self.manager.create("test", terminal)
                self.manager.transition(task["task_id"], "running")
                self.manager.transition(task["task_id"], terminal)

                with self.assertRaises(TaskTransitionError):
                    await self.manager.cancel(task["task_id"])
                with self.assertRaises(TaskTransitionError):
                    self.manager.transition(task["task_id"], "running")

                self.assertEqual(self.manager.get(task["task_id"])["status"], terminal)

    async def test_first_terminal_transition_wins_timeout_cancel_race(self) -> None:
        task = self.manager.create("test", "race")
        self.manager.transition(task["task_id"], "running")
        self.manager.transition(task["task_id"], "timeout", error="execution timed out")

        with self.assertRaises(TaskTransitionError):
            await self.manager.cancel(task["task_id"])
        with self.assertRaises(TaskTransitionError):
            self.manager.transition(task["task_id"], "completed", result={"ok": True})

        self.assertEqual(self.manager.get(task["task_id"])["status"], "timeout")
        self.assertIsNone(self.manager.get(task["task_id"])["result"])

    async def test_shutdown_cancels_active_jobs_and_persists_terminal_state(self) -> None:
        started = asyncio.Event()

        async def operation() -> dict[str, object]:
            started.set()
            await asyncio.Future()

        task = self.manager.submit("test", "shutdown", operation)
        await started.wait()
        await self.manager.shutdown()

        self.assertEqual(self.manager.get(task["task_id"])["status"], "cancelled")
        recovered = TaskManager(self.state_path)
        self.assertEqual(recovered.get(task["task_id"])["status"], "cancelled")


class TaskManagerPersistenceTests(unittest.TestCase):
    def test_summary_aggregates_structured_executors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "tasks.json")
            local = manager.create("powerbi.open", "Power BI", executor="local", display_name="Real X Meta")
            self.assertEqual(manager.summary()["executor"], "local")
            self.assertEqual(manager.summary()["active_tasks"][0]["display_name"], "Real X Meta")
            codex = manager.create("chat.provider", "Chat", executor="codex")
            self.assertEqual(manager.summary()["executor"], "multi")
            manager.transition(local["task_id"], "cancelled")
            self.assertEqual(manager.summary()["executor"], "codex")
            manager.transition(codex["task_id"], "cancelled")
            self.assertEqual(manager.summary()["executor"], "idle")

    def test_claude_executor_is_reported_only_while_its_task_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "tasks.json")
            task = manager.create("chat.provider", "Chat", executor="claude")
            manager.transition(task["task_id"], "running")
            self.assertEqual(manager.summary()["executor"], "claude")
            manager.transition(task["task_id"], "completed")
            self.assertEqual(manager.summary()["executor"], "idle")
    def test_summary_without_tasks_is_idle_and_has_no_last_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "tasks.json")

            self.assertEqual(
                manager.summary(),
                {"tasks": 0, "total": 0, "failed": 0, "executor": "idle", "last_task": None, "active_tasks": []},
            )

    def test_summary_reports_active_action_and_sanitized_recent_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "tasks.json")
            task = manager.create("powerbi.open", "secret prompt and token")

            pending = manager.summary()
            self.assertEqual(pending["tasks"], 1)
            self.assertEqual(pending["executor"], "local")
            self.assertEqual(pending["last_task"]["status"], "pending")

            manager.transition(task["task_id"], "running")
            running = manager.summary()
            self.assertEqual(running["tasks"], 1)
            self.assertEqual(running["executor"], "local")
            self.assertEqual(len(running["active_tasks"]), 1)
            self.assertEqual(running["active_tasks"][0]["task_id"], task["task_id"])
            self.assertEqual(running["active_tasks"][0]["status"], "running")
            self.assertIsNotNone(running["active_tasks"][0]["started_at"])

            manager.transition(
                task["task_id"],
                "completed",
                result={"ok": True, "token": "must-not-leak"},
            )
            completed = manager.summary()
            self.assertEqual(completed["tasks"], 0)
            self.assertEqual(completed["executor"], "idle")
            self.assertEqual(completed["last_task"]["type"], "powerbi.open")
            self.assertEqual(completed["last_task"]["status"], "completed")
            self.assertEqual(completed["active_tasks"], [])
            self.assertNotIn("must-not-leak", json.dumps(completed))
            self.assertNotIn("secret prompt", json.dumps(completed))

    def test_summary_keeps_failed_as_last_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TaskManager(Path(temp_dir) / "tasks.json")
            task = manager.create("powerbi.open", "failure")
            manager.transition(task["task_id"], "running")
            manager.transition(task["task_id"], "failed", error="sensitive detail")

            summary = manager.summary()
            self.assertEqual(summary["tasks"], 0)
            self.assertEqual(summary["executor"], "idle")
            self.assertEqual(summary["last_task"]["status"], "failed")
            self.assertNotIn("sensitive detail", json.dumps(summary))

    def test_persistence_and_recovery_preserve_completed_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "task-state.json"
            manager = TaskManager(state_path)
            task = manager.create("test", "persist")
            manager.transition(task["task_id"], "running")
            manager.transition(task["task_id"], "completed", result={"ok": True})

            recovered = TaskManager(state_path)
            self.assertEqual(recovered.get(task["task_id"])["status"], "completed")
            self.assertEqual(recovered.get(task["task_id"])["result"], {"ok": True})
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["version"], 1)
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])

    def test_recovery_migrates_legacy_states_and_failed_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "task-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "tasks": [
                            {"task_id": "queued", "status": "queued", "error": None},
                            {"task_id": "interrupted", "status": "interrupted", "error": "old detail"},
                            {"task_id": "running", "status": "running", "error": None},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            manager = TaskManager(state_path)
            manager.reconcile()

            self.assertEqual(manager.get("queued")["status"], "pending")
            self.assertEqual(manager.get("interrupted")["status"], "failed")
            self.assertIn("old detail", manager.get("interrupted")["error"])
            self.assertIn("shutdown/restart", manager.get("interrupted")["error"])
            self.assertEqual(manager.get("running")["status"], "failed")
            self.assertIn("application restart", manager.get("running")["error"])


class TaskCancellationRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = TaskManager(Path(self.temp_dir.name) / "task-state.json")
        self.app = create_app(task_manager=self.manager)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_cancel_route_returns_404_for_unknown_task(self) -> None:
        response = self.client.post("/api/tasks/missing/cancel")
        self.assertEqual(response.status_code, 404)

    def test_cancel_route_cancels_pending_task_and_is_idempotent(self) -> None:
        task = self.manager.create("test", "route")

        first = self.client.post(f"/api/tasks/{task['task_id']}/cancel")
        second = self.client.post(f"/api/tasks/{task['task_id']}/cancel")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "cancelled")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["status"], "cancelled")

    def test_cancel_route_returns_409_for_completed_task(self) -> None:
        task = self.manager.create("test", "completed")
        self.manager.transition(task["task_id"], "running")
        self.manager.transition(task["task_id"], "completed", result={"ok": True})

        response = self.client.post(f"/api/tasks/{task['task_id']}/cancel")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.manager.get(task["task_id"])["status"], "completed")


if __name__ == "__main__":
    unittest.main()
