"""Deterministic tests for the dependency-free CUI progress reporter."""

from __future__ import annotations

import io
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "training"))

from progress import ProgressReporter, track  # noqa: E402


class FakeClock:
    def __init__(self, current: float = 0.0) -> None:
        self.current = current

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class ProgressReporterTest(unittest.TestCase):
    def test_tty_uses_one_line_bar_and_finishes_with_newline(self) -> None:
        clock = FakeClock()
        output = io.StringIO()
        reporter = ProgressReporter(
            10,
            label="positions",
            phase="epoch 1/3",
            interval=0,
            stream=output,
            clock=clock,
            tty=True,
            bar_width=10,
        )
        clock.advance(2)
        reporter.update(current=5)
        interim = output.getvalue()
        self.assertTrue(interim.startswith("\r[epoch 1/3] positions | [#####.....]"))
        self.assertNotIn("\n", interim)
        self.assertIn("5/10 ( 50.0%)", interim)
        self.assertIn("2.50 items/s", interim)
        self.assertIn("00:02 elapsed", interim)
        self.assertIn("00:02 ETA", interim)

        clock.advance(2)
        reporter.finish(current=10)
        self.assertTrue(output.getvalue().endswith("00:00 ETA\n"))
        self.assertEqual(1, output.getvalue().count("\n"))

    def test_redirected_output_is_periodic_readable_lines(self) -> None:
        clock = FakeClock()
        output = io.StringIO()
        reporter = ProgressReporter(
            8, interval=2.0, stream=output, clock=clock, tty=False
        )
        reporter.update(current=1)
        clock.advance(1)
        reporter.update(current=2)
        clock.advance(1)
        reporter.update(current=4)
        reporter.finish()

        lines = output.getvalue().splitlines()
        self.assertEqual(3, len(lines))
        self.assertIn("1/8", lines[0])
        self.assertIn("4/8", lines[1])
        self.assertIn("4/8", lines[2])
        self.assertTrue(all("\r" not in line for line in lines))
        self.assertTrue(all("elapsed" in line and "ETA" in line for line in lines))

    def test_unknown_total_has_count_rate_elapsed_and_unknown_eta(self) -> None:
        clock = FakeClock()
        output = io.StringIO()
        reporter = ProgressReporter(
            None,
            label="records",
            phase="verify",
            interval=0,
            stream=output,
            clock=clock,
            tty=False,
        )
        clock.advance(4)
        reporter.update(current=12)
        reporter.finish()
        line = output.getvalue().splitlines()[0]
        self.assertIn("[verify] records | 12", line)
        self.assertIn("3.00 items/s", line)
        self.assertIn("00:04 elapsed", line)
        self.assertIn("--:-- ETA", line)
        self.assertNotIn("%", line)

    def test_zero_total_and_empty_track_are_safe(self) -> None:
        output = io.StringIO()
        clock = FakeClock()
        result = list(
            track([], label="empty", stream=output, clock=clock, tty=False)
        )
        self.assertEqual([], result)
        lines = output.getvalue().splitlines()
        self.assertEqual(2, len(lines))
        self.assertTrue(all("0/0 (100.0%)" in line for line in lines))
        self.assertTrue(lines[-1].endswith("00:00 ETA"))

    def test_quiet_keeps_api_active_without_writing(self) -> None:
        output = io.StringIO()
        clock = FakeClock()
        with ProgressReporter(
            2, quiet=True, stream=output, clock=clock, tty=True
        ) as reporter:
            self.assertFalse(reporter.advance())
            reporter.set_phase("test", label="batches", total=None, reset=True)
            reporter.advance()
        self.assertEqual(1, reporter.count)
        self.assertEqual("test", reporter.phase)
        self.assertEqual("batches", reporter.label)
        self.assertEqual("", output.getvalue())

    def test_phase_can_reset_count_total_and_clock(self) -> None:
        output = io.StringIO()
        clock = FakeClock()
        reporter = ProgressReporter(
            10, stream=output, clock=clock, tty=False, interval=99
        )
        clock.advance(5)
        reporter.update(current=5)
        clock.advance(2)
        reporter.set_phase("validation", label="batches", total=4, reset=True)
        self.assertEqual(0, reporter.count)
        self.assertEqual(4, reporter.total)
        self.assertEqual(0, reporter.elapsed)
        self.assertIn("[validation] batches | 0/4", output.getvalue().splitlines()[-1])

    def test_invalid_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ProgressReporter(-1)
        with self.assertRaises(ValueError):
            ProgressReporter(1, interval=-0.1)
        reporter = ProgressReporter(1, quiet=True)
        with self.assertRaises(ValueError):
            reporter.update(current=-1)
        with self.assertRaises(ValueError):
            reporter.set_phase("bad", total=-1)


if __name__ == "__main__":
    unittest.main()
