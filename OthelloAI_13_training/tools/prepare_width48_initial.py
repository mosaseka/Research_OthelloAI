"""Expand a completed width-16 evaluator checkpoint to width 48.

The transformation is function preserving (Net2Wider-style): every hidden
unit is copied three times and every outgoing weight is divided by three.
Small deterministic zero-sum perturbations are then added to outgoing
weights.  They leave the initial function unchanged because the three
replicas initially have identical activations, while ensuring that their
gradients are not identical after the first optimizer step.  The resulting
parameter file is a fresh width-48 initialization; optimizer, scheduler, and
early-stopping state are deliberately not carried over.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

try:
    import torch
    import torch.nn.functional as functional
except ImportError as error:  # pragma: no cover - local environment dependent
    raise ImportError("PyTorch is required to widen the evaluator") from error


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_ROOT = PROJECT_ROOT / "training"
sys.path.insert(0, str(TRAINING_ROOT))

from wide_evaluator_model import (  # noqa: E402
    JavaCompatibleEvaluator,
    export_java_parameters,
)
from wide_java_eval import (  # noqa: E402
    EXPECTED_PARAMETER_COUNT,
    N_PHASES,
    PATTERN_SIZES,
)


SOURCE_WIDTH = 16
TARGET_WIDTH = 48
REPLICATION = TARGET_WIDTH // SOURCE_WIDTH
SYMMETRY_BREAK_SCALE = 1.0e-3
SYMMETRY_BREAK_FLOOR = 1.0e-2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_tensor(
    state: dict[str, Any],
    key: str,
    shape: tuple[int, ...],
) -> torch.Tensor:
    value = state.get(key)
    if not isinstance(value, torch.Tensor):
        raise ValueError(f"checkpoint model_state has no tensor {key!r}")
    if tuple(value.shape) != shape:
        raise ValueError(
            f"checkpoint tensor {key!r} has shape {tuple(value.shape)}, "
            f"expected {shape}"
        )
    if not bool(torch.all(torch.isfinite(value))):
        raise ValueError(f"checkpoint tensor {key!r} contains NaN or infinity")
    return value.detach().cpu()


def widen_pattern(
    model: JavaCompatibleEvaluator,
    state: dict[str, Any],
    phase: int,
    pattern_index: int,
    pattern_size: int,
) -> tuple[float, float, float]:
    prefix = f"patterns.{phase}.{pattern_index}"
    source_w0 = require_tensor(
        state, f"{prefix}.dense0.weight", (SOURCE_WIDTH, pattern_size * 2)
    )
    source_b0 = require_tensor(
        state, f"{prefix}.dense0.bias", (SOURCE_WIDTH,)
    )
    source_w1 = require_tensor(
        state, f"{prefix}.dense1.weight", (SOURCE_WIDTH, SOURCE_WIDTH)
    )
    source_b1 = require_tensor(
        state, f"{prefix}.dense1.bias", (SOURCE_WIDTH,)
    )
    source_w2 = require_tensor(
        state, f"{prefix}.dense2.weight", (1, SOURCE_WIDTH)
    )
    source_b2 = require_tensor(state, f"{prefix}.dense2.bias", (1,))

    target = model.patterns[phase][pattern_index]
    dtype = target.dense0.weight.dtype
    with torch.no_grad():
        target.dense0.weight.copy_(
            source_w0.repeat_interleave(REPLICATION, dim=0).to(dtype=dtype)
        )
        target.dense0.bias.copy_(
            source_b0.repeat_interleave(REPLICATION).to(dtype=dtype)
        )
        widened_w1 = (
            source_w1
            .repeat_interleave(REPLICATION, dim=0)
            .repeat_interleave(REPLICATION, dim=1)
            / REPLICATION
        )
        base_w1 = widened_w1.clone()
        offset_pattern = torch.tensor(
            (-1.0, 0.0, 1.0), dtype=widened_w1.dtype
        )
        for source_row in range(SOURCE_WIDTH):
            for row_replica in range(REPLICATION):
                target_row = source_row * REPLICATION + row_replica
                for source_column in range(SOURCE_WIDTH):
                    start = source_column * REPLICATION
                    base = float(widened_w1[target_row, start].item())
                    delta = (
                        SYMMETRY_BREAK_SCALE
                        * max(abs(base), SYMMETRY_BREAK_FLOOR)
                    )
                    rotation = (
                        phase
                        + pattern_index
                        + source_row
                        + source_column
                        + row_replica
                    ) % REPLICATION
                    widened_w1[target_row, start:start + REPLICATION] += (
                        torch.roll(offset_pattern, shifts=rotation) * delta
                    )
        target.dense1.weight.copy_(widened_w1.to(dtype=dtype))
        target.dense1.bias.copy_(
            source_b1.repeat_interleave(REPLICATION).to(dtype=dtype)
        )
        widened_w2 = (
            source_w2.repeat_interleave(REPLICATION, dim=1)
            / REPLICATION
        )
        base_w2 = widened_w2.clone()
        for source_column in range(SOURCE_WIDTH):
            start = source_column * REPLICATION
            base = float(widened_w2[0, start].item())
            delta = (
                SYMMETRY_BREAK_SCALE
                * max(abs(base), SYMMETRY_BREAK_FLOOR)
            )
            rotation = (
                phase + pattern_index + source_column
            ) % REPLICATION
            widened_w2[0, start:start + REPLICATION] += (
                torch.roll(offset_pattern, shifts=rotation) * delta
            )
        target.dense2.weight.copy_(widened_w2.to(dtype=dtype))
        target.dense2.bias.copy_(source_b2.to(dtype=dtype))

    expected_w1_sums = source_w1.repeat_interleave(REPLICATION, dim=0)
    actual_w1_sums = widened_w1.reshape(
        TARGET_WIDTH, SOURCE_WIDTH, REPLICATION
    ).sum(dim=2)
    expected_w2_sums = source_w2
    actual_w2_sums = widened_w2.reshape(
        1, SOURCE_WIDTH, REPLICATION
    ).sum(dim=2)
    max_group_sum_error = max(
        float(torch.max(torch.abs(actual_w1_sums - expected_w1_sums)).item()),
        float(torch.max(torch.abs(actual_w2_sums - expected_w2_sums)).item()),
    )
    max_perturbation = max(
        float(torch.max(torch.abs(widened_w1 - base_w1)).item()),
        float(torch.max(torch.abs(widened_w2 - base_w2)).item()),
    )

    # Deterministic numeric proof on every one-hot ternary input when the
    # pattern is small, and on a fixed sample for 10-cell patterns.
    generator = torch.Generator(device="cpu").manual_seed(
        13_000 + phase * 101 + pattern_index
    )
    sample_count = min(4096, 3 ** pattern_size)
    digits = torch.randint(
        0, 3, (sample_count, pattern_size), generator=generator
    )
    inputs = torch.cat((digits == 0, digits == 1), dim=1).to(dtype=source_w0.dtype)
    old_h0 = functional.leaky_relu(
        functional.linear(inputs, source_w0, source_b0), negative_slope=0.01
    )
    old_h1 = functional.leaky_relu(
        functional.linear(old_h0, source_w1, source_b1), negative_slope=0.01
    )
    old_out = functional.leaky_relu(
        functional.linear(old_h1, source_w2, source_b2), negative_slope=0.01
    )
    with torch.no_grad():
        new_h0 = functional.leaky_relu(target.dense0(inputs), negative_slope=0.01)
        new_h1 = functional.leaky_relu(target.dense1(new_h0), negative_slope=0.01)
        new_out = functional.leaky_relu(target.dense2(new_h1), negative_slope=0.01)
    max_function_error = float(
        torch.max(torch.abs(old_out - new_out)).item()
    )
    return max_function_error, max_group_sum_error, max_perturbation


def copy_unchanged_parameters(
    model: JavaCompatibleEvaluator,
    state: dict[str, Any],
) -> None:
    target_state = model.state_dict()
    pattern_prefix = "patterns."
    with torch.no_grad():
        for key, target in target_state.items():
            if key.startswith(pattern_prefix):
                continue
            source = state.get(key)
            if not isinstance(source, torch.Tensor):
                raise ValueError(f"checkpoint model_state has no tensor {key!r}")
            if tuple(source.shape) != tuple(target.shape):
                raise ValueError(
                    f"checkpoint tensor {key!r} has shape {tuple(source.shape)}, "
                    f"expected unchanged shape {tuple(target.shape)}"
                )
            if not bool(torch.all(torch.isfinite(source))):
                raise ValueError(f"checkpoint tensor {key!r} is non-finite")
            target.copy_(source.detach().cpu().to(dtype=target.dtype))
    model.load_state_dict(target_state)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint",
        type=Path,
        required=True,
        help="completed width-16 checkpoint_last.pt",
    )
    parser.add_argument(
        "--best-checkpoint",
        type=Path,
        help="matching checkpoint_best.pt (default: beside checkpoint_last.pt)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checkpoint_path = args.checkpoint.expanduser().resolve()
    best_checkpoint_path = (
        args.best_checkpoint.expanduser().resolve()
        if args.best_checkpoint is not None
        else checkpoint_path.with_name("checkpoint_best.pt")
    )
    output_path = args.output.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"checkpoint not found: {checkpoint_path}")
    if checkpoint_path.name != "checkpoint_last.pt":
        raise ValueError("--checkpoint must name checkpoint_last.pt")
    if not best_checkpoint_path.is_file():
        raise FileNotFoundError(
            f"matching best checkpoint not found: {best_checkpoint_path}"
        )
    for destination in (output_path, manifest_path):
        if destination.exists() and not args.overwrite:
            raise FileExistsError(
                f"refusing to overwrite existing output: {destination}"
            )

    last_checkpoint = torch.load(
        checkpoint_path, map_location="cpu", weights_only=False
    )
    best_checkpoint = torch.load(
        best_checkpoint_path, map_location="cpu", weights_only=False
    )
    if not isinstance(last_checkpoint, dict) or not isinstance(best_checkpoint, dict):
        raise ValueError("checkpoint roots must be dictionaries")
    if last_checkpoint.get("lineage_id") != best_checkpoint.get("lineage_id"):
        raise ValueError("last and best checkpoints have different lineage_id")
    completed_epoch = int(last_checkpoint.get("epoch", -1))
    if completed_epoch < 1:
        raise ValueError(
            "width-48 preparation requires at least two completed epochs "
            "(checkpoint epoch must be at least 1)"
        )
    if int(best_checkpoint.get("epoch", -1)) > completed_epoch:
        raise ValueError("best checkpoint epoch is newer than checkpoint_last")
    state = best_checkpoint.get("model_state")
    if not isinstance(state, dict):
        raise ValueError("checkpoint has no model_state dictionary")

    model = JavaCompatibleEvaluator(dtype=torch.float32)
    copy_unchanged_parameters(model, state)
    max_abs_error = 0.0
    max_group_sum_error = 0.0
    max_perturbation = 0.0
    for phase in range(N_PHASES):
        for pattern_index, pattern_size in enumerate(PATTERN_SIZES):
            function_error, group_sum_error, perturbation = widen_pattern(
                model, state, phase, pattern_index, pattern_size
            )
            max_abs_error = max(max_abs_error, function_error)
            max_group_sum_error = max(
                max_group_sum_error, group_sum_error
            )
            max_perturbation = max(max_perturbation, perturbation)
    if not math.isfinite(max_abs_error) or max_abs_error > 2.0e-5:
        raise RuntimeError(
            "function-preserving widening verification failed: "
            f"max_abs_error={max_abs_error:.9g}"
        )
    if (
        not math.isfinite(max_group_sum_error)
        or max_group_sum_error > 2.0e-6
    ):
        raise RuntimeError(
            "zero-sum widening verification failed: "
            f"max_group_sum_error={max_group_sum_error:.9g}"
        )
    if not math.isfinite(max_perturbation) or max_perturbation <= 0.0:
        raise RuntimeError(
            "symmetry breaking was not applied to the widened model"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    export_java_parameters(model, output_path, overwrite=args.overwrite)
    line_count = sum(1 for _ in output_path.open("r", encoding="utf-8"))
    if line_count != EXPECTED_PARAMETER_COUNT:
        raise AssertionError(
            f"wide export has {line_count} lines, "
            f"expected {EXPECTED_PARAMETER_COUNT}"
        )

    manifest = {
        "schema": "othello-width48-initialization-v2",
        "source_checkpoint_last": str(checkpoint_path),
        "source_checkpoint_last_sha256": sha256(checkpoint_path),
        "source_completed_epoch": completed_epoch,
        "source_checkpoint_best": str(best_checkpoint_path),
        "source_checkpoint_best_sha256": sha256(best_checkpoint_path),
        "source_best_epoch": best_checkpoint.get("epoch"),
        "source_lineage_id": last_checkpoint.get("lineage_id"),
        "source_width": SOURCE_WIDTH,
        "target_width": TARGET_WIDTH,
        "replication": REPLICATION,
        "function_preserving": True,
        "max_abs_error": max_abs_error,
        "symmetry_broken": True,
        "symmetry_break_method": "deterministic-zero-sum-outgoing-v1",
        "symmetry_break_scale": SYMMETRY_BREAK_SCALE,
        "symmetry_break_floor": SYMMETRY_BREAK_FLOOR,
        "max_group_sum_error": max_group_sum_error,
        "max_perturbation": max_perturbation,
        "output": str(output_path),
        "output_sha256": sha256(output_path),
        "parameter_count": line_count,
        "optimizer_state_carried": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
