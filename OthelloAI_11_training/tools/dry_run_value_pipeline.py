#!/usr/bin/env python3
"""Run the isolated original_11 file-backed training smoke contract.

This driver never reads the production dataset and writes only inside a system
temporary directory.  It checks a file-backed mini batch, forward/backward and
finite loss, AdamW, scheduler, atomic format-2 checkpoint save/resume, Java
parameter export/count, and a small Java/Python parity sample.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_DIR = PROJECT_ROOT / "training"
sys.path.insert(0, str(TRAINING_DIR))

import torch  # noqa: E402
from torch.utils.data import default_collate  # noqa: E402

from evaluator_model import (  # noqa: E402
    EXPECTED_PARAMETER_COUNT,
    JavaCompatibleEvaluator,
    export_java_parameters,
    feature_tensors,
    features_from_relative,
    read_parameter_values,
)
from train_evaluator import (  # noqa: E402
    build_scheduler,
    early_stopping_settings,
    file_sha256,
    restore_rng_state,
    save_checkpoint,
    set_reproducible_seed,
)


DEFAULT_CONFIG = PROJECT_ROOT / "config" / "dry_run_value.json"


def resolve(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def fixture_batch(config: dict[str, Any], dtype: torch.dtype) -> dict[str, torch.Tensor]:
    fixture_path = resolve(config["fixture_file"])
    fixture = load_object(fixture_path)
    if fixture.get("schema") != "original_11_dry_run_positions_v1":
        raise ValueError("unexpected dry-run fixture schema")
    if fixture.get("training_eligible") is not False:
        raise ValueError("dry-run fixture must be marked training_eligible=false")
    positions = fixture.get("positions")
    if not isinstance(positions, list) or len(positions) != int(config["fixture_records"]):
        raise ValueError("dry-run fixture record count differs from config")
    records = []
    for index, item in enumerate(positions):
        if not isinstance(item, dict):
            raise ValueError(f"fixture position {index} is not an object")
        rows = item.get("rows")
        if (
            not isinstance(rows, list)
            or len(rows) != 8
            or any(not isinstance(row, str) or len(row) != 8 for row in rows)
        ):
            raise ValueError(f"fixture position {index} must contain eight rows")
        board = "".join(rows).replace(".", "-")
        if len(board) != 64 or set(board) - {"X", "O", "-"}:
            raise ValueError(f"fixture position {index} has invalid symbols")
        player = int(item["player"])
        target = float(item["target"]) / 64.0
        records.append(feature_tensors(
            features_from_relative(board, player), target=target
        ))
    batch = default_collate(records)
    batch["target"] = batch["target"].to(dtype=dtype)
    return batch


def run(config: dict[str, Any]) -> dict[str, Any]:
    safety = config.get("safety")
    if not isinstance(safety, dict) or safety.get("dry_run_only") is not True:
        raise ValueError("config must be explicitly dry_run_only")
    if safety.get("allow_production_pipeline") is not False:
        raise ValueError("dry-run config must forbid the production pipeline")
    if safety.get("allow_external_dataset_reads") is not False:
        raise ValueError("dry-run config must forbid production dataset reads")
    if int(config.get("epochs", -1)) != 1:
        raise ValueError("dry-run epochs must be exactly one")
    if int(config.get("train_batches", -1)) != 1:
        raise ValueError("dry-run train_batches must be exactly one")
    if int(config.get("validation_batches", -1)) != 1:
        raise ValueError("dry-run validation_batches must be exactly one")
    if int(config.get("checkpoint_save_resume_cycles", -1)) != 1:
        raise ValueError("dry-run checkpoint cycle count must be exactly one")

    seed = int(config["seed"])
    set_reproducible_seed(seed, True)
    dtype_name = str(config["dtype"])
    dtype = {"float32": torch.float32, "float64": torch.float64}.get(dtype_name)
    if dtype is None:
        raise ValueError("dry-run dtype must be float32 or float64")
    device = torch.device(str(config.get("device", "cpu")))
    if device.type != "cpu":
        raise ValueError("the isolated dry-run is intentionally CPU-only")

    parameter_init = resolve(config["parameter_init"])
    actual_sha = file_sha256(parameter_init)
    if actual_sha != str(config["source_model_sha256"]).lower():
        raise RuntimeError("dry-run source model SHA-256 mismatch")
    batch = fixture_batch(config, dtype)
    if int(batch["phase"].shape[0]) != int(config["batch_size"]):
        raise ValueError("fixture count must equal dry-run batch_size")

    training_config = {
        "scheduler": config["scheduler"],
        "early_stopping": config["early_stopping"],
    }
    model = JavaCompatibleEvaluator(dtype)
    model.load_java_parameters(parameter_init)
    model.to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config["learning_rate"]),
        weight_decay=float(config["weight_decay"]),
    )
    scheduler = build_scheduler(optimizer, training_config)
    early_settings = early_stopping_settings(training_config)

    optimizer.zero_grad(set_to_none=True)
    prediction = model(batch)
    loss = torch.mean((prediction - batch["target"]) ** 2)
    if not math.isfinite(float(loss.detach().cpu())):
        raise RuntimeError("dry-run training loss is not finite")
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), float(config["gradient_clip"]))
    optimizer.step()
    with torch.no_grad():
        validation_loss = torch.mean((model(batch) - batch["target"]) ** 2)
    validation_value = float(validation_loss.detach().cpu())
    if not math.isfinite(validation_value):
        raise RuntimeError("dry-run validation loss is not finite")
    scheduler.step(validation_value)

    early_state = {
        "epochs_without_improvement": 0,
        "completed_epochs": 1,
        "stopped_early": False,
    }
    resolved_config = {
        **config,
        "resolved": {
            "dry_run": True,
            "checkpoint_format_version": 2,
        },
    }
    with tempfile.TemporaryDirectory(prefix="original11-value-dry-run-") as temporary:
        root = Path(temporary)
        checkpoint = root / "checkpoint_last.pt"
        exported = root / "value_candidate.txt"
        save_checkpoint(
            checkpoint,
            model,
            optimizer,
            scheduler,
            0,
            validation_value,
            resolved_config,
            early_state,
            "dry-run-lineage",
            "last",
        )
        payload = torch.load(checkpoint, map_location=device, weights_only=False)
        if int(payload.get("format_version", -1)) != 2:
            raise RuntimeError("dry-run checkpoint format is not version 2")
        if payload.get("checkpoint_role") != "last":
            raise RuntimeError("dry-run checkpoint role was not preserved")
        if payload.get("lineage_id") != "dry-run-lineage":
            raise RuntimeError("dry-run checkpoint lineage was not preserved")
        if dict(payload.get("early_stop_state", {})) != early_state:
            raise RuntimeError("dry-run early-stop state was not preserved")
        resumed_model = JavaCompatibleEvaluator(dtype)
        resumed_model.load_state_dict(payload["model_state"])
        resumed_optimizer = torch.optim.AdamW(
            resumed_model.parameters(),
            lr=float(config["learning_rate"]),
            weight_decay=float(config["weight_decay"]),
        )
        resumed_optimizer.load_state_dict(payload["optimizer_state"])
        resumed_scheduler = build_scheduler(resumed_optimizer, training_config)
        resumed_scheduler.load_state_dict(payload["scheduler_state"])
        restore_rng_state(payload["rng_state"])
        with torch.no_grad():
            saved_prediction = model(batch)
            resumed_prediction = resumed_model(batch)
        if not bool(torch.all(torch.isfinite(resumed_prediction))):
            raise RuntimeError("dry-run resumed model produced non-finite values")
        if not bool(torch.equal(saved_prediction, resumed_prediction)):
            raise RuntimeError("dry-run resumed model differs from saved model")
        export_java_parameters(resumed_model, exported)
        exported_values = read_parameter_values(exported)
        expected_count = int(config["export_parameter_count"])
        if expected_count != EXPECTED_PARAMETER_COUNT or len(exported_values) != expected_count:
            raise RuntimeError("dry-run Java parameter export count mismatch")

        parity = config["parity"]
        parity_command = [
            sys.executable,
            str(PROJECT_ROOT / "tests" / "compare_java_eval.py"),
            "--positions", str(int(parity["positions"])),
            "--seed", str(int(parity["seed"])),
            "--tolerance", str(float(parity["tolerance"])),
            "--param", str(exported),
            "--ai-source", str(resolve(config["ai_source"])),
            "--compile-timeout", str(float(parity["timeout_seconds"])),
            "--query-timeout", str(float(parity["timeout_seconds"])),
        ]
        completed = subprocess.run(
            parity_command,
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "dry-run Java/Python parity failed\n"
                f"stdout:\n{completed.stdout[-4000:]}\n"
                f"stderr:\n{completed.stderr[-4000:]}"
            )
        return {
            "schema": "original_11_value_dry_run_result_v1",
            "pass": True,
            "training_eligible": False,
            "fixture_file": str(resolve(config["fixture_file"])),
            "fixture_records": int(config["fixture_records"]),
            "train_batches": 1,
            "validation_batches": 1,
            "training_loss": float(loss.detach().cpu()),
            "validation_loss": validation_value,
            "checkpoint_save_resume": "passed",
            "checkpoint_format_version": 2,
            "scheduler": config["scheduler"],
            "early_stopping": early_settings,
            "export_parameter_count": len(exported_values),
            "java_python_parity_positions": int(parity["positions"]),
            "java_python_parity": "passed",
            "persistent_outputs": [],
        }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        print(json.dumps(run(load_object(resolve(args.config))), ensure_ascii=False, indent=2))
        return 0
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
