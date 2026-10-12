"""Network-free integration tests for the C++ v0002 converter."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PROJECT_ROOT / "converter" / "build_converter.ps1"
CONVERTER = PROJECT_ROOT / "build" / "egaroucid_v2_converter.exe"
COMPILER = Path(r"C:\msys64\ucrt64\bin\g++.exe")

FULL_GAME = (
    "c4e3f2e2f4c5c6g4f5e6d3c3c2d6f1b5a6b4a5b6f3a3b3c1d2e1c7d1"
    "b1g3d7a4a2e7g2d8h3b8f8f6g7g6h5h8g5h4h7h6f7e8g8b2c8a7b7a1"
    "a8g1h2h1"
)
PASS_GAME = (
    "c4c3e6c5b4a5c2e3a4a3b5d2d3f4f2b2g4b6c1d6c7h4f5d1e2b8a1f3"
    "c6a2e1b3c8g6g5d8g7b7a7d7g3h3h2g2a6g8e7e8h6f6h1f1h7a8b1g1"
    "h5f7f8h8"
)
EARLY_TERMINAL_GAME = (
    "d3c3e6e3c4c5b5c6e2f4d7a5g3c2c1e8a6d6c7f5g5b1a1b2a3c8f3f1"
    "d8f6e1a7f8a2b6g8b4h4g6h3h5d1g1h6d2g4e7b8b3f7h7a4f2g2h2g7"
    "h8b7a8"
)
FULL_ROW_PLY8 = (
    "------------OX------O-----XOOOO---XXO-----X--------------------- -4\n"
)
PASS_ROW_PLY55 = (
    "XXXXXO-XXXXOOOOXXXOXOOOOXXXOXXOOXXXOOXO-XXOXOOXXXOXOO-OXOOOOO-O- 10\n"
)


def make_layout(root: Path) -> tuple[Path, Path]:
    roots = (root / "part0", root / "part1")
    for ply in range(8, 60):
        part = 0 if ply <= 33 else 1
        folder = roots[part] / f"release_{part}" / str(ply)
        folder.mkdir(parents=True, exist_ok=True)
        game = PASS_GAME if ply == 55 else EARLY_TERMINAL_GAME if ply == 59 else FULL_GAME
        (folder / "0000000.txt").write_bytes((game + "\n").encode("ascii"))
    return roots


def source_path(roots: tuple[Path, Path], ply: int) -> Path:
    part = 0 if ply <= 33 else 1
    return roots[part] / f"release_{part}" / str(ply) / "0000000.txt"


def converter_command(
    roots: tuple[Path, Path], output: Path, *, workers: int = 4
) -> list[str]:
    return [
        str(CONVERTER),
        str(roots[0]),
        str(roots[1]),
        "--output-root",
        str(output),
        "--expected-games-per-file",
        "1",
        "--train-ratio",
        "1",
        "--val-ratio",
        "0",
        "--test-ratio",
        "0",
        "--workers",
        str(workers),
        "--quiet",
    ]


class CppConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not COMPILER.is_file():
            raise unittest.SkipTest(f"g++ is not installed at {COMPILER}")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(BUILD_SCRIPT),
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_conversion_resume_integrity_and_worker_determinism(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cpp-converter-") as temporary:
            root = Path(temporary)
            roots = make_layout(root)
            output = root / "prepared-workers4"
            completed = subprocess.run(
                converter_command(roots, output),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)

            manifest_path = output / "conversion_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("verified-limited", manifest["status"])
            self.assertEqual(52, manifest["counts"]["source_files"])
            self.assertEqual(52, manifest["counts"]["source_games"])
            self.assertEqual(51, manifest["counts"]["prepared_records"])
            self.assertEqual(1, manifest["counts"]["skipped_no_position"])
            self.assertEqual(
                {"train": 51, "val": 0, "test": 0},
                manifest["counts"]["by_split"],
            )
            self.assertEqual(52, len(manifest["sources"]))
            self.assertEqual(52, len(list((output / "train").rglob("*.txt"))))
            self.assertEqual(52, len(list((output / "val").rglob("*.txt"))))
            self.assertEqual(52, len(list((output / "test").rglob("*.txt"))))
            self.assertEqual(
                FULL_ROW_PLY8,
                (output / "train" / "8" / "0000000.txt").read_text(encoding="ascii"),
            )
            self.assertEqual(
                PASS_ROW_PLY55,
                (output / "train" / "55" / "0000000.txt").read_text(encoding="ascii"),
            )
            for split in ("train", "val", "test"):
                self.assertEqual(
                    b"", (output / split / "59" / "0000000.txt").read_bytes()
                )

            receipt = output / "_receipts" / "8" / "0000000.json"
            receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(
                source_path(roots, 8).stat().st_mtime_ns,
                receipt_payload["fingerprint"]["mtime_ns"],
            )
            # Reformat exactly as a Python json.dump receipt to exercise the
            # migration path from already completed Python conversions.
            receipt.write_text(
                json.dumps(receipt_payload, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            receipt_mtime = receipt.stat().st_mtime_ns
            resumed = subprocess.run(
                converter_command(roots, output),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            resumed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(0, resumed_manifest["run"]["converted_sources"])
            self.assertEqual(52, resumed_manifest["run"]["validated_and_skipped_sources"])
            self.assertEqual(receipt_mtime, receipt.stat().st_mtime_ns)

            output_single = root / "prepared-workers1"
            single = subprocess.run(
                converter_command(roots, output_single, workers=1),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, single.returncode, single.stderr)
            for split in ("train", "val", "test"):
                first = sorted((output / split).rglob("*.txt"), key=lambda path: path.as_posix())
                second = sorted(
                    (output_single / split).rglob("*.txt"), key=lambda path: path.as_posix()
                )
                self.assertEqual(
                    [path.relative_to(output / split) for path in first],
                    [path.relative_to(output_single / split) for path in second],
                )
                self.assertEqual(
                    [path.read_bytes() for path in first],
                    [path.read_bytes() for path in second],
                )

            corrupted = output / "train" / "8" / "0000000.txt"
            corrupted.write_bytes(corrupted.read_bytes() + b"broken\n")
            rejected = subprocess.run(
                converter_command(roots, output),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("invalid prepared row", rejected.stderr)

    def test_malformed_source_never_publishes_shards_or_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cpp-converter-failure-") as temporary:
            root = Path(temporary)
            roots = make_layout(root)
            source_path(roots, 8).write_bytes((FULL_GAME + "\nC4\n").encode("ascii"))
            output = root / "prepared"
            command = converter_command(roots, output, workers=1)
            expected_index = command.index("--expected-games-per-file") + 1
            command[expected_index] = "2"
            command.extend(("--limit-files", "1"))
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("contiguous lowercase", completed.stderr)
            self.assertEqual([], list(output.rglob("*.txt")))
            self.assertFalse((output / "_receipts" / "8" / "0000000.json").exists())
            self.assertFalse((output / "conversion_manifest.json").exists())
            self.assertEqual(3, len(list(output.rglob("*.part"))))


if __name__ == "__main__":
    unittest.main()
