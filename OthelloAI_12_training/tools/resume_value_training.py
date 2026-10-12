#!/usr/bin/env python3
"""Preflight and optionally launch the pinned value_11a checkpoint continuation.

The default is plan-only.  ``--execute`` is deliberately required before any
training subprocess is started.  This preflight never deserializes a PyTorch
checkpoint; the trusted-checkpoint load remains in train_evaluator.py after
path, companion, run-config, and metrics checks have passed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "value_11a_resume.json"


def resolve(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def last_completed_epoch(metrics_path: Path) -> int:
    last: int | None = None
    for line_number, raw in enumerate(
        metrics_path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not raw.strip():
            continue
        row = json.loads(raw)
        if not isinstance(row, dict):
            raise ValueError(f"metrics row {line_number} is not an object")
        if "epoch" in row and isinstance(row["epoch"], int):
            last = row["epoch"] if last is None else max(last, row["epoch"])
    if last is None:
        raise ValueError(f"metrics has no completed epoch: {metrics_path}")
    return last


def preflight(
    config_path: Path,
    run_dir: Path,
    device: str | None,
) -> dict[str, Any]:
    config = load_object(config_path)
    resume = config.get("resume")
    if not isinstance(resume, dict):
        raise ValueError("config.resume must be an object")
    if not bool(resume.get("require_checkpoint", False)):
        raise ValueError("resume helper requires resume.require_checkpoint=true")
    if not bool(config.get("resume_optimizer_state", False)):
        raise ValueError("resume_optimizer_state must be true for value_11a")

    allowed_roots = [resolve(value) for value in resume.get("allowed_roots", [])]
    if not allowed_roots or not any(run_dir.is_relative_to(root) for root in allowed_roots):
        raise ValueError("run-dir is outside resume.allowed_roots")

    last_path = run_dir / "checkpoint_last.pt"
    best_path = run_dir / "checkpoint_best.pt"
    resolved_path = run_dir / "config_resolved.json"
    metrics_path = run_dir / "metrics.jsonl"
    required = (last_path, best_path, resolved_path, metrics_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "resume inputs are incomplete; use config/value_11a_fresh.json "
            f"instead when they cannot be recovered: {missing}"
        )

    pinned_checkpoint = config.get("checkpoint_resume_from")
    if not isinstance(pinned_checkpoint, str) or resolve(pinned_checkpoint) != last_path:
        raise ValueError(
            "--run-dir/checkpoint_last.pt differs from checkpoint_resume_from"
        )
    saved = load_object(resolved_path)
    expected_epoch = int(resume.get("legacy_expected_epoch", -1))
    completed_epoch = last_completed_epoch(metrics_path)
    if completed_epoch != expected_epoch:
        raise ValueError(
            f"legacy run must end at epoch {expected_epoch}, got {completed_epoch}"
        )
    if int(saved.get("seed", -1)) != int(resume.get("legacy_expected_seed", -2)):
        raise ValueError("saved run seed differs from legacy_expected_seed")
    if saved.get("feature_schema") != config.get("feature_schema"):
        raise ValueError("saved/current feature_schema differs")
    if saved.get("dataset_kind") != config.get("dataset_kind"):
        raise ValueError("saved/current dataset_kind differs")
    if saved.get("data") != config.get("data"):
        raise ValueError("saved/current dataset and split contract differs")
    if saved.get("model") != config.get("model"):
        raise ValueError("saved/current model contract differs")
    if saved.get("training", {}).get("phase_loss_weights") != [1.0, 1.0, 1.0, 1.0]:
        raise ValueError("saved phase_loss_weights are not the unchanged baseline")
    if saved.get("parameter_init") != resume.get("legacy_expected_parameter_init"):
        raise ValueError("saved legacy parameter_init differs from the pinned history")

    command = [
        sys.executable,
        str(PROJECT_ROOT / "training" / "run_training_pipeline.py"),
        "--config", str(config_path),
        "--stage", "all",
        "--resume", str(last_path),
    ]
    if device:
        command.extend(("--device", device))
    return {
        "schema": "original_11_safe_resume_plan_v1",
        "execute": False,
        "config": str(config_path),
        "run_dir": str(run_dir),
        "checkpoint_last": str(last_path),
        "checkpoint_best": str(best_path),
        "completed_epoch": completed_epoch,
        "target_total_epochs": int(config["training"]["epochs"]),
        "optimizer_state": "required-and-reused",
        "optimizer_learning_rate": "overridden-by-config",
        "legacy_scheduler_state": "absent-start-new",
        "legacy_early_stop_state": "absent-start-new",
        "fallback_config": str(PROJECT_ROOT / "config" / "value_11a_fresh.json"),
        "command": command,
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--device")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run the printed pipeline command after every preflight passes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        plan = preflight(resolve(args.config), resolve(args.run_dir), args.device)
        plan["execute"] = bool(args.execute)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if not args.execute:
            return 0
        completed = subprocess.run(plan["command"], cwd=PROJECT_ROOT, check=False)
        return completed.returncode
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
