#!/usr/bin/env python3
"""Gate an original_10 exact-mobility evaluator candidate before A/B play.

The validator is intentionally read-only with respect to model and data files.
Its JSON report is created with exclusive-create semantics and is never
overwritten.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, BinaryIO, Iterator, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "training"))

from java_eval import (  # noqa: E402
    EXPECTED_PARAMETER_COUNT,
    Evaluator,
    FEATURE_SCHEMA,
    encode_board,
)


EXPECTED_FEATURE_SCHEMA = "exact-mobility-v1"
EXPECTED_BASELINE_FEATURE_SCHEMA = "legacy-v1"
PREPARED_MANIFEST_SCHEMA_VERSION = 2
PREPARED_MANIFEST_STATUS = "verified-full"
PREPARED_SPLIT_ALGORITHM = "sha256-canonical-d4-board-v1"
PREPARED_SPLIT_UNIT = "canonical_d4_relative_board"
PHASES = (0, 1, 2, 3)
_PARAMETER_HASH = re.compile(r"[0-9a-fA-F]{64}")
_PREPARED_ROW = re.compile(
    rb"[XO-]{64} (?:0|-[1-9][0-9]*|[1-9][0-9]*)\n"
)


@dataclass(frozen=True)
class Position:
    board: str
    target_disc: float
    phase: int


@dataclass
class SampleAggregate:
    priority: int
    order: int
    board: str
    target_sum: float
    observations: int
    phase: int

    def position(self) -> Position:
        return Position(
            self.board,
            self.target_sum / self.observations,
            self.phase,
        )


@dataclass(frozen=True)
class Shard:
    path: Path
    rows: int
    size_bytes: int
    sha256: str


class CuiProgress:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def step(self, current: int, total: int, message: str) -> None:
        if not self.quiet:
            print(
                f"CUI [{current}/{total}] {message}",
                file=sys.stderr,
                flush=True,
            )

    def scan(
        self,
        records: int,
        phase_counts: Counter[int],
        selected_counts: dict[int, int],
    ) -> None:
        if not self.quiet:
            print(
                "CUI [scan] "
                f"records={records:,} "
                f"phases={dict(sorted(phase_counts.items()))} "
                f"selected={selected_counts}",
                file=sys.stderr,
                flush=True,
            )


def resolve_project_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parameter_check(
    path: Path,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    raw_lines = resolved.read_text(encoding="utf-8").splitlines()
    bad_lines: list[int] = []
    for line_number, raw in enumerate(raw_lines, 1):
        if not raw.strip():
            bad_lines.append(line_number)
            continue
        try:
            value = float(raw)
        except ValueError:
            bad_lines.append(line_number)
            continue
        if not math.isfinite(value):
            bad_lines.append(line_number)

    actual_sha256 = file_sha256(resolved)
    normalized_expected = (
        expected_sha256.lower() if expected_sha256 is not None else None
    )
    if (
        normalized_expected is not None
        and _PARAMETER_HASH.fullmatch(normalized_expected) is None
    ):
        raise ValueError(
            "--expect-candidate-sha256 must contain 64 hexadecimal digits"
        )
    hash_matches = (
        normalized_expected is None
        or actual_sha256 == normalized_expected
    )
    passed = (
        len(raw_lines) == EXPECTED_PARAMETER_COUNT
        and not bad_lines
        and hash_matches
    )
    return {
        "path": str(resolved),
        "sha256": actual_sha256,
        "expected_sha256": normalized_expected,
        "hash_matches": hash_matches,
        "count": len(raw_lines),
        "expected_count": EXPECTED_PARAMETER_COUNT,
        "all_finite": not bad_lines,
        "bad_lines": bad_lines[:16],
        "pass": passed,
    }


def rotate90(board: str) -> str:
    return "".join(
        board[(7 - x) * 8 + y]
        for y in range(8)
        for x in range(8)
    )


def mirror(board: str) -> str:
    return "".join(
        board[y * 8 + 7 - x]
        for y in range(8)
        for x in range(8)
    )


def d4_variants(board: str) -> tuple[str, ...]:
    result: list[str] = []
    rotated = board
    for _ in range(4):
        result.extend((rotated, mirror(rotated)))
        rotated = rotate90(rotated)
    return tuple(result)


def canonical_d4(board: str) -> str:
    return min(d4_variants(board))


def phase_for_board(board: str) -> int:
    stones = 64 - board.count("-")
    if not 4 <= stones <= 64:
        raise ValueError(f"invalid occupied-cell count: {stones}")
    return max(0, min(3, (stones - 4) // 10 - 2))


def absolute_board(relative: str, player: int = 0) -> str:
    if len(relative) != 64 or set(relative) - {"X", "O", "-"}:
        raise ValueError("relative board must contain 64 X/O/- cells")
    if player == 0:
        colors = {"X": "0", "O": "1", "-": "."}
    elif player == 1:
        colors = {"X": "1", "O": "0", "-": "."}
    else:
        raise ValueError(f"player must be 0 or 1, got {player}")
    return relative.translate(str.maketrans(colors))


def sample_priority(board: str, seed: int) -> int:
    digest = hashlib.blake2b(digest_size=16, person=b"oth-gate-v1")
    digest.update(str(seed).encode("ascii"))
    digest.update(b"\0")
    digest.update(canonical_d4(board).encode("ascii"))
    return int.from_bytes(digest.digest(), "big")


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def load_prepared_shards(
    manifest_path: Path,
    split: str,
) -> tuple[list[Shard], dict[int, int], dict[str, Any]]:
    resolved_manifest = manifest_path.expanduser().resolve()
    manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("prepared manifest root must be an object")
    if manifest.get("schema_version") != PREPARED_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            "prepared manifest schema mismatch: "
            f"{manifest.get('schema_version')!r}"
        )
    if manifest.get("status") != PREPARED_MANIFEST_STATUS:
        raise ValueError(
            "prepared manifest must have status "
            f"{PREPARED_MANIFEST_STATUS!r}"
        )
    split_contract = manifest.get("split")
    if not isinstance(split_contract, dict):
        raise ValueError("prepared manifest has no split contract")
    if (
        split_contract.get("algorithm") != PREPARED_SPLIT_ALGORITHM
        or split_contract.get("unit") != PREPARED_SPLIT_UNIT
    ):
        raise ValueError(
            "prepared manifest does not use the canonical-D4 split contract"
        )
    if split not in {"train", "val", "test"}:
        raise ValueError(f"unsupported prepared split: {split!r}")

    output_root = Path(str(manifest.get("output_root", ""))).resolve()
    sources = manifest.get("sources")
    counts = manifest.get("counts")
    if not output_root.is_dir():
        raise FileNotFoundError(
            f"prepared output_root does not exist: {output_root}"
        )
    if not isinstance(sources, list) or not isinstance(counts, dict):
        raise ValueError("prepared manifest lacks sources/counts")

    shards: list[Shard] = []
    expected_rows = 0
    for source_number, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            raise ValueError(
                f"prepared source {source_number} is not an object"
            )
        outputs = source.get("outputs")
        if not isinstance(outputs, dict) or split not in outputs:
            raise ValueError(
                f"prepared source {source_number} has no {split} output"
            )
        info = outputs[split]
        if not isinstance(info, dict):
            raise ValueError(
                f"prepared source {source_number} has malformed output"
            )
        relative = info.get("path")
        rows = info.get("rows")
        size_bytes = info.get("size_bytes")
        digest = info.get("sha256")
        if (
            not isinstance(relative, str)
            or not isinstance(rows, int)
            or rows < 0
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError(
                f"prepared source {source_number} has invalid metadata"
            )
        path = (output_root / relative).resolve()
        if not _inside(output_root, path):
            raise ValueError(
                f"prepared shard escapes output_root: {relative}"
            )
        shards.append(Shard(path, rows, size_bytes, digest))
        expected_rows += rows

    by_split = counts.get("by_split")
    by_split_phase = counts.get("by_split_and_phase")
    if (
        not isinstance(by_split, dict)
        or int(by_split.get(split, -1)) != expected_rows
    ):
        raise ValueError(
            f"prepared {split} shard rows do not match counts.by_split"
        )
    if (
        not isinstance(by_split_phase, dict)
        or not isinstance(by_split_phase.get(split), dict)
    ):
        raise ValueError(
            f"prepared manifest has no {split} phase populations"
        )
    phase_weights = {
        phase: int(by_split_phase[split].get(str(phase), -1))
        for phase in PHASES
    }
    if (
        any(weight <= 0 for weight in phase_weights.values())
        or sum(phase_weights.values()) != expected_rows
    ):
        raise ValueError(
            f"prepared {split} phase populations are inconsistent"
        )

    missing = [str(shard.path) for shard in shards if not shard.path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} prepared shards are missing; first={missing[0]}"
        )
    duplicate_paths = len({shard.path for shard in shards}) != len(shards)
    if duplicate_paths:
        raise ValueError("prepared manifest repeats a shard path")

    metadata = {
        "manifest_path": str(resolved_manifest),
        "manifest_sha256": file_sha256(resolved_manifest),
        "manifest_status": manifest["status"],
        "manifest_schema_version": manifest["schema_version"],
        "split": split,
        "split_contract": split_contract,
        "output_root": str(output_root),
        "shard_count": len(shards),
        "expected_records": expected_rows,
        "population_by_phase": {
            str(phase): phase_weights[phase] for phase in PHASES
        },
    }
    return shards, phase_weights, metadata


def parse_prepared_row(
    raw: bytes,
    path: Path,
    line_number: int,
) -> Position:
    if _PREPARED_ROW.fullmatch(raw) is None:
        raise ValueError(
            f"invalid prepared row at {path}:{line_number}"
        )
    board = raw[:64].decode("ascii")
    target = int(raw[65:-1])
    if not -64 <= target <= 64:
        raise ValueError(
            f"prepared target outside [-64, 64] at {path}:{line_number}"
        )
    return Position(board, float(target), phase_for_board(board))


def _sample_limit(raw: int | dict[str, int], phase: int) -> int:
    value = (
        int(raw[str(phase)])
        if isinstance(raw, dict)
        else int(raw)
    )
    if value <= 0:
        raise ValueError("heldout.samples_per_phase must be positive")
    return value


def _scan_shard(
    source: BinaryIO,
    shard: Shard,
) -> Iterator[tuple[bytes, int]]:
    for line_number, raw in enumerate(source, 1):
        yield raw, line_number


def select_samples(
    shards: Sequence[Shard],
    config: dict[str, Any],
    progress: CuiProgress,
) -> tuple[dict[int, list[Position]], dict[str, Any]]:
    limits = {
        phase: _sample_limit(config["samples_per_phase"], phase)
        for phase in PHASES
    }
    heaps: dict[int, list[tuple[int, int, str]]] = {
        phase: [] for phase in PHASES
    }
    selected: dict[int, dict[str, SampleAggregate]] = {
        phase: {} for phase in PHASES
    }
    scanned_by_phase: Counter[int] = Counter()
    seed = int(config["sample_seed"])
    report_every = int(config.get("progress_every_records", 250_000))
    if report_every <= 0:
        raise ValueError(
            "heldout.progress_every_records must be positive"
        )
    records = 0
    next_report = report_every
    total_bytes = 0

    for shard_number, shard in enumerate(shards, 1):
        digest = hashlib.sha256()
        rows = 0
        size_bytes = 0
        with shard.path.open("rb") as source:
            for raw, line_number in _scan_shard(source, shard):
                digest.update(raw)
                size_bytes += len(raw)
                rows += 1
                records += 1
                record = parse_prepared_row(raw, shard.path, line_number)
                scanned_by_phase[record.phase] += 1
                canonical = canonical_d4(record.board)
                aggregate = selected[record.phase].get(canonical)
                if aggregate is not None:
                    aggregate.target_sum += record.target_disc
                    aggregate.observations += 1
                    if records >= next_report:
                        progress.scan(
                            records,
                            scanned_by_phase,
                            {
                                phase: len(heaps[phase])
                                for phase in PHASES
                            },
                        )
                        next_report += report_every
                    continue

                priority = sample_priority(canonical, seed)
                item = (-priority, -records, canonical)
                heap = heaps[record.phase]
                limit = limits[record.phase]
                new_aggregate = SampleAggregate(
                    priority,
                    records,
                    canonical,
                    record.target_disc,
                    1,
                    record.phase,
                )
                if len(heap) < limit:
                    heapq.heappush(heap, item)
                    selected[record.phase][canonical] = new_aggregate
                elif priority < -heap[0][0]:
                    evicted = heapq.heapreplace(heap, item)
                    del selected[record.phase][evicted[2]]
                    selected[record.phase][canonical] = new_aggregate

                if records >= next_report:
                    progress.scan(
                        records,
                        scanned_by_phase,
                        {
                            phase: len(heaps[phase])
                            for phase in PHASES
                        },
                    )
                    next_report += report_every
        total_bytes += size_bytes
        actual = (rows, size_bytes, digest.hexdigest())
        expected = (shard.rows, shard.size_bytes, shard.sha256)
        if actual != expected:
            raise ValueError(
                "prepared shard integrity mismatch: "
                f"{shard.path}; expected={expected}, actual={actual}"
            )

        if shard_number == len(shards) and records < next_report:
            progress.scan(
                records,
                scanned_by_phase,
                {phase: len(heaps[phase]) for phase in PHASES},
            )

    missing = {
        phase: {
            "required": limits[phase],
            "selected": len(heaps[phase]),
        }
        for phase in PHASES
        if len(heaps[phase]) != limits[phase]
    }
    if missing:
        raise ValueError(
            f"insufficient deterministic heldout samples: {missing}"
        )

    result: dict[int, list[Position]] = {}
    sample_digest = hashlib.sha256()
    for phase in PHASES:
        items = sorted(
            heaps[phase],
            key=lambda item: (-item[0], -item[1]),
        )
        result[phase] = [
            selected[phase][item[2]].position() for item in items
        ]
        for record in result[phase]:
            sample_digest.update(
                (
                    f"{phase}\t{record.board}\t"
                    f"{record.target_disc:.17g}\n"
                ).encode("ascii")
            )
    return result, {
        "records_scanned": records,
        "records_by_phase": {
            str(phase): scanned_by_phase[phase] for phase in PHASES
        },
        "selected_by_phase": {
            str(phase): len(result[phase]) for phase in PHASES
        },
        "sampling_unit": "unique_canonical_d4_board",
        "selected_observations_by_phase": {
            str(phase): sum(
                aggregate.observations
                for aggregate in selected[phase].values()
            )
            for phase in PHASES
        },
        "duplicate_targets": (
            "mean target over all encountered occurrences while a selected "
            "canonical board remains in the deterministic bottom-k heap"
        ),
        "sample_seed": seed,
        "sample_sha256": sample_digest.hexdigest(),
        "bytes_verified": total_bytes,
        "all_shard_rows_sizes_and_hashes_verified": True,
    }


def _rmse_summary(
    squared_error: dict[int, float],
    counts: Counter[int],
    phase_weights: dict[int, int],
) -> dict[str, Any]:
    phase_mse = {
        phase: squared_error[phase] / counts[phase]
        for phase in PHASES
    }
    total_population = sum(phase_weights.values())
    weighted_mse = sum(
        phase_mse[phase] * phase_weights[phase]
        for phase in PHASES
    ) / total_population
    return {
        "count": sum(counts.values()),
        "rmse_disc": math.sqrt(weighted_mse),
        "aggregation": "prepared_split_population_weighted",
        "phases": {
            str(phase): {
                "count": counts[phase],
                "rmse_disc": math.sqrt(phase_mse[phase]),
                "population_count": phase_weights[phase],
                "population_weight": (
                    phase_weights[phase] / total_population
                ),
            }
            for phase in PHASES
        },
    }


def evaluate_rmse(
    baseline: Evaluator,
    candidate: Evaluator,
    samples: dict[int, list[Position]],
    phase_weights: dict[int, int],
    progress: CuiProgress,
) -> dict[str, Any]:
    baseline_squares = {phase: 0.0 for phase in PHASES}
    candidate_squares = {phase: 0.0 for phase in PHASES}
    counts: Counter[int] = Counter()

    for phase in PHASES:
        for record in samples[phase]:
            for player in (0, 1):
                board = absolute_board(record.board, player)
                baseline_prediction = (
                    baseline.evaluate_encoded(
                        encode_board(board, player)
                    ).raw_value
                    * 64.0
                )
                candidate_prediction = (
                    candidate.evaluate_details(board, player).raw_value
                    * 64.0
                )
                if (
                    not math.isfinite(baseline_prediction)
                    or not math.isfinite(candidate_prediction)
                ):
                    raise ValueError(
                        "an evaluator produced a non-finite heldout prediction"
                    )
                baseline_squares[phase] += (
                    baseline_prediction - record.target_disc
                ) ** 2
                candidate_squares[phase] += (
                    candidate_prediction - record.target_disc
                ) ** 2
                counts[phase] += 1
        if not progress.quiet:
            print(
                f"CUI [RMSE] phase={phase} "
                f"positions={counts[phase]:,}",
                file=sys.stderr,
                flush=True,
            )
    return {
        "color_orientations_per_position": 2,
        "baseline_feature_schema": EXPECTED_BASELINE_FEATURE_SCHEMA,
        "candidate_feature_schema": EXPECTED_FEATURE_SCHEMA,
        "baseline": _rmse_summary(
            baseline_squares, counts, phase_weights,
        ),
        "candidate": _rmse_summary(
            candidate_squares, counts, phase_weights,
        ),
    }


def rmse_gate(
    metrics: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    baseline = float(metrics["baseline"]["rmse_disc"])
    candidate = float(metrics["candidate"]["rmse_disc"])
    absolute = baseline - candidate
    relative = absolute / baseline if baseline > 0.0 else None
    minimum_absolute = float(config["minimum_absolute_disc"])
    minimum_relative = float(config["minimum_relative"])
    absolute_pass = (
        absolute >= minimum_absolute
        or math.isclose(
            absolute,
            minimum_absolute,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    )
    relative_pass = (
        relative is not None
        and (
            relative >= minimum_relative
            or math.isclose(
                relative,
                minimum_relative,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        )
    )
    phase = str(int(config.get("endgame_phase", 3)))
    baseline_end = float(
        metrics["baseline"]["phases"][phase]["rmse_disc"]
    )
    candidate_end = float(
        metrics["candidate"]["phases"][phase]["rmse_disc"]
    )
    endgame_tolerance = float(
        config.get("endgame_tolerance_disc", 0.0)
    )
    endgame_pass = (
        candidate_end <= baseline_end + endgame_tolerance
        or math.isclose(
            candidate_end,
            baseline_end + endgame_tolerance,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    )
    return {
        "pass": (absolute_pass or relative_pass) and endgame_pass,
        "improvement_pass": absolute_pass or relative_pass,
        "absolute_improvement_pass": absolute_pass,
        "relative_improvement_pass": relative_pass,
        "endgame_nonworsening_pass": endgame_pass,
        "absolute_improvement_disc": absolute,
        "relative_improvement": relative,
        "minimum_absolute_disc": minimum_absolute,
        "minimum_relative": minimum_relative,
        "endgame_phase": int(phase),
        "endgame_change_disc": candidate_end - baseline_end,
        "endgame_tolerance_disc": endgame_tolerance,
    }


def _span_summary(
    raw_spans: Sequence[float],
    integer_spans: Sequence[int],
) -> dict[str, Any]:
    return {
        "positions": len(raw_spans),
        "maximum_span_disc": max(raw_spans) if raw_spans else None,
        "mean_span_disc": (
            sum(raw_spans) / len(raw_spans)
            if raw_spans else None
        ),
        "rms_span_disc": (
            math.sqrt(
                sum(value * value for value in raw_spans)
                / len(raw_spans)
            )
            if raw_spans else None
        ),
        "maximum_span_java_units": (
            max(integer_spans) if integer_spans else None
        ),
        "mean_span_java_units": (
            sum(integer_spans) / len(integer_spans)
            if integer_spans else None
        ),
    }


def direction_stats(
    evaluator: Evaluator,
    samples: dict[int, list[Position]],
    per_phase: int,
    label: str,
    feature_schema: str,
    progress: CuiProgress,
) -> dict[str, Any]:
    all_raw: list[float] = []
    all_integer: list[int] = []
    phases: dict[str, Any] = {}

    for phase in PHASES:
        raw_spans: list[float] = []
        integer_spans: list[int] = []
        for record in samples[phase][:per_phase]:
            for player in (0, 1):
                details = []
                for variant in d4_variants(record.board):
                    board = absolute_board(variant, player)
                    if feature_schema == EXPECTED_BASELINE_FEATURE_SCHEMA:
                        details.append(
                            evaluator.evaluate_encoded(
                                encode_board(board, player)
                            )
                        )
                    elif feature_schema == EXPECTED_FEATURE_SCHEMA:
                        details.append(
                            evaluator.evaluate_details(board, player)
                        )
                    else:
                        raise ValueError(
                            f"unsupported evaluator feature schema: "
                            f"{feature_schema}"
                        )
                raw_values = [item.raw_value * 64.0 for item in details]
                integer_values = [item.value for item in details]
                if any(not math.isfinite(value) for value in raw_values):
                    raise ValueError(
                        f"{label} produced a non-finite D4 prediction"
                    )
                raw_spans.append(max(raw_values) - min(raw_values))
                integer_spans.append(
                    max(integer_values) - min(integer_values)
                )
        phases[str(phase)] = _span_summary(
            raw_spans, integer_spans,
        )
        all_raw.extend(raw_spans)
        all_integer.extend(integer_spans)
        if not progress.quiet:
            print(
                f"CUI [D4] evaluator={label} phase={phase} "
                f"positions={len(raw_spans):,}",
                file=sys.stderr,
                flush=True,
            )
    result = _span_summary(all_raw, all_integer)
    result["phases"] = phases
    return result


def direction_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    candidate_max = float(candidate["maximum_span_disc"])
    candidate_mean = float(candidate["mean_span_disc"])
    baseline_max = float(baseline["maximum_span_disc"])
    baseline_mean = float(baseline["mean_span_disc"])
    max_limit = config.get("maximum_candidate_span_disc")
    mean_limit = config.get("maximum_candidate_mean_span_disc")
    within_max = (
        max_limit is None or candidate_max <= float(max_limit)
    )
    within_mean = (
        mean_limit is None or candidate_mean <= float(mean_limit)
    )
    tolerance = float(
        config.get("nonworsening_tolerance_disc", 0.0)
    )
    max_nonworsening = candidate_max <= baseline_max + tolerance
    mean_nonworsening = candidate_mean <= baseline_mean + tolerance
    require_nonworsening = bool(
        config.get("require_nonworsening", False)
    )
    passed = (
        within_max
        and within_mean
        and (
            not require_nonworsening
            or (max_nonworsening and mean_nonworsening)
        )
    )
    return {
        "pass": passed,
        "inspection_completed": True,
        "within_maximum_limit": within_max,
        "within_mean_limit": within_mean,
        "maximum_nonworsening": max_nonworsening,
        "mean_nonworsening": mean_nonworsening,
        "require_nonworsening": require_nonworsening,
        "configured_maximum_candidate_span_disc": max_limit,
        "configured_maximum_candidate_mean_span_disc": mean_limit,
        "candidate_minus_baseline_maximum_span_disc": (
            candidate_max - baseline_max
        ),
        "candidate_minus_baseline_mean_span_disc": (
            candidate_mean - baseline_mean
        ),
        "nonworsening_tolerance_disc": tolerance,
    }


def run_direction_check(
    baseline: Evaluator,
    candidate: Evaluator,
    samples: dict[int, list[Position]],
    config: dict[str, Any],
    progress: CuiProgress,
) -> dict[str, Any]:
    per_phase = int(config["samples_per_phase"])
    if per_phase <= 0 or any(
        len(samples[phase]) < per_phase for phase in PHASES
    ):
        raise ValueError(
            "D4 samples_per_phase must be available in every phase"
        )
    baseline_stats = direction_stats(
        baseline,
        samples,
        per_phase,
        "baseline",
        EXPECTED_BASELINE_FEATURE_SCHEMA,
        progress,
    )
    candidate_stats = direction_stats(
        candidate,
        samples,
        per_phase,
        "candidate",
        EXPECTED_FEATURE_SCHEMA,
        progress,
    )
    return {
        "sample_rule": (
            "first N positions per phase from the deterministic heldout sample"
        ),
        "samples_per_phase": per_phase,
        "color_orientations_per_position": 2,
        "baseline_feature_schema": EXPECTED_BASELINE_FEATURE_SCHEMA,
        "candidate_feature_schema": EXPECTED_FEATURE_SCHEMA,
        "baseline": baseline_stats,
        "candidate": candidate_stats,
        "gate": direction_gate(
            baseline_stats, candidate_stats, config,
        ),
    }


def run_parity(
    candidate: Path,
    ai_source: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    positions = int(config["positions"])
    if positions != 4096:
        raise ValueError(
            "java_python_parity.positions must be exactly 4096"
        )
    command = [
        sys.executable,
        str(PROJECT_ROOT / "tests" / "compare_java_eval.py"),
        "--positions", str(positions),
        "--seed", str(int(config["seed"])),
        "--tolerance", str(float(config.get("tolerance", 1e-12))),
        "--param", str(candidate.resolve()),
        "--ai-source", str(ai_source.resolve()),
    ]
    if config.get("java"):
        command.extend(("--java", str(config["java"])))
    if config.get("javac"):
        command.extend(("--javac", str(config["javac"])))

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=float(config.get("timeout_seconds", 900)),
        )
    except subprocess.TimeoutExpired as error:
        return {
            "pass": False,
            "positions": positions,
            "command": command,
            "returncode": None,
            "error": f"timeout: {error}",
            "duration_seconds": time.monotonic() - started,
        }
    marker = f"PASS: {positions} reachable positions"
    passed = (
        completed.returncode == 0
        and marker in completed.stdout
    )
    return {
        "pass": passed,
        "positions": positions,
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
        "duration_seconds": time.monotonic() - started,
    }


def failed_checks(checks: dict[str, Any]) -> list[str]:
    return [
        name
        for name, check in checks.items()
        if not bool(check.get("pass", False))
    ]


def finish_decision(report: dict[str, Any]) -> dict[str, Any]:
    failed = failed_checks(report["checks"])
    report["decision"] = {
        "pass": not failed,
        "eligible_for_ab": not failed,
        "failed_checks": failed,
    }
    return report


def validate(
    candidate_path: Path,
    baseline_path: Path,
    ai_source: Path,
    expected_candidate_sha256: str | None,
    config: dict[str, Any],
    progress: CuiProgress,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "candidate_feature_schema": EXPECTED_FEATURE_SCHEMA,
        "baseline_feature_schema": EXPECTED_BASELINE_FEATURE_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "checks": {},
    }

    progress.step(1, 6, "checking parameter count, finiteness, and SHA-256")
    report["candidate"] = parameter_check(
        candidate_path, expected_candidate_sha256,
    )
    report["baseline"] = parameter_check(baseline_path)
    report["checks"]["parameters"] = {
        "pass": bool(
            report["candidate"]["pass"]
            and report["baseline"]["pass"]
        ),
        "required_count": EXPECTED_PARAMETER_COUNT,
        "all_values_must_be_finite": True,
        "candidate_hash_bound": (
            expected_candidate_sha256 is not None
        ),
    }
    report["checks"]["feature_schema"] = {
        "pass": (
            FEATURE_SCHEMA == EXPECTED_FEATURE_SCHEMA
            and config.get("feature_schema")
            == EXPECTED_FEATURE_SCHEMA
            and config.get("baseline_feature_schema")
            == EXPECTED_BASELINE_FEATURE_SCHEMA
        ),
        "python_evaluator": FEATURE_SCHEMA,
        "candidate_required": EXPECTED_FEATURE_SCHEMA,
        "baseline_required": EXPECTED_BASELINE_FEATURE_SCHEMA,
        "bridge_load_mode": "EXACT_MOBILITY",
    }
    if failed_checks(report["checks"]):
        return finish_decision(report)

    progress.step(2, 6, "verifying prepared test shards and sampling")
    heldout = config["heldout"]
    manifest_path = resolve_project_path(
        heldout["prepared_manifest"]
    )
    split = str(heldout.get("split", "test"))
    if split != "test":
        raise ValueError("candidate gating must use the prepared test split")
    shards, phase_weights, manifest_metadata = load_prepared_shards(
        manifest_path, split,
    )
    samples, sample_metadata = select_samples(
        shards, heldout, progress,
    )
    actual_phase_counts = {
        phase: int(sample_metadata["records_by_phase"][str(phase)])
        for phase in PHASES
    }
    if actual_phase_counts != phase_weights:
        raise ValueError(
            "prepared rows do not match manifest phase populations: "
            f"manifest={phase_weights}, actual={actual_phase_counts}"
        )
    report["heldout"] = {
        **manifest_metadata,
        **sample_metadata,
    }
    report["checks"]["heldout_integrity"] = {
        "pass": True,
        "split": split,
        "shard_count": len(shards),
        "sample_sha256": sample_metadata["sample_sha256"],
    }

    progress.step(3, 6, "running 4096-position Java/Python parity")
    parity = run_parity(
        candidate_path,
        ai_source,
        config["java_python_parity"],
    )
    report["checks"]["java_python_parity"] = parity
    if not parity["pass"]:
        return finish_decision(report)

    progress.step(4, 6, "computing population-weighted phase RMSE")
    baseline = Evaluator(baseline_path)
    candidate = Evaluator(candidate_path)
    rmse = evaluate_rmse(
        baseline,
        candidate,
        samples,
        phase_weights,
        progress,
    )
    report["rmse"] = rmse
    report["checks"]["rmse"] = rmse_gate(
        rmse, config["rmse_gate"],
    )

    progress.step(5, 6, "measuring deterministic D4 direction spans")
    directions = run_direction_check(
        baseline,
        candidate,
        samples,
        config["d4_direction_check"],
        progress,
    )
    report["d4_direction_difference"] = {
        key: value
        for key, value in directions.items()
        if key != "gate"
    }
    report["checks"]["d4_direction_difference"] = directions["gate"]
    return finish_decision(report)


def default_report_path(candidate: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate.stem)
    return (
        PROJECT_ROOT
        / "artifacts"
        / f"candidate_validation_{stem}_{timestamp}.json"
    )


def write_report_exclusive(
    path: Path,
    report: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("candidate gate config root must be an object")
    return config


def validate_config_contract(config: dict[str, Any]) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("candidate gate config schema_version must be 1")
    if config.get("feature_schema") != EXPECTED_FEATURE_SCHEMA:
        raise ValueError(
            "candidate gate feature_schema must be exact-mobility-v1"
        )
    if (
        config.get("baseline_feature_schema")
        != EXPECTED_BASELINE_FEATURE_SCHEMA
    ):
        raise ValueError(
            "candidate gate baseline_feature_schema must be legacy-v1"
        )
    parity = config.get("java_python_parity")
    heldout = config.get("heldout")
    rmse = config.get("rmse_gate")
    d4 = config.get("d4_direction_check")
    if not all(
        isinstance(item, dict)
        for item in (parity, heldout, rmse, d4)
    ):
        raise ValueError(
            "candidate gate config is missing a required section"
        )
    assert isinstance(parity, dict)
    assert isinstance(heldout, dict)
    assert isinstance(rmse, dict)
    assert isinstance(d4, dict)
    if int(parity.get("positions", -1)) != 4096:
        raise ValueError("Java/Python parity must use exactly 4096 positions")
    tolerance = float(parity.get("tolerance", math.nan))
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("Java/Python parity tolerance must be non-negative")
    if float(parity.get("timeout_seconds", 0.0)) <= 0.0:
        raise ValueError("Java/Python parity timeout must be positive")
    if heldout.get("split") != "test":
        raise ValueError("candidate gating must use heldout.split=test")
    heldout_limits = {
        phase: _sample_limit(heldout["samples_per_phase"], phase)
        for phase in PHASES
    }
    d4_count = int(d4.get("samples_per_phase", 0))
    if d4_count <= 0 or any(
        d4_count > heldout_limits[phase] for phase in PHASES
    ):
        raise ValueError(
            "D4 samples_per_phase must be positive and no larger than "
            "the heldout sample"
        )
    if (
        float(rmse.get("minimum_relative", -1.0)) < 0.0
        or float(rmse.get("minimum_absolute_disc", -1.0)) < 0.0
    ):
        raise ValueError("RMSE improvement thresholds must be non-negative")
    if int(rmse.get("endgame_phase", -1)) != 3:
        raise ValueError("the nonworsening RMSE gate must target phase 3")
    if float(rmse.get("endgame_tolerance_disc", -1.0)) < 0.0:
        raise ValueError("endgame_tolerance_disc must be non-negative")


def configured_path(
    cli_value: Path | None,
    config: dict[str, Any],
    key: str,
) -> Path:
    raw: str | Path
    if cli_value is not None:
        raw = cli_value
    else:
        raw_value = config.get(key)
        if not isinstance(raw_value, str) or not raw_value:
            raise ValueError(
                f"candidate gate config requires string key {key!r}"
            )
        raw = raw_value
    return resolve_project_path(raw).resolve()


def dry_run(
    candidate: Path,
    baseline: Path,
    ai_source: Path,
    expected_candidate_sha256: str | None,
    config_path: Path,
    config: dict[str, Any],
    report_path: Path,
) -> dict[str, Any]:
    candidate_check = parameter_check(
        candidate, expected_candidate_sha256,
    )
    baseline_check = parameter_check(baseline)
    heldout = config["heldout"]
    shards, _, manifest_metadata = load_prepared_shards(
        resolve_project_path(heldout["prepared_manifest"]),
        str(heldout.get("split", "test")),
    )
    required_files = {
        "ai_source": ai_source,
        "java_bridge": (
            PROJECT_ROOT / "tests" / "JavaEvalBridge10.java"
        ),
        "parity_script": (
            PROJECT_ROOT / "tests" / "compare_java_eval.py"
        ),
        "python_evaluator": (
            PROJECT_ROOT / "training" / "java_eval.py"
        ),
    }
    required_status = {
        key: {
            "path": str(path.resolve()),
            "exists": path.is_file(),
        }
        for key, path in required_files.items()
    }
    schema_pass = (
        FEATURE_SCHEMA == EXPECTED_FEATURE_SCHEMA
        and config.get("feature_schema")
        == EXPECTED_FEATURE_SCHEMA
        and config.get("baseline_feature_schema")
        == EXPECTED_BASELINE_FEATURE_SCHEMA
    )
    references_pass = all(
        item["exists"] for item in required_status.values()
    )
    would_overwrite = report_path.exists()
    passed = bool(
        candidate_check["pass"]
        and baseline_check["pass"]
        and schema_pass
        and references_pass
        and not would_overwrite
    )
    return {
        "dry_run": True,
        "pass": passed,
        "config_path": str(config_path.resolve()),
        "candidate": candidate_check,
        "baseline": baseline_check,
        "feature_schema": {
            "pass": schema_pass,
            "python_evaluator": FEATURE_SCHEMA,
            "candidate_required": EXPECTED_FEATURE_SCHEMA,
            "baseline_required": EXPECTED_BASELINE_FEATURE_SCHEMA,
        },
        "required_files": required_status,
        "heldout_plan": {
            **manifest_metadata,
            "samples_per_phase": heldout["samples_per_phase"],
            "sample_seed": heldout["sample_seed"],
            "shards_resolved": len(shards),
            "shards_scanned": 0,
        },
        "parity_plan": config["java_python_parity"],
        "report_path": str(report_path.resolve()),
        "report_exists": would_overwrite,
        "report_will_be_written": False,
    }


def self_test() -> None:
    board = list("-" * 64)
    for place in (0, 1, 10, 27):
        board[place] = "X"
    for place in (7, 18, 42):
        board[place] = "O"
    compact = "".join(board)
    variants = d4_variants(compact)
    if len(variants) != 8 or len(set(variants)) != 8:
        raise AssertionError("D4 variant generation failed")
    if canonical_d4(compact) != min(variants):
        raise AssertionError("D4 canonicalization failed")
    if absolute_board("XO--" + "-" * 60)[:4] != "01..":
        raise AssertionError("relative-to-absolute mapping failed")
    if sample_priority(compact, 17) != sample_priority(
        compact, 17,
    ):
        raise AssertionError("sample priority is not deterministic")
    synthetic = {
        "baseline": {
            "rmse_disc": 10.0,
            "phases": {"3": {"rmse_disc": 5.0}},
        },
        "candidate": {
            "rmse_disc": 9.9,
            "phases": {"3": {"rmse_disc": 5.0}},
        },
    }
    gate = rmse_gate(
        synthetic,
        {
            "minimum_relative": 0.01,
            "minimum_absolute_disc": 0.1,
            "endgame_phase": 3,
            "endgame_tolerance_disc": 0.0,
        },
    )
    if not gate["pass"]:
        raise AssertionError("RMSE threshold boundary self-test failed")
    print("PASS: validate_candidate self-test")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--ai-source", type=Path)
    parser.add_argument(
        "--expect-candidate-sha256",
        help="optional 64-hex digest binding for the candidate",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "candidate_gate.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help=(
            "exclusive-create JSON path; default contains candidate name "
            "and a UTC timestamp"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="check inputs and print the plan without scanning or writing",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run fast internal tests without model or data files",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.candidate is None:
        parser.error("--candidate is required unless --self-test is used")

    config_path = resolve_project_path(args.config).resolve()
    candidate = resolve_project_path(args.candidate).resolve()
    report_path = (
        resolve_project_path(args.report).resolve()
        if args.report is not None
        else default_report_path(candidate).resolve()
    )
    if report_path.exists() and not args.dry_run:
        print(
            f"ERROR: refusing to overwrite report: {report_path}",
            file=sys.stderr,
        )
        return 2

    progress = CuiProgress(args.quiet)
    try:
        config = load_config(config_path)
        validate_config_contract(config)
        baseline = configured_path(
            args.baseline, config, "baseline",
        )
        ai_source = configured_path(
            args.ai_source, config, "ai_source",
        )
        if args.dry_run:
            plan = dry_run(
                candidate,
                baseline,
                ai_source,
                args.expect_candidate_sha256,
                config_path,
                config,
                report_path,
            )
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0 if plan["pass"] else 1

        report = validate(
            candidate,
            baseline,
            ai_source,
            args.expect_candidate_sha256,
            config,
            progress,
        )
    except Exception as error:
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "pass": False,
                        "error": f"{type(error).__name__}: {error}",
                        "report_will_be_written": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        report = {
            "schema_version": 1,
            "feature_schema": EXPECTED_FEATURE_SCHEMA,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "decision": {
                "pass": False,
                "eligible_for_ab": False,
                "failed_checks": ["execution"],
            },
            "error": f"{type(error).__name__}: {error}",
        }

    progress.step(6, 6, f"writing exclusive report {report_path}")
    try:
        write_report_exclusive(report_path, report)
    except FileExistsError:
        print(
            f"ERROR: refusing to overwrite report: {report_path}",
            file=sys.stderr,
        )
        return 2
    decision = report["decision"]
    print(
        f"{'PASS' if decision['pass'] else 'FAIL'}: "
        f"eligible_for_ab={decision['eligible_for_ab']} "
        f"report={report_path}"
    )
    if decision["failed_checks"]:
        print(
            "failed_checks="
            + ",".join(decision["failed_checks"])
        )
    return 0 if decision["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
