"""Unit contracts for the Python credential bridge."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from app.providers.credentials import (
    CredentialErrorCode,
    CredentialStoreError,
    DpapiSecretStore,
    SecretStore,
)


FAKE_SECRET = "test-secret-123"


class FakeRunner:
    def __init__(self, responses: list[object] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((args, kwargs))
        response = self.responses.pop(0) if self.responses else {"ok": True}
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, str):
            stdout = response
            returncode = 0
        else:
            payload = dict(response)  # type: ignore[arg-type]
            returncode = int(payload.pop("_returncode", 0))
            stdout = json.dumps(payload)
        return subprocess.CompletedProcess(args, returncode, stdout, "")


def make_store(runner: FakeRunner) -> DpapiSecretStore:
    return DpapiSecretStore(
        node_path="node-test-bin",
        bridge_path=Path("bridge-test.js"),
        timeout_seconds=2.5,
        runner=runner,
    )


class SecretStoreContractTest(unittest.TestCase):
    def test_contract_is_runtime_checkable_and_dpapi_implementation_satisfies_it(self) -> None:
        self.assertTrue(getattr(SecretStore, "_is_runtime_protocol", False))
        self.assertIsInstance(make_store(FakeRunner()), SecretStore)

    def test_domain_contract_is_independent_of_dpapi_implementation(self) -> None:
        class InMemoryStore:
            def set_secret(self, reference: str, secret: str) -> str:
                return reference

            def get_secret(self, reference: str) -> str:
                return "fake"

            def has_secret(self, reference: str) -> bool:
                return False

            def delete_secret(self, reference: str) -> bool:
                return False

        self.assertIsInstance(InMemoryStore(), SecretStore)


class DpapiSecretStoreTest(unittest.TestCase):
    def test_set_secret_uses_structured_stdin_and_returns_reference(self) -> None:
        runner = FakeRunner([{"ok": True, "reference": "provider:connection"}])
        store = make_store(runner)

        result = store.set_secret("provider:connection", FAKE_SECRET)

        self.assertEqual(result, "provider:connection")
        request = json.loads(runner.calls[0][1]["input"])  # type: ignore[arg-type]
        self.assertEqual(
            request,
            {"operation": "set", "reference": "provider:connection", "secret": FAKE_SECRET},
        )

    def test_get_secret_returns_opaque_value_without_transforming_it(self) -> None:
        opaque = "  value-with-leading-and-trailing-space  \n"
        store = make_store(FakeRunner([{"ok": True, "secret": opaque}]))
        self.assertEqual(store.get_secret("provider:connection"), opaque)

    def test_has_secret_returns_boolean(self) -> None:
        store = make_store(FakeRunner([{"ok": True, "exists": True}]))
        self.assertTrue(store.has_secret("provider:connection"))

    def test_delete_secret_is_idempotent(self) -> None:
        store = make_store(
            FakeRunner(
                [
                    {"ok": True, "deleted": True},
                    {"ok": True, "deleted": False},
                ]
            )
        )
        self.assertTrue(store.delete_secret("provider:connection"))
        self.assertFalse(store.delete_secret("provider:connection"))

    def test_rejects_empty_invalid_and_oversized_references_without_process(self) -> None:
        runner = FakeRunner()
        store = make_store(runner)
        invalid = ("", "..", "provider/name", "provider\\name", "provider\x00name", "a" * 161)
        for reference in invalid:
            with self.subTest(reference=repr(reference)):
                with self.assertRaises(CredentialStoreError) as context:
                    store.has_secret(reference)
                self.assertEqual(context.exception.code, CredentialErrorCode.INVALID_REFERENCE)
        self.assertEqual(runner.calls, [])

    def test_rejects_empty_non_string_and_oversized_secret_without_process(self) -> None:
        runner = FakeRunner()
        store = make_store(runner)
        invalid: tuple[object, ...] = ("", None, b"bytes", "x" * 65537)
        for secret in invalid:
            with self.subTest(kind=type(secret).__name__):
                with self.assertRaises(CredentialStoreError) as context:
                    store.set_secret("provider:connection", secret)  # type: ignore[arg-type]
                self.assertEqual(context.exception.code, CredentialErrorCode.INVALID_SECRET)
        self.assertEqual(runner.calls, [])

    def test_timeout_is_sanitized(self) -> None:
        runner = FakeRunner([subprocess.TimeoutExpired(["node-test-bin"], 2.5)])
        with self.assertRaises(CredentialStoreError) as context:
            make_store(runner).has_secret("provider:connection")
        self.assertEqual(context.exception.code, CredentialErrorCode.BRIDGE_TIMEOUT)
        self.assertNotIn("provider:connection", str(context.exception))

    def test_invalid_json_response_is_rejected(self) -> None:
        with self.assertRaises(CredentialStoreError) as context:
            make_store(FakeRunner(["not-json"])).has_secret("provider:connection")
        self.assertEqual(context.exception.code, CredentialErrorCode.INVALID_BRIDGE_RESPONSE)

    def test_bridge_error_is_mapped_to_safe_domain_error(self) -> None:
        runner = FakeRunner(
            [{"ok": False, "error": "DPAPI_HELPER_FAILED", "_returncode": 1}]
        )
        with self.assertRaises(CredentialStoreError) as context:
            make_store(runner).get_secret("provider:connection")
        self.assertEqual(context.exception.code, CredentialErrorCode.DPAPI_FAILED)
        self.assertEqual(str(context.exception), "Credential protection operation failed.")

    def test_missing_secret_uses_explicit_domain_error(self) -> None:
        with self.assertRaises(CredentialStoreError) as context:
            make_store(FakeRunner([{"ok": True, "secret": None}])).get_secret(
                "provider:connection"
            )
        self.assertEqual(context.exception.code, CredentialErrorCode.SECRET_NOT_FOUND)

    def test_secret_never_appears_in_exception_message(self) -> None:
        runner = FakeRunner(
            [{"ok": False, "error": "DPAPI_HELPER_FAILED", "_returncode": 1}]
        )
        with self.assertRaises(CredentialStoreError) as context:
            make_store(runner).set_secret("provider:connection", FAKE_SECRET)
        self.assertNotIn(FAKE_SECRET, str(context.exception))
        self.assertNotIn(FAKE_SECRET, repr(context.exception))

    def test_secret_never_appears_in_subprocess_arguments(self) -> None:
        runner = FakeRunner([{"ok": True, "reference": "provider:connection"}])
        make_store(runner).set_secret("provider:connection", FAKE_SECRET)
        args, kwargs = runner.calls[0]
        self.assertNotIn(FAKE_SECRET, " ".join(args))
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["timeout"], 2.5)

    def test_bridge_missing_is_sanitized(self) -> None:
        runner = FakeRunner([FileNotFoundError("node binary missing")])
        with self.assertRaises(CredentialStoreError) as context:
            make_store(runner).has_secret("provider:connection")
        self.assertEqual(context.exception.code, CredentialErrorCode.BRIDGE_UNAVAILABLE)
        self.assertNotIn("node binary missing", str(context.exception))

    def test_malformed_success_payload_is_rejected(self) -> None:
        with self.assertRaises(CredentialStoreError) as context:
            make_store(FakeRunner([{"ok": True, "exists": "yes"}])).has_secret(
                "provider:connection"
            )
        self.assertEqual(context.exception.code, CredentialErrorCode.INVALID_BRIDGE_RESPONSE)


if __name__ == "__main__":
    unittest.main()
