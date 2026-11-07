"""Testes básicos da fundação FastAPI do JARVIS."""

import json
import socket
import threading
import time
import unittest
from urllib.request import Request, urlopen

import uvicorn
from fastapi.testclient import TestClient

from app.core.config import HOST, LOCAL_ORIGINS, PORT, get_setting
from app.executors.availability import ProviderAvailabilityService
from app.main import app, create_app


class FastAPIFoundationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((HOST, 0))
            cls.test_port = probe.getsockname()[1]

        config = uvicorn.Config(app, host=HOST, port=cls.test_port, log_level="critical")
        cls.server = uvicorn.Server(config)
        cls.server_thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.server_thread.start()

        deadline = time.monotonic() + 5
        while not cls.server.started and cls.server_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not cls.server.started:
            raise RuntimeError("Uvicorn did not start during the test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.server_thread.join(timeout=5)

    def test_app_starts_and_health_matches_node_contract(self) -> None:
        with urlopen(f"http://{HOST}:{self.test_port}/api/health", timeout=5) as response:
            self.assertEqual(response.status, 200)
            payload = json.load(response)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["components"]["server"], {"status": "ok"})
        self.assertIn("openai", payload["components"])
        self.assertIn("claude", payload["components"])
        self.assertIn("chrome", payload["components"])
        self.assertIn("pools", payload["components"])
        self.assertTrue(payload["capabilities"]["task_execution"])
        self.assertEqual(
            payload["capabilities"]["voice_realtime"],
            bool(get_setting("OPENAI_API_KEY")),
        )

    def test_existing_frontend_is_served_without_modification(self) -> None:
        with urlopen(f"http://{HOST}:{self.test_port}/", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["content-type"])

    def test_network_configuration_is_local_only(self) -> None:
        self.assertEqual(HOST, "127.0.0.1")
        self.assertEqual(PORT, 8000)
        self.assertNotIn("*", LOCAL_ORIGINS)
        self.assertTrue(
            all(origin.startswith(("http://127.0.0.1:", "http://localhost:")) for origin in LOCAL_ORIGINS)
        )

    def test_health_claude_component_projects_authoritative_state(self) -> None:
        availability = ProviderAvailabilityService()
        availability.set_state(
            "claude",
            installed=True,
            authenticated=True,
            operational=True,
            entitled=True,
            reason="operational",
        )
        with TestClient(create_app(availability_service=availability)) as client:
            payload = client.get("/api/health").json()

        self.assertEqual(payload["components"]["claude"]["status"], "online")
        self.assertTrue(payload["components"]["claude"]["operational"])

    def test_cors_allows_local_origin_only(self) -> None:
        url = f"http://{HOST}:{self.test_port}/api/health"
        local_request = Request(url, headers={"Origin": "http://127.0.0.1:8000"})
        with urlopen(local_request, timeout=5) as response:
            self.assertEqual(response.headers["access-control-allow-origin"], "http://127.0.0.1:8000")

        external_request = Request(url, headers={"Origin": "https://example.com"})
        with urlopen(external_request, timeout=5) as response:
            self.assertIsNone(response.headers["access-control-allow-origin"])


if __name__ == "__main__":
    unittest.main()
