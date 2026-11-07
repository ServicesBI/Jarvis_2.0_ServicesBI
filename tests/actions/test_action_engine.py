from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.actions.engine import ActionEngine, ActionVerificationError
from app.actions.models import (
    ActionArtifact,
    ActionRequest,
    ActionResult,
    ActionRisk,
    PersistencePolicy,
)
from app.actions.policy import ActionPolicy, ConfirmationRequiredError, PathAccess, PathPolicy
from app.actions.registry import (
    ActionDefinition,
    ActionNotAllowedError,
    ActionRegistry,
    DuplicateActionError,
    UnsafeActionError,
    UnknownActionError,
)
from app.tasks.manager import TaskManager


class FakeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int = Field(gt=0)
    secret: str | None = None


async def successful_handler(arguments: FakeInput) -> ActionResult:
    return ActionResult(
        ok=True,
        action="test.create",
        summary=f"created {arguments.value}",
        artifacts=[
            ActionArtifact(
                path="C:/safe/result.txt",
                exists=True,
                size=12,
                media_type="text/plain",
            )
        ],
        data={"value": arguments.value, "token": "must-not-persist"},
    )


async def approved_verifier(_arguments: FakeInput, result: ActionResult) -> bool:
    return result.artifacts[0].exists and result.artifacts[0].size == 12


def definition(
    *,
    name: str = "test.create",
    handler=successful_handler,
    verifier=approved_verifier,
    sources: frozenset[str] = frozenset({"chat", "voice"}),
    risk: ActionRisk = ActionRisk.WRITE_FILE,
    confirmation_required: bool = False,
    timeout: float = 1.0,
    desktop_exclusive: bool = False,
    persistence: PersistencePolicy = PersistencePolicy.SANITIZED,
) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        description="Create a fake test artifact.",
        input_model=FakeInput,
        handler=handler,
        verifier=verifier,
        risk=risk,
        confirmation_required=confirmation_required,
        timeout=timeout,
        desktop_exclusive=desktop_exclusive,
        persistence=persistence,
        allowed_sources=sources,
    )


class ActionRegistryTests(unittest.TestCase):
    def test_registers_and_resolves_action_for_allowed_source(self) -> None:
        registry = ActionRegistry()
        registered = registry.register(definition())

        self.assertEqual(registered.name, "test.create")
        self.assertIs(registry.resolve("test.create", source="chat"), registered)

    def test_rejects_duplicate_name(self) -> None:
        registry = ActionRegistry()
        registry.register(definition())

        with self.assertRaises(DuplicateActionError):
            registry.register(definition())

    def test_rejects_unknown_action(self) -> None:
        with self.assertRaises(UnknownActionError):
            ActionRegistry().resolve("missing.action", source="chat")

    def test_rejects_action_from_disallowed_source(self) -> None:
        registry = ActionRegistry()
        registry.register(definition(sources=frozenset({"chat"})))

        with self.assertRaises(ActionNotAllowedError):
            registry.resolve("test.create", source="realtime")

    def test_validates_schema_and_forbids_extra_fields(self) -> None:
        registry = ActionRegistry()
        registry.register(definition())

        validated = registry.validate_arguments("test.create", {"value": 2})
        self.assertEqual(validated.value, 2)
        with self.assertRaises(ValidationError):
            registry.validate_arguments("test.create", {"value": 2, "command": "whoami"})

    def test_rejects_invalid_schema_values(self) -> None:
        registry = ActionRegistry()
        registry.register(definition())

        with self.assertRaises(ValidationError):
            registry.validate_arguments("test.create", {"value": 0})

    def test_never_registers_shell_action(self) -> None:
        registry = ActionRegistry()

        with self.assertRaises(UnsafeActionError):
            registry.register(definition(name="shell"))
        with self.assertRaises(UnsafeActionError):
            registry.register(definition(name="desktop.shell"))


class ActionPolicyTests(unittest.TestCase):
    def test_confirmation_is_required_before_sensitive_action(self) -> None:
        policy = ActionPolicy()
        request = ActionRequest(action="test.create", arguments={"value": 1}, source="chat")

        with self.assertRaises(ConfirmationRequiredError):
            policy.authorize(definition(confirmation_required=True), request)

        confirmed = request.model_copy(update={"confirmed": True})
        policy.authorize(definition(confirmation_required=True), confirmed)

    def test_path_policy_separates_read_and_write_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            read_root = root / "read"
            write_root = root / "write"
            read_root.mkdir()
            write_root.mkdir()
            existing = read_root / "input.txt"
            existing.write_text("ok", encoding="utf-8")
            policy = PathPolicy(read_roots=(read_root,), write_roots=(write_root,))

            self.assertEqual(policy.validate(existing, access=PathAccess.READ), existing)
            self.assertEqual(
                policy.validate(write_root / "output.txt", access=PathAccess.WRITE),
                write_root / "output.txt",
            )
            with self.assertRaises(PermissionError):
                policy.validate(root / "outside.txt", access=PathAccess.WRITE)


class ActionEngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = TaskManager(Path(self.temp_dir.name) / "task-state.json")
        self.registry = ActionRegistry()
        self.registry.register(definition())
        self.engine = ActionEngine(self.registry, self.manager)

    async def asyncTearDown(self) -> None:
        await self.manager.shutdown()
        self.temp_dir.cleanup()

    async def test_valid_action_creates_exactly_one_task_and_uniform_result(self) -> None:
        task = self.engine.submit(
            ActionRequest(action="test.create", arguments={"value": 3}, source="chat")
        )
        finished = await self.manager.wait(task["task_id"])

        self.assertEqual(len(self.manager.list()), 1)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["type"], "test.create")
        self.assertEqual(finished["result"]["action"], "test.create")
        self.assertEqual(finished["result"]["summary"], "created 3")
        self.assertEqual(finished["result"]["artifacts"][0]["exists"], True)
        self.assertEqual(finished["result"]["data"], {"value": 3, "token": "[REDACTED]"})

    async def test_invalid_schema_creates_no_task_and_no_effect(self) -> None:
        effects: list[int] = []

        async def handler(arguments: FakeInput) -> ActionResult:
            effects.append(arguments.value)
            return ActionResult(ok=True, action="test.invalid")

        registry = ActionRegistry()
        registry.register(definition(name="test.invalid", handler=handler))
        engine = ActionEngine(registry, self.manager)

        with self.assertRaises(ValidationError):
            engine.submit(
                ActionRequest(
                    action="test.invalid",
                    arguments={"value": -1, "shell": "echo unsafe"},
                    source="chat",
                )
            )

        self.assertEqual(effects, [])
        self.assertEqual(self.manager.list(), [])

    async def test_unknown_action_executes_nothing(self) -> None:
        with self.assertRaises(UnknownActionError):
            self.engine.submit(
                ActionRequest(
                    action="missing.action",
                    arguments={"command": "echo arbitrary"},
                    source="chat",
                )
            )

        self.assertEqual(self.manager.list(), [])

    async def test_failed_verifier_marks_task_failed(self) -> None:
        async def rejected(_arguments: FakeInput, _result: ActionResult) -> bool:
            return False

        registry = ActionRegistry()
        registry.register(definition(name="test.unverified", verifier=rejected))
        engine = ActionEngine(registry, self.manager)
        task = engine.submit(
            ActionRequest(action="test.unverified", arguments={"value": 1}, source="chat")
        )
        finished = await self.manager.wait(task["task_id"])

        self.assertEqual(finished["status"], "failed")
        self.assertIn("verifier", finished["error"].lower())

    async def test_timeout_is_enforced_by_existing_task_manager(self) -> None:
        async def blocked(_arguments: FakeInput) -> ActionResult:
            await asyncio.Future()
            raise AssertionError("unreachable")

        registry = ActionRegistry()
        registry.register(definition(name="test.timeout", handler=blocked, timeout=0.01))
        engine = ActionEngine(registry, self.manager)
        task = engine.submit(
            ActionRequest(action="test.timeout", arguments={"value": 1}, source="chat")
        )
        finished = await self.manager.wait(task["task_id"])

        self.assertEqual(finished["status"], "timeout")
        self.assertIn("0.01s", finished["error"])

    async def test_desktop_exclusive_actions_do_not_overlap(self) -> None:
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        second_started = asyncio.Event()

        async def handler(arguments: FakeInput) -> ActionResult:
            if arguments.value == 1:
                first_started.set()
                await release_first.wait()
            else:
                second_started.set()
            return ActionResult(ok=True, action="test.desktop")

        registry = ActionRegistry()
        registry.register(
            definition(name="test.desktop", handler=handler, desktop_exclusive=True)
        )
        engine = ActionEngine(registry, self.manager)
        first = engine.submit(
            ActionRequest(action="test.desktop", arguments={"value": 1}, source="chat")
        )
        second = engine.submit(
            ActionRequest(action="test.desktop", arguments={"value": 2}, source="chat")
        )

        await first_started.wait()
        await asyncio.sleep(0)
        self.assertFalse(second_started.is_set())
        release_first.set()
        await self.manager.wait(first["task_id"])
        await self.manager.wait(second["task_id"])
        self.assertTrue(second_started.is_set())

    async def test_confirmation_failure_creates_no_task(self) -> None:
        registry = ActionRegistry()
        registry.register(definition(name="test.sensitive", confirmation_required=True))
        engine = ActionEngine(registry, self.manager)

        with self.assertRaises(ConfirmationRequiredError):
            engine.submit(
                ActionRequest(
                    action="test.sensitive", arguments={"value": 1}, source="chat"
                )
            )

        self.assertEqual(self.manager.list(), [])


if __name__ == "__main__":
    unittest.main()
