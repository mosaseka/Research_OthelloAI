"""Network-free tests for the production evaluator-training data supply."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_DIR = PROJECT_ROOT / "training"
sys.path.insert(0, str(TRAINING_DIR))

import torch  # noqa: E402
import run_training_pipeline as pipeline  # noqa: E402
import train_evaluator as trainer  # noqa: E402


class TrainingDataSupplyTest(unittest.TestCase):
    def test_resume_requires_and_preserves_companion_best_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="resume-best-") as temporary:
            root = Path(temporary)
            last = root / "checkpoint_last.pt"
            best = root / "checkpoint_best.pt"
            last.touch()
            with self.assertRaisesRegex(RuntimeError, "checkpoint_best.pt"):
                trainer.resolve_resume_best_checkpoint(last)
            best.touch()
            self.assertEqual(
                best.resolve(),
                trainer.resolve_resume_best_checkpoint(last),
            )
            self.assertEqual(
                best.resolve(),
                trainer.resolve_resume_best_checkpoint(best),
            )

    @classmethod
    def setUpClass(cls) -> None:
        cls.full_config = trainer.load_config(PROJECT_ROOT / "config" / "train_full.json")
        cls.small_config = trainer.load_config(PROJECT_ROOT / "config" / "train_small.json")

    def test_train_small_remains_bounded_smoke_configuration(self) -> None:
        mode, required = trainer.validate_data_supply(
            self.small_config["data"], self.small_config["training"]
        )
        self.assertEqual("bounded", mode)
        self.assertEqual((), required)
        self.assertEqual(1000, self.small_config["training"]["steps_per_epoch"])

    def test_full_configuration_has_no_prefix_cutoff(self) -> None:
        mode, required = trainer.validate_data_supply(
            self.full_config["data"], self.full_config["training"]
        )
        self.assertEqual("full_pass", mode)
        self.assertEqual({0, 1, 2, 3}, set(required))
        for key in ("steps_per_epoch", "validation_steps", "test_steps"):
            self.assertEqual(0, self.full_config["training"][key])
        self.assertEqual(
            {"train": 0, "val": 0, "test": 0},
            self.full_config["data"]["max_source_records"],
        )

    def test_full_pass_rejects_accidental_finite_step(self) -> None:
        config = copy.deepcopy(self.full_config)
        config["training"]["steps_per_epoch"] = 1
        with self.assertRaisesRegex(ValueError, "full_pass requires zero"):
            trainer.validate_data_supply(config["data"], config["training"])

    def test_overfit_sample_is_exactly_balanced_across_four_phases(self) -> None:
        consumed = 0

        def records():
            nonlocal consumed
            for phase in trainer.PHASES:
                for index in range(700):
                    consumed += 1
                    yield {"phase": torch.tensor(phase, dtype=torch.long), "id": index}

        selected = trainer.collect_stratified_examples(records(), 2048, seed=20260715)
        self.assertEqual(2800, consumed)
        self.assertEqual(2048, len(selected))
        self.assertEqual(
            Counter({0: 512, 1: 512, 2: 512, 3: 512}),
            Counter(int(record["phase"].item()) for record in selected),
        )

    def test_overfit_sample_rejects_missing_phase(self) -> None:
        records = (
            {"phase": torch.tensor(phase, dtype=torch.long)}
            for phase in (0, 1, 2)
            for _ in range(4)
        )
        with self.assertRaisesRegex(RuntimeError, "stream supplied"):
            trainer.collect_stratified_examples(records, 8, seed=1)

    def test_synthetic_zip_scan_reports_all_phases(self) -> None:
        lines = []
        for stones in (4, 34, 44, 54):
            occupied = "".join("X" if index % 2 == 0 else "O" for index in range(stones))
            lines.append(f"{occupied + '-' * (64 - stones)} 0\n")
        with tempfile.TemporaryDirectory(prefix="training-data-test-") as temporary:
            archive_path = Path(temporary) / "sample.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("positions.txt", "".join(lines))
            data_config = {
                "strict": True,
                "split": {
                    "seed": 7,
                    "ratios": {"train": 0.8, "val": 0.1, "test": 0.1},
                },
                "expected_source_records": 4,
                "expected_phase_counts": {"0": 1, "1": 1, "2": 1, "3": 1},
            }
            result = trainer.scan_dataset([archive_path], data_config, limit=0)
            trainer.validate_scan_expectations(result, data_config)
        self.assertEqual({0: 1, 1: 1, 2: 1, 3: 1}, result["total_phase_counts"])

    def test_pipeline_all_stage_is_gated_in_order(self) -> None:
        pipeline.validate_pipeline_config(self.full_config)
        plan = pipeline.command_plan(
            PROJECT_ROOT / "config" / "train_full.json",
            self.full_config,
            "all",
            device="cpu",
            report_override=None,
            resume=None,
            export=None,
        )
        self.assertEqual(["verify", "overfit", "train"], [stage for stage, _ in plan])
        self.assertIn("--verify-all", plan[0][1])
        self.assertIn("--overfit", plan[1][1])
        self.assertIn("--no-export", plan[1][1])
        self.assertNotIn("--overfit", plan[2][1])

    def test_pipeline_dry_run_needs_no_raw_zip(self) -> None:
        exit_code = pipeline.main([
            "--config",
            str(PROJECT_ROOT / "config" / "train_full.json"),
            "--stage",
            "all",
            "--device",
            "cpu",
            "--dry-run",
        ])
        self.assertEqual(0, exit_code)

    def test_overfit_training_uses_same_small_cache_for_test(self) -> None:
        lines = []
        for stones in (24, 34, 44, 54):
            for variant in range(600):
                cells = ["-"] * 64
                for offset in range(stones):
                    position = (variant + offset * 7) % 64
                    cells[position] = "X" if offset % 2 == 0 else "O"
                lines.append("".join(cells) + " 64\n")

        with tempfile.TemporaryDirectory(prefix="overfit-cache-test-") as temporary:
            root = Path(temporary)
            archive_path = root / "sample.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("positions.txt", "".join(lines))
            config = {
                "seed": 17,
                "parameter_init": str(PROJECT_ROOT / "resources" / "param.txt"),
                "model": {"dtype": "float32"},
                "data": {
                    "paths": [str(archive_path)],
                    "strict": True,
                    "target_scale": 64.0,
                    "clip_targets": True,
                    "d4_augmentation": False,
                    "train_color_augmentation": "black_only",
                    "eval_color_augmentation": "both",
                    "shuffle_buffer": 0,
                    "epoch_sampling": {
                        "mode": "full_pass",
                        "required_phases": [0, 1, 2, 3],
                    },
                    "split": {
                        "seed": 23,
                        "ratios": {"train": 0.98, "val": 0.01, "test": 0.01},
                    },
                    "max_source_records": {"train": 0, "val": 0, "test": 0},
                },
                "training": {
                    "device": "cpu",
                    "deterministic": True,
                    "epochs": 3,
                    "batch_size": 2048,
                    "steps_per_epoch": 0,
                    "validation_steps": 0,
                    "test_steps": 0,
                    "learning_rate": 0.001,
                    "weight_decay": 0.0,
                    "gradient_clip": 5.0,
                    "phase_loss_weights": [1.0, 1.0, 1.0, 1.0],
                    "num_workers": 0,
                    "pin_memory": False,
                },
                "overfit": {
                    "enabled": False,
                    "examples": 2048,
                    "phase_stratified": True,
                    "epochs": 3,
                    "batch_size": 2048,
                    "minimum_relative_rmse_reduction": 0.000001,
                },
                "output": {
                    "runs_dir": str(root / "runs"),
                    "candidate_path": str(root / "unused_candidate.txt"),
                },
            }
            args = argparse.Namespace(
                device="cpu", resume=None, overfit=True, export=None, no_export=True
            )
            with redirect_stdout(io.StringIO()):
                candidate = trainer.train(config, args)
            self.assertIsNone(candidate)
            metrics_path = next((root / "runs").glob("run_*/metrics.jsonl"))
            events = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines()]

        test_event = next(event for event in events if event.get("event") == "test")
        gate_event = next(event for event in events if event.get("event") == "overfit_check")
        self.assertEqual(2048, test_event["test"]["count"])
        self.assertEqual(
            {"0": 512, "1": 512, "2": 512, "3": 512},
            test_event["test"]["phase_counts"],
        )
        self.assertTrue(gate_event["passed"])
        self.assertEqual(2048, gate_event["examples"])


if __name__ == "__main__":
    unittest.main()
