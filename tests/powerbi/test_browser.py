from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID


WORKSPACE_ID = UUID("12345678-1234-5678-9234-567812345678")
REPORT_ID = UUID("87654321-4321-4765-8765-876543210987")
CANONICAL_URL = (
    "https://app.powerbi.com/groups/12345678-1234-5678-9234-567812345678/"
    "reports/87654321-4321-4765-8765-876543210987"
)


def browser_module():
    try:
        return importlib.import_module("app.powerbi.browser")
    except ModuleNotFoundError as exc:
        raise AssertionError("app.powerbi.browser ainda não foi implementado") from exc


class BrowserTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.program_files = self.root / "Program Files" / "Google" / "Chrome" / "Application"
        self.program_files_x86 = self.root / "Program Files (x86)" / "Google" / "Chrome" / "Application"
        self.local_app_data = self.root / "Local" / "Google" / "Chrome" / "Application"
        self.trusted_roots = (
            self.program_files,
            self.program_files_x86,
            self.local_app_data,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def executable(self, root: Path, name: str = "chrome.exe") -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        path.write_bytes(b"MZ")
        return path


class PowerBIUrlTests(BrowserTestCase):
    def test_valid_uuids_build_the_exact_canonical_url(self) -> None:
        module = browser_module()

        result = module.build_powerbi_report_url(WORKSPACE_ID, REPORT_ID)

        self.assertEqual(result, CANONICAL_URL)

    def test_uuid_objects_are_rendered_canonically(self) -> None:
        module = browser_module()
        workspace = UUID("{12345678-1234-5678-9234-567812345678}")

        result = module.build_powerbi_report_url(workspace, REPORT_ID)

        self.assertIn("/12345678-1234-5678-9234-567812345678/", result)

    def test_non_uuid_inputs_are_rejected(self) -> None:
        module = browser_module()
        for workspace, report in (
            (str(WORKSPACE_ID), REPORT_ID),
            (WORKSPACE_ID, str(REPORT_ID)),
            ("javascript:alert(1)", REPORT_ID),
        ):
            with self.subTest(workspace=workspace, report=report):
                with self.assertRaises(ValueError):
                    module.build_powerbi_report_url(workspace, report)

    def test_validator_accepts_only_the_exact_closed_url_shape(self) -> None:
        module = browser_module()

        self.assertEqual(
            module._validate_powerbi_report_url(CANONICAL_URL, WORKSPACE_ID, REPORT_ID),
            CANONICAL_URL,
        )

    def test_validator_rejects_every_noncanonical_url_variant(self) -> None:
        module = browser_module()
        invalid_urls = (
            CANONICAL_URL.replace("https://", "http://"),
            CANONICAL_URL.replace("app.powerbi.com", "evil.example"),
            CANONICAL_URL.replace("app.powerbi.com", "localhost"),
            CANONICAL_URL.replace("app.powerbi.com", "127.0.0.1"),
            CANONICAL_URL.replace("app.powerbi.com", "app.powerbi.com:444"),
            CANONICAL_URL + "?redirect=https://evil.example",
            CANONICAL_URL + "#fragment",
            CANONICAL_URL + "/extra",
            CANONICAL_URL.replace("/groups/", "/groups/%2e%2e/"),
            "javascript:alert(1)",
            "file:///etc/passwd",
            "data:text/html,hello",
            "ftp://app.powerbi.com/report",
            "https://user:password@app.powerbi.com/groups/x/reports/y",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    module._validate_powerbi_report_url(url, WORKSPACE_ID, REPORT_ID)


class ChromeResolutionTests(BrowserTestCase):
    def resolve(self, *, registry=None, known=(), which=None):
        return browser_module().resolve_chrome(
            registry_lookup=lambda _name: registry,
            known_paths=lambda: known,
            which=lambda _name: which,
            trusted_roots=lambda: self.trusted_roots,
        )

    def test_valid_app_paths_candidate_is_preferred(self) -> None:
        chrome = self.executable(self.program_files)

        result = self.resolve(registry=chrome)

        self.assertEqual(result.executable, chrome.resolve())
        self.assertEqual(result.method, "registry_app_paths")

    def test_each_official_installation_root_is_accepted(self) -> None:
        for root, label in (
            (self.program_files, "program_files"),
            (self.program_files_x86, "program_files_x86"),
            (self.local_app_data, "local_app_data"),
        ):
            with self.subTest(root=label):
                chrome = self.executable(root)
                result = self.resolve(known=(chrome,))
                self.assertEqual(result.executable, chrome.resolve())
                self.assertEqual(result.method, "known_path")

    def test_path_candidate_is_accepted_only_inside_trusted_root(self) -> None:
        trusted = self.executable(self.local_app_data)
        self.assertEqual(self.resolve(which=str(trusted)).method, "path")

        untrusted = self.executable(self.root / "Temp")
        with self.assertRaises(FileNotFoundError):
            self.resolve(which=str(untrusted))

    def test_wrong_basename_missing_file_and_untrusted_homonym_are_rejected(self) -> None:
        wrong = self.executable(self.program_files, "not-chrome.exe")
        missing = self.program_files / "chrome.exe"
        untrusted = self.executable(self.root / "Untrusted")
        for candidate in (wrong, missing, untrusted):
            with self.subTest(candidate=candidate):
                with self.assertRaises(FileNotFoundError):
                    self.resolve(registry=candidate)

    def test_absent_chrome_is_reported_by_open_result(self) -> None:
        module = browser_module()

        result = module.open_powerbi_report(
            WORKSPACE_ID,
            REPORT_ID,
            resolver=lambda: (_ for _ in ()).throw(FileNotFoundError()),
        )

        self.assertEqual(result.outcome, module.BrowserOpenOutcome.CHROME_UNAVAILABLE)
        self.assertEqual(result.error_code, "chrome_unavailable")
        self.assertFalse(result.launch_requested)


class BrowserLaunchTests(BrowserTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.module = browser_module()
        self.chrome = self.executable(self.program_files)
        self.resolution = self.module.ChromeResolution(
            executable=self.chrome.resolve(), method="test"
        )

    def open(self, *, launcher=None, snapshots=None):
        observed = iter(snapshots or (set(), {101}))
        return self.module.open_powerbi_report(
            WORKSPACE_ID,
            REPORT_ID,
            resolver=lambda: self.resolution,
            launcher=launcher,
            process_snapshot=lambda: set(next(observed, set())),
            trusted_roots=lambda: self.trusted_roots,
        )

    def test_launcher_uses_exactly_two_structured_arguments_and_no_shell(self) -> None:
        with patch("app.powerbi.browser.subprocess.Popen") as popen:
            result = self.open()

        popen.assert_called_once_with(
            [str(self.chrome.resolve()), CANONICAL_URL],
            shell=False,
            close_fds=True,
        )
        self.assertEqual(result.outcome, self.module.BrowserOpenOutcome.OPENED)
        self.assertTrue(result.launch_requested)

    def test_url_is_revalidated_immediately_before_launch(self) -> None:
        launches: list[tuple[Path, str]] = []
        with patch.object(
            self.module,
            "build_powerbi_report_url",
            return_value="https://evil.example/report",
        ):
            result = self.open(launcher=lambda executable, url: launches.append((executable, url)))

        self.assertEqual(result.outcome, self.module.BrowserOpenOutcome.INVALID_LINK)
        self.assertEqual(launches, [])

    def test_popen_failure_is_sanitized_as_launch_failed(self) -> None:
        def fail(_executable: Path, _url: str) -> None:
            raise OSError("secret path C:\\Users\\name\\chrome.exe token=abc")

        result = self.open(launcher=fail)

        self.assertEqual(result.outcome, self.module.BrowserOpenOutcome.LAUNCH_FAILED)
        self.assertEqual(result.error_code, "launch_failed")
        self.assertNotIn("secret", repr(result))
        self.assertNotIn("token", repr(result))

    def test_preexisting_chrome_does_not_claim_visual_verification(self) -> None:
        result = self.open(launcher=lambda _executable, _url: object(), snapshots=({41}, {41}))

        self.assertEqual(result.outcome, self.module.BrowserOpenOutcome.OPENED)
        self.assertTrue(result.process_preexisting)
        self.assertTrue(result.process_detected)
        self.assertTrue(result.verification_limited)

    def test_new_pid_is_observed_but_not_required_for_opened(self) -> None:
        new_process = self.open(
            launcher=lambda _executable, _url: object(), snapshots=(set(), {52})
        )
        no_process = self.open(
            launcher=lambda _executable, _url: object(), snapshots=(set(), set())
        )

        self.assertFalse(new_process.process_preexisting)
        self.assertTrue(new_process.process_detected)
        self.assertEqual(no_process.outcome, self.module.BrowserOpenOutcome.OPENED)
        self.assertFalse(no_process.process_detected)

    def test_result_exposes_no_url_path_ids_session_or_credentials(self) -> None:
        result = self.open(launcher=lambda _executable, _url: object())
        serialized = json.dumps(result.to_dict())

        for forbidden in (
            "https://",
            str(self.chrome.resolve()),
            str(WORKSPACE_ID),
            str(REPORT_ID),
            "session",
            "token",
            "credential",
            "password",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)
        self.assertEqual(result.browser, "chrome")

    def test_invalid_ids_return_invalid_link_without_launching(self) -> None:
        launches: list[object] = []
        result = self.module.open_powerbi_report(
            str(WORKSPACE_ID),
            REPORT_ID,
            resolver=lambda: self.resolution,
            launcher=lambda *_args: launches.append(object()),
            trusted_roots=lambda: self.trusted_roots,
        )

        self.assertEqual(result.outcome, self.module.BrowserOpenOutcome.INVALID_LINK)
        self.assertEqual(result.error_code, "invalid_link")
        self.assertEqual(launches, [])

    def test_publish_to_web_src_is_preserved_byte_for_byte(self) -> None:
        source = "https://app.powerbi.com/view?r=Exact%2BToken%3D&keep=One%2FTwo"
        launches: list[str] = []
        result = self.module.open_powerbi_publish_to_web(
            source,
            resolver=lambda: self.resolution,
            launcher=lambda _executable, url: launches.append(url),
            process_snapshot=lambda: set(),
            trusted_roots=lambda: self.trusted_roots,
        )
        self.assertEqual(result.outcome, self.module.BrowserOpenOutcome.OPENED)
        self.assertEqual(launches, [source])

    def test_publish_to_web_rejects_untrusted_or_mutated_shape(self) -> None:
        for source in (
            "http://app.powerbi.com/view?r=x",
            "https://evil.example/view?r=x",
            "https://app.powerbi.com/groups/x/reports/y",
            "https://app.powerbi.com/view?x=1",
        ):
            with self.subTest(source=source):
                result = self.module.open_powerbi_publish_to_web(source)
                self.assertEqual(result.outcome, self.module.BrowserOpenOutcome.INVALID_LINK)


if __name__ == "__main__":
    unittest.main()
