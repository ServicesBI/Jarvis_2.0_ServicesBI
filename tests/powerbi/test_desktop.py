from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.powerbi.desktop import DesktopSnapshot, DesktopWindow, PowerBIDesktopStatus, open_powerbi_desktop


class PowerBIDesktopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.pbix = Path(self.temp_dir.name) / "Real X Meta (Recomendações).pbix"
        self.pbix.write_bytes(b"PBIX")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def snapshot(*windows: DesktopWindow, pids: set[int] | None = None) -> DesktopSnapshot:
        return DesktopSnapshot(frozenset(pids if pids is not None else {w.pid for w in windows}), tuple(windows))

    def run_open(self, snapshots: list[DesktopSnapshot], launches: list[Path] | None = None):
        observed = iter(snapshots)

        async def no_sleep(_delay: float) -> None:
            return None

        return asyncio.run(open_powerbi_desktop(
            self.pbix,
            launcher=lambda path: (launches.append(path) if launches is not None else None),
            snapshot=lambda: next(observed, snapshots[-1]),
            sleeper=no_sleep,
        ))

    def test_validated_pbix_is_the_only_value_sent_to_windows_association(self) -> None:
        launches: list[Path] = []
        result = self.run_open([
            self.snapshot(),
            self.snapshot(DesktopWindow(10, 100, "Real X Meta (Recomendações)", True, True)),
        ], launches)
        self.assertEqual(launches, [self.pbix.resolve()])
        self.assertEqual(result.status, PowerBIDesktopStatus.OPENED)

    def test_empty_untitled_process_only_and_unresponsive_windows_never_confirm(self) -> None:
        invalid = (
            DesktopWindow(10, 100, "", True, True),
            DesktopWindow(10, 101, "Sem título - Power BI Desktop", True, True),
            DesktopWindow(10, 0, "", False, True),
            DesktopWindow(10, 102, "Real X Meta (Recomendações)", True, False),
        )
        result = self.run_open([self.snapshot(), self.snapshot(*invalid, pids={10})])
        self.assertEqual(result.status, PowerBIDesktopStatus.FAILED)
        self.assertFalse(result.report_loaded)
        self.assertTrue(result.process_detected)

    def test_title_after_more_than_twenty_seconds_is_accepted_within_bounded_budget(self) -> None:
        loading = self.snapshot(DesktopWindow(10, 100, "Sem título - Power BI Desktop", True, True))
        ready = self.snapshot(DesktopWindow(10, 100, "Real X Meta (Recomendações)", True, True))
        sleeps: list[float] = []
        snapshots = iter([self.snapshot()] + [loading] * 121 + [ready])

        async def record_sleep(delay: float) -> None:
            sleeps.append(delay)

        result = asyncio.run(open_powerbi_desktop(
            self.pbix,
            launcher=lambda _path: None,
            snapshot=lambda: next(snapshots, ready),
            sleeper=record_sleep,
        ))
        self.assertGreater(sum(sleeps), 20.0)
        self.assertLessEqual(sum(sleeps), 75.0)
        self.assertEqual(result.status, PowerBIDesktopStatus.OPENED)

    def test_preexisting_confirmed_report_is_explicitly_already_open_without_duplicate_launch(self) -> None:
        ready = self.snapshot(DesktopWindow(41, 900, "Real X Meta (Recomendações)", True, True))
        launches: list[Path] = []
        result = self.run_open([ready], launches)
        self.assertEqual(result.status, PowerBIDesktopStatus.ALREADY_OPEN)
        self.assertTrue(result.report_loaded)
        self.assertFalse(result.launch_requested)
        self.assertEqual((result.pid, result.window_handle), (41, 900))
        self.assertEqual(launches, [])

    def test_preexisting_unconfirmed_window_does_not_mask_launch_failure(self) -> None:
        untitled = self.snapshot(DesktopWindow(41, 900, "Sem título - Power BI Desktop", True, True))

        def fail(_path: Path) -> None:
            raise OSError("secret credential")

        result = asyncio.run(open_powerbi_desktop(self.pbix, launcher=fail, snapshot=lambda: untitled))
        self.assertEqual(result.status, PowerBIDesktopStatus.FAILED)
        self.assertEqual(result.error_code, "launch_failed")
        self.assertNotIn("secret", repr(result))

    def test_pid_switch_and_new_window_are_re_evaluated_during_polling(self) -> None:
        result = self.run_open([
            self.snapshot(pids={10}),
            self.snapshot(pids={10}),
            self.snapshot(DesktopWindow(22, 220, "Real X Meta (Recomendações)", True, True)),
        ])
        self.assertEqual(result.status, PowerBIDesktopStatus.OPENED)
        self.assertEqual((result.pid, result.window_handle), (22, 220))

    def test_known_power_bi_suffix_is_normalized_safely(self) -> None:
        result = self.run_open([
            self.snapshot(),
            self.snapshot(DesktopWindow(10, 100, " Real X Meta (Recomendações) - Power BI Desktop ", True, True)),
        ])
        self.assertEqual(result.status, PowerBIDesktopStatus.OPENED)

    def test_default_budget_is_bounded_to_ninety_seconds(self) -> None:
        delays: list[float] = []

        async def record_sleep(delay: float) -> None:
            delays.append(delay)

        result = asyncio.run(open_powerbi_desktop(
            self.pbix,
            launcher=lambda _path: None,
            snapshot=lambda: self.snapshot(pids={10}),
            sleeper=record_sleep,
        ))
        self.assertEqual(result.status, PowerBIDesktopStatus.FAILED)
        self.assertEqual(sum(delays), 90.0)


if __name__ == "__main__":
    unittest.main()
