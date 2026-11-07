"""Testes do preflight de startup idempotente do backend Jarvis (porta 8000)."""

from __future__ import annotations

import socket
import threading
import time
import unittest

import uvicorn

from app.core.config import HOST, PORT
from app.core.startup_guard import (
    StartupDecision,
    describe_port_owner,
    is_jarvis_health_payload,
    probe_jarvis_health,
    run_preflight,
)
from app.main import app


def _free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


class OfficialHostAndPortTest(unittest.TestCase):
    def test_official_host_and_port_are_unchanged(self) -> None:
        self.assertEqual(HOST, "127.0.0.1")
        self.assertEqual(PORT, 8000)


class HealthPayloadContractTest(unittest.TestCase):
    def test_valid_jarvis_payload_is_recognized(self) -> None:
        payload = {"status": "degraded", "components": {"server": {"status": "ok"}}}
        self.assertTrue(is_jarvis_health_payload(payload))

    def test_missing_components_is_rejected(self) -> None:
        self.assertFalse(is_jarvis_health_payload({"status": "ok"}))

    def test_wrong_server_status_is_rejected(self) -> None:
        payload = {"components": {"server": {"status": "error"}}}
        self.assertFalse(is_jarvis_health_payload(payload))

    def test_unrelated_json_shape_is_rejected(self) -> None:
        self.assertFalse(is_jarvis_health_payload({"foo": "bar"}))

    def test_non_dict_payload_is_rejected(self) -> None:
        self.assertFalse(is_jarvis_health_payload(["not", "a", "dict"]))
        self.assertFalse(is_jarvis_health_payload(None))


class PreflightWithFreePortTest(unittest.TestCase):
    def test_free_port_allows_start(self) -> None:
        port = _free_port()
        result = run_preflight(HOST, port)
        self.assertEqual(result.decision, StartupDecision.START)


class PreflightWithHealthyJarvisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_port = _free_port()
        config = uvicorn.Config(app, host=HOST, port=cls.test_port, log_level="critical")
        cls.server = uvicorn.Server(config)
        cls.server_thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.server_thread.start()

        deadline = time.monotonic() + 5
        while not cls.server.started and cls.server_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not cls.server.started:
            raise RuntimeError("Servidor de teste nao iniciou")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.server_thread.join(timeout=5)

    def test_healthy_jarvis_is_detected_as_already_running(self) -> None:
        result = run_preflight(HOST, self.test_port)
        self.assertEqual(result.decision, StartupDecision.ALREADY_RUNNING)

    def test_existing_instance_is_not_disturbed(self) -> None:
        run_preflight(HOST, self.test_port)
        # A instancia real continua respondendo normalmente depois do preflight.
        self.assertTrue(probe_jarvis_health(HOST, self.test_port))

    def test_preflight_is_idempotent_and_read_only(self) -> None:
        first = run_preflight(HOST, self.test_port)
        second = run_preflight(HOST, self.test_port)
        self.assertEqual(first.decision, second.decision)
        self.assertEqual(second.decision, StartupDecision.ALREADY_RUNNING)


class PreflightWithUnknownOccupantTest(unittest.TestCase):
    def setUp(self) -> None:
        self.port = _free_port()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind((HOST, self.port))
        self.listener.listen(1)

    def tearDown(self) -> None:
        self.listener.close()

    def test_port_occupied_by_non_jarvis_blocks_start(self) -> None:
        result = run_preflight(HOST, self.port)
        self.assertEqual(result.decision, StartupDecision.PORT_OCCUPIED)

    def test_unknown_occupant_socket_is_never_closed_by_preflight(self) -> None:
        run_preflight(HOST, self.port)
        # O socket que criamos continua vivo: nada foi encerrado automaticamente.
        self.assertNotEqual(self.listener.fileno(), -1)
        self.assertEqual(self.listener.getsockname()[1], self.port)

    def test_describe_port_owner_is_bounded_and_never_raises(self) -> None:
        description = describe_port_owner(self.port)
        self.assertIsInstance(description, str)
        self.assertTrue(description)


class PreflightHealthTimeoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.port = _free_port()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind((HOST, self.port))
        self.listener.listen(1)

        def _accept_and_hang() -> None:
            try:
                self.listener.settimeout(5)
                connection, _ = self.listener.accept()
                connection.close()
            except OSError:
                pass

        self.thread = threading.Thread(target=_accept_and_hang, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.listener.close()
        self.thread.join(timeout=2)

    def test_unresponsive_occupant_is_treated_as_unknown_within_bounded_time(self) -> None:
        started = time.monotonic()
        result = run_preflight(HOST, self.port)
        elapsed = time.monotonic() - started
        self.assertEqual(result.decision, StartupDecision.PORT_OCCUPIED)
        self.assertLess(elapsed, 5, "preflight nao deve travar esperando instancia inexistente")


if __name__ == "__main__":
    unittest.main()
