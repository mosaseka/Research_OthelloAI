#!/usr/bin/env python3
"""Plan or continue an interrupted original_11 format-2 value run safely.

Use ``resume_value_training.py`` exactly once for the pinned original_10
format-1 import.  Use this helper only after original_11 has written its own
format-2 checkpoint_last/checkpoint_best pair at an epoch boundary.  The
default is plan-only; ``--execute`` is required to launch subprocesses.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def last_epoch_and_events(path: Path) -> tuple[int, set[str]]:
    last = -1
    events: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: row is not an object")
            if isinstance(value.get("epoch"), int):
                last = max(last, int(value["epoch"]))
            if isinstance(value.get("event"), str):
                events.add(str(value["event"]))
    if last < 0:
        raise ValueError(f"{path}: no completed epoch")
    return last, events


def stable_identity(config: dict[str, Any]) -> dict[str, Any]:
    training = {
        key: value
        for key, value in config.get("training", {}).items()
        if key not in {"epochs", "device", "pin_memory"}
    }
    return {
        "run_name": config.get("run_name"),
        "candidate_name": config.get("candidate_name"),
        "source_model_sha256": config.get("source_model_sha256"),
        "feature_schema": config.get("feature_schema"),
        "experiment": config.get("experiment"),
        "dataset_kind": config.get("dataset_kind"),
        "seed": config.get("seed"),
        "parameter_init": config.get("parameter_init"),
        "model": config.get("model"),
        "data": config.get("data"),
        "training": training,
        "overfit": config.get("overfit"),
    }


def preflight(config_path: Path, checkpoint: Path, device: str | None) -> dict[str, Any]:
    config = load_object(config_path)
    resume = config.get("resume")
    if not isinstance(resume, dict) or not bool(resume.get("allow_format_2_resume", False)):
        raise ValueError("config does not allow same-variant format-2 continuation")
    if not bool(config.get("resume_optimizer_state", False)):
        raise ValueError("resume_optimizer_state must be true")
    if checkpoint.name != "checkpoint_last.pt" or not checkpoint.is_file():
        raise ValueError("--checkpoint must be an existing checkpoint_last.pt")
    best = checkpoint.with_name("checkpoint_best.pt")
    if not best.is_file():
        raise FileNotFoundError(f"checkpoint_best.pt is missing beside {checkpoint}")

    pinned = config.get("checkpoint_resume_from")
    if isinstance(pinned, str) and resolve(pinned) == checkpoint:
        raise ValueError(
            "the pinned original_10 import belongs to resume_value_training.py, not this helper"
        )
    roots = [resolve(value) for value in resume.get("allowed_roots", [])]
    # Exclude broad/external legacy roots: a format-2 continuation must live
    # below this config's own output.runs_dir.
    own_root = resolve(config["output"]["runs_dir"])
    if own_root not in roots or not checkpoint.is_relative_to(own_root):
        raise ValueError("format-2 checkpoint is outside this variant's own runs_dir")

    run_dir = checkpoint.parent
    resolved_config_path = run_dir / "config_resolved.json"
    metrics_path = run_dir / "metrics.jsonl"
    for required in (resolved_config_path, metrics_path):
        if not required.is_file():
            raise FileNotFoundError(f"format-2 run sidecar is missing: {required}")
    saved = load_object(resolved_config_path)
    if stable_identity(saved) != stable_identity(config):
        raise ValueError("saved run identity/data/model contract differs from current config")
    if saved.get("resolved", {}).get("overfit") is not False:
        raise ValueError("overfit-gate checkpoints are not production continuation checkpoints")
    if int(saved.get("resolved", {}).get("checkpoint_format_version", -1)) != 2:
        raise ValueError("saved run sidecar does not declare checkpoint format 2")
    last_epoch, events = last_epoch_and_events(metrics_path)
    target_epochs = int(config["training"]["epochs"])
    if last_epoch >= target_epochs - 1:
        raise ValueError("run has already reached the configured epoch target")
    if "early_stop" in events or "test" in events:
        raise ValueError("run is already early-stopped or finalized; do not continue it")

    command = [
        sys.executable,
        str(PROJECT_ROOT / "training" / "run_training_pipeline.py"),
        "--config", str(config_path),
        "--stage", "all",
        "--resume", str(checkpoint),
    ]
    if device:
        command.extend(("--device", device))
    return {
        "schema": "original-11-format2-continuation-plan-v1",
        "execute": False,
        "config": str(config_path),
        "variant": config.get("experiment", {}).get("variant"),
        "checkpoint_last": str(checkpoint),
        "checkpoint_best": str(best),
        "completed_epoch": last_epoch,
        "restart_epoch": last_epoch + 1,
        "target_total_epochs": target_epochs,
        "optimizer_scheduler_early_stop_rng": "restored-by-format2-loader",
        "interrupted_partial_epoch": "discarded-and-repeated-from-epoch-start",
        "output": "a new exclusive run directory under the same variant runs_dir",
        "command": command,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--device")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        plan = preflight(resolve(args.config), resolve(args.checkpoint), args.device)
        plan["execute"] = bool(args.execute)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        if not args.execute:
            return 0
        completed = subprocess.run(plan["command"], cwd=PROJECT_ROOT, check=False)
        return completed.returncode
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
