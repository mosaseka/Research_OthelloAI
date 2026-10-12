#!/usr/bin/env python3
"""Plan or execute the dedicated one-epoch full-pass timing run.

The default only validates and prints the command.  ``--execute`` is required
to start the expensive epoch.  The child uses train_evaluator.py's production
train/validation path and writes a timing-only manifest, never a candidate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "timing_only_value.json"


def resolve(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("timing config root must be an object")
    return value


def plan(config_path: Path, device: str | None) -> dict[str, Any]:
    config = load_object(config_path)
    safety = config.get("safety")
    training = config.get("training")
    data = config.get("data")
    if not isinstance(safety, dict) or safety.get("timing_only") is not True:
        raise ValueError("timing config must set safety.timing_only=true")
    if safety.get("adoption_eligible") is not False:
        raise ValueError("timing output must be adoption_eligible=false")
    if not isinstance(training, dict) or int(training.get("epochs", -1)) != 1:
        raise ValueError("timing config must run exactly one epoch")
    if any(int(training.get(key, -1)) != 0 for key in (
        "steps_per_epoch", "validation_steps", "test_steps"
    )):
        raise ValueError("timing config forbids finite step limits")
    if not isinstance(data, dict):
        raise ValueError("timing config has no data section")
    sampling = data.get("epoch_sampling")
    if not isinstance(sampling, dict) or sampling.get("mode") != "full_pass":
        raise ValueError("timing config must use full_pass")
    if sampling.get("required_phases") != [0, 1, 2, 3]:
        raise ValueError("timing config must cover all four phases")
    limits = data.get("max_source_records")
    if not isinstance(limits, dict) or any(int(limits.get(split, -1)) != 0 for split in (
        "train", "val", "test"
    )):
        raise ValueError("timing config forbids source record limits")
    if config.get("checkpoint_resume_from") is not None:
        raise ValueError("timing run cannot resume")
    if not str(config.get("output_dir", "")).startswith("artifacts/timing_only_runs"):
        raise ValueError("timing output must use its exclusive timing_only_runs root")

    command = [
        sys.executable,
        str(PROJECT_ROOT / "training" / "train_evaluator.py"),
        "--config", str(config_path),
        "--timing-only",
        "--no-export",
    ]
    if device:
        command.extend(("--device", device))
    return {
        "schema": "original-11-value-timing-plan-v1",
        "execute": False,
        "config": str(config_path),
        "command": command,
        "work": "one full train epoch plus one normal full validation pass",
        "production_code_path_same": True,
        "heldout_test": "skipped",
        "candidate_export": "forbidden",
        "adoption_eligible": False,
        "output_root": str(resolve(config["output"]["runs_dir"])),
        "ctrl_c": "partial epoch is not checkpointed; rerun from epoch start",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        value = plan(resolve(args.config), args.device)
        value["execute"] = bool(args.execute)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        if not args.execute:
            return 0
        completed = subprocess.run(value["command"], cwd=PROJECT_ROOT, check=False)
        return completed.returncode
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
