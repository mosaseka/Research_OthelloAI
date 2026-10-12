#!/usr/bin/env python3
"""Compare baseline/11a/11b value parameters on diagnostic positions.

For each selected position this driver compiles the unmodified production
``OthelloAI_11.java`` with ``JavaRootSearchBridge11.java`` in a temporary
directory, then obtains all legal root moves at two fixed depths.  It also
examines every legal reply to the observed move.  Output remains diagnostic
only and is never sufficient evidence for training or candidate adoption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


POSITION_SCHEMA = "original-11-opponent-regression-v2"
JAVA_SCHEMA = "original-11-fixed-depth-root-diagnostic-v1"
OUTPUT_SCHEMA = "original-11-candidate-value-comparison-v1"
PARAMETER_COUNT = 25_436
ROOT_SCORE_TYPES = ("static", "shallow", "deep")
STRICT_TWO_PLY_DEFINITION = (
    "immediate_non_pass_opponent_move_then_immediate_non_pass_ai_move"
)
ROOT_RANKING_CONTRACT = {
    "applies_to": ["static", "shallow", "deep"],
    "value_ordering": "descending_larger_is_better",
    "primary_comparator": "java.lang.Double.compare(right_value, left_value)",
    "tie_equality_basis": "unrounded_java_double_score_before_json_formatting",
    "tie_break_key": "zero_based_row_major_policy_cell_number_ascending",
    "policy_cell_number_definition": "row * 8 + column",
    "rank_method": "ordinal_after_value_and_cell_total_order",
    "rank_sequence": "1,2,...,legal_move_count; equal values never share a rank",
}


def fail(message: str) -> "NoReturn":
    raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parameter_check(path: Path) -> str:
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    fail(f"{path}:{number}: blank parameter")
                try:
                    value = float(line)
                except ValueError as exc:
                    fail(f"{path}:{number}: invalid parameter: {exc}")
                if not math.isfinite(value):
                    fail(f"{path}:{number}: non-finite parameter")
                count += 1
    except OSError as exc:
        fail(f"cannot read parameter file {path}: {exc}")
    if count != PARAMETER_COUNT:
        fail(f"{path}: expected {PARAMETER_COUNT} parameters, got {count}")
    return sha256(path)


def parse_model(value: str) -> tuple[str, Path]:
    if "=" not in value:
        fail("--model must be LABEL=PARAMETER_PATH")
    label, raw_path = value.split("=", 1)
    if not label or not label.replace("_", "").replace("-", "").isalnum():
        fail(f"invalid model label: {label!r}")
    return label, Path(raw_path).resolve()


def load_positions(path: Path, focus_only: bool) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    skipped_requested_ranges: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict) or value.get("schema") != POSITION_SCHEMA:
                    fail(f"{path}:{number}: unexpected regression schema")
                if value.get("diagnostic_only") is not True:
                    fail(f"{path}:{number}: diagnostic_only must be true")
                if value.get("training_eligible") is not False:
                    fail(f"{path}:{number}: training_eligible must be false")
                if value.get("adoption_gate_eligible") is not False:
                    fail(f"{path}:{number}: adoption_gate_eligible must be false")
                board = value.get("board")
                if not isinstance(board, str) or len(board) != 64 or any(c not in ".XO" for c in board):
                    fail(f"{path}:{number}: invalid board")
                two_ply_valid = value.get("two_ply_sequence_valid")
                two_ply_reason = value.get("two_ply_unavailable_reason")
                if not isinstance(two_ply_valid, bool):
                    fail(f"{path}:{number}: two_ply_sequence_valid must be boolean")
                if value.get("two_ply_sequence_definition") != STRICT_TWO_PLY_DEFINITION:
                    fail(f"{path}:{number}: unexpected two-ply sequence definition")
                if two_ply_valid:
                    if two_ply_reason is not None:
                        fail(f"{path}:{number}: valid two-ply record has an unavailable reason")
                    reply = value.get("observed_opponent_reply")
                    if not isinstance(reply, list) or len(reply) != 2:
                        fail(f"{path}:{number}: valid two-ply record has no direct reply")
                    required_two_ply_fields = (
                        "observed_opponent_reply_algebraic",
                        "board_after_observed_opponent_reply",
                        "next_ai_turn_stones",
                        "next_ai_turn_value_engine_disc",
                        "observed_two_ply_value_change_engine_disc",
                        "same_phase_to_next_ai_turn",
                    )
                    for field in required_two_ply_fields:
                        if value.get(field) is None:
                            fail(
                                f"{path}:{number}: valid two-ply field {field} is missing"
                            )
                else:
                    if not isinstance(two_ply_reason, str) or not two_ply_reason:
                        fail(f"{path}:{number}: unavailable two-ply record has no reason")
                    nullable_two_ply_fields = (
                        "observed_opponent_reply",
                        "observed_opponent_reply_algebraic",
                        "board_after_observed_opponent_reply",
                        "next_ai_turn_stones",
                        "next_ai_turn_value_engine_disc",
                        "observed_two_ply_value_change_engine_disc",
                        "same_phase_to_next_ai_turn",
                    )
                    for field in nullable_two_ply_fields:
                        if value.get(field) is not None:
                            fail(
                                f"{path}:{number}: unavailable two-ply field {field} "
                                "must be null"
                            )
                # By default include every sidecar-pinned position.  This
                # covers both 29/31-stone value-collapse positions (hypothesis
                # B) and 42/44-stone book-transition positions (hypothesis A).
                if focus_only and value.get("focus_role") is None:
                    reasons = value.get("importance_reasons")
                    if isinstance(reasons, list) and "requested_stone_range" in reasons:
                        skipped_requested_ranges.append(
                            str(value.get("position_id") or f"line-{number}")
                        )
                    continue
                result.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read positions {path}: {exc}")
    if skipped_requested_ranges:
        preview = ", ".join(skipped_requested_ranges[:4])
        suffix = "..." if len(skipped_requested_ranges) > 4 else ""
        fail(
            "requested-stone-range positions require --all-positions; "
            f"otherwise they would be omitted ({preview}{suffix})"
        )
    if not result:
        fail("no selected diagnostic positions")
    return result


def compile_bridge(java_source: Path, bridge_source: Path, classes: Path) -> None:
    if java_source.name != "OthelloAI_11.java":
        fail("--ai-source must be named OthelloAI_11.java")
    if not java_source.is_file() or not bridge_source.is_file():
        fail("Java source or diagnostic bridge is missing")
    javac = shutil.which("javac")
    if javac is None:
        fail("javac was not found on PATH")
    command = [
        javac, "--release", "11", "-encoding", "UTF-8", "-d", str(classes),
        str(java_source), str(bridge_source),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        fail(f"javac failed:\n{completed.stdout}\n{completed.stderr}")


def run_bridge(
    classes: Path,
    parameter: Path,
    position: dict[str, Any],
    shallow_depth: int,
    deep_depth: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    java = shutil.which("java")
    if java is None:
        fail("java was not found on PATH")
    observed = position.get("observed_move")
    if not isinstance(observed, list) or len(observed) != 2:
        fail(f"{position.get('position_id')}: observed_move is missing")
    command = [
        java, "-cp", str(classes), "JavaRootSearchBridge11",
        "--param", str(parameter),
        "--board", position["board"],
        "--player", str(int(position["player"])),
        "--shallow-depth", str(shallow_depth),
        "--deep-depth", str(deep_depth),
        "--observed-row", str(int(observed[0])),
        "--observed-col", str(int(observed[1])),
    ]
    reply = position.get("observed_opponent_reply")
    if isinstance(reply, list) and len(reply) == 2:
        command.extend([
            "--observed-reply-row", str(int(reply[0])),
            "--observed-reply-col", str(int(reply[1])),
        ])
    try:
        completed = subprocess.run(
            command, text=True, capture_output=True, check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        fail(f"Java fixed-depth search timed out for {position.get('position_id')}: {exc}")
    if completed.returncode != 0:
        fail(
            f"Java fixed-depth search failed for {position.get('position_id')}:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        fail(f"Java bridge emitted {len(lines)} non-empty stdout lines, expected one")
    try:
        report = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        fail(f"Java bridge emitted invalid JSON: {exc}")
    if not isinstance(report, dict) or report.get("schema") != JAVA_SCHEMA:
        fail("Java bridge returned an unexpected schema")
    if report.get("diagnostic_only") is not True:
        fail("Java bridge diagnostic_only must be true")
    if report.get("training_eligible") is not False:
        fail("Java bridge training_eligible must be false")
    if report.get("adoption_gate_eligible") is not False:
        fail("Java bridge adoption_gate_eligible must be false")
    if report.get("mpc_used") is not False:
        fail("Java bridge mpc_used must be false")
    root_rank_summaries(report)
    return report


def diagnosis(
    report: dict[str, Any], logged_change: Any, focus_role: str | None
) -> list[str]:
    observed = report.get("observed") or {}
    observed_reply = report.get("observed_opponent_reply") or {}
    reasons: list[str] = []
    if focus_role in {"book_transition_origin", "book_transition_destination"}:
        reasons.append("value_search_diagnostic_only_does_not_establish_a_book_hit")
    if int(observed.get("deep_rank", 1)) > 1 or float(observed.get("deep_best_gap_disc", 0.0)) >= 0.25:
        reasons.append("deep_search_prefers_another_root_move")
    if int(observed.get("shallow_rank", 1)) != int(observed.get("deep_rank", 1)):
        reasons.append("shallow_and_deep_root_ranks_disagree")
    if observed_reply and int(observed_reply.get("opponent_rank", 999)) == 1:
        reasons.append("observed_reply_is_deep_best_opponent_reply")
    if isinstance(logged_change, (int, float)) and float(logged_change) <= -3.0:
        reasons.append("logged_two_ply_value_collapse")
    if not reasons:
        reasons.append("fixed_depth_search_does_not_identify_a_single_large_cause")
    return reasons


def result_class(value: float) -> str:
    if value > 0.0:
        return "win"
    if value < 0.0:
        return "loss"
    return "draw"


def move_key(move: Any) -> str:
    if (
        not isinstance(move, list) or len(move) != 2 or
        not all(isinstance(value, int) and not isinstance(value, bool) for value in move)
    ):
        fail(f"invalid move in Java report: {move!r}")
    row, col = move
    if not (0 <= row < 8 and 0 <= col < 8):
        fail(f"out-of-range move in Java report: {move!r}")
    return f"{chr(ord('A') + col)}{row + 1}"


def legal_move_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    moves = report.get("legal_moves")
    if not isinstance(moves, list) or not moves:
        fail("Java report has no legal_moves")
    result: dict[str, dict[str, Any]] = {}
    required = (
        "static_value_disc", "shallow_value_disc", "deep_value_disc",
        "static_rank", "shallow_rank", "deep_rank",
    )
    for move in moves:
        if not isinstance(move, dict):
            fail("Java legal move entry is not an object")
        key = move_key(move.get("move"))
        if move.get("move_algebraic") != key:
            fail(f"Java move coordinate/algebraic disagreement for {key}")
        if key in result:
            fail(f"duplicate Java legal move: {key}")
        for field in required:
            if field not in move:
                fail(f"Java legal move {key} is missing {field}")
        result[key] = move
    return result


def all_root_move_deltas(
    candidate: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    baseline_moves = legal_move_map(baseline)
    candidate_moves = legal_move_map(candidate)
    if set(candidate_moves) != set(baseline_moves):
        fail("candidate and baseline legal root move sets differ")
    result: dict[str, dict[str, Any]] = {}
    for key, base in baseline_moves.items():
        cand = candidate_moves[key]
        result[key] = {
            "move": base["move"],
            "baseline": {
                "static_value_disc": float(base["static_value_disc"]),
                "shallow_value_disc": float(base["shallow_value_disc"]),
                "deep_value_disc": float(base["deep_value_disc"]),
                "static_rank": int(base["static_rank"]),
                "shallow_rank": int(base["shallow_rank"]),
                "deep_rank": int(base["deep_rank"]),
            },
            "candidate": {
                "static_value_disc": float(cand["static_value_disc"]),
                "shallow_value_disc": float(cand["shallow_value_disc"]),
                "deep_value_disc": float(cand["deep_value_disc"]),
                "static_rank": int(cand["static_rank"]),
                "shallow_rank": int(cand["shallow_rank"]),
                "deep_rank": int(cand["deep_rank"]),
            },
            "candidate_minus_baseline": {
                "static_value_disc": (
                    float(cand["static_value_disc"]) - float(base["static_value_disc"])
                ),
                "shallow_value_disc": (
                    float(cand["shallow_value_disc"]) - float(base["shallow_value_disc"])
                ),
                "deep_value_disc": (
                    float(cand["deep_value_disc"]) - float(base["deep_value_disc"])
                ),
                "static_rank": int(cand["static_rank"]) - int(base["static_rank"]),
                "shallow_rank": int(cand["shallow_rank"]) - int(base["shallow_rank"]),
                "deep_rank": int(cand["deep_rank"]) - int(base["deep_rank"]),
            },
        }
    return result


def optional_float_delta(right: Any, left: Any) -> float | None:
    if right is None or left is None:
        return None
    return float(right) - float(left)


def root_rank_summaries(report: dict[str, Any]) -> dict[str, Any]:
    raw = report.get("root_rank_summaries")
    if not isinstance(raw, dict):
        fail("Java report is missing root_rank_summaries")
    if (
        raw.get("viewpoint") != "root_player" or
        raw.get("value_unit") != "disc" or
        raw.get("ordering") != "larger_is_better" or
        raw.get("gap_definition") != "best_value_disc - runner_up_value_disc"
    ):
        fail("Java root_rank_summaries viewpoint/unit contract is invalid")
    for score_type in ROOT_SCORE_TYPES:
        summary = raw.get(score_type)
        if not isinstance(summary, dict):
            fail(f"Java root_rank_summaries is missing {score_type}")
        best_key = move_key(summary.get("best_move"))
        if summary.get("best_move_algebraic") != best_key:
            fail(f"Java {score_type} best move coordinate/algebraic disagreement")
        best_value = float(summary.get("best_value_disc"))
        if not math.isfinite(best_value):
            fail(f"Java {score_type} best value is non-finite")
        runner = summary.get("runner_up_move")
        runner_name = summary.get("runner_up_move_algebraic")
        runner_value = summary.get("runner_up_value_disc")
        gap = summary.get("best_minus_runner_up_gap_disc")
        if runner is None:
            if runner_name is not None or runner_value is not None or gap is not None:
                fail(f"Java {score_type} single-move summary has partial runner-up data")
        else:
            runner_key = move_key(runner)
            if runner_name != runner_key:
                fail(f"Java {score_type} runner-up coordinate/algebraic disagreement")
            runner_number = float(runner_value)
            gap_number = float(gap)
            if not math.isfinite(runner_number) or not math.isfinite(gap_number):
                fail(f"Java {score_type} runner-up/gap value is non-finite")
            if abs((best_value - runner_number) - gap_number) > 0.00000002:
                fail(f"Java {score_type} best-minus-runner-up gap is inconsistent")
            if gap_number < -0.00000002:
                fail(f"Java {score_type} best-minus-runner-up gap is negative")
    return raw


def compare_root_rank_summaries(
    right_report: dict[str, Any],
    left_report: dict[str, Any],
    right_label: str,
    left_label: str,
) -> dict[str, Any]:
    right = root_rank_summaries(right_report)
    left = root_rank_summaries(left_report)
    result: dict[str, Any] = {
        "left_label": left_label,
        "right_label": right_label,
        "delta_definition": "right minus left",
        "viewpoint": "root_player",
        "value_unit": "disc",
        "ordering": "larger_is_better",
        "gap_definition": "best_value_disc - runner_up_value_disc",
    }
    for score_type in ROOT_SCORE_TYPES:
        left_summary = left[score_type]
        right_summary = right[score_type]
        result[score_type] = {
            "left": left_summary,
            "right": right_summary,
            "best_move_changed": (
                right_summary["best_move"] != left_summary["best_move"]
            ),
            "runner_up_move_changed": (
                right_summary["runner_up_move"] != left_summary["runner_up_move"]
            ),
            "right_minus_left": {
                "best_value_disc": optional_float_delta(
                    right_summary["best_value_disc"], left_summary["best_value_disc"]
                ),
                "runner_up_value_disc": optional_float_delta(
                    right_summary["runner_up_value_disc"],
                    left_summary["runner_up_value_disc"],
                ),
                "best_minus_runner_up_gap_disc": optional_float_delta(
                    right_summary["best_minus_runner_up_gap_disc"],
                    left_summary["best_minus_runner_up_gap_disc"],
                ),
            },
        }
    return result


def pairwise_root_rank_comparisons(
    reports: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    labels = list(reports)
    result: list[dict[str, Any]] = []
    for left_index, left_label in enumerate(labels):
        for right_label in labels[left_index + 1:]:
            result.append(compare_root_rank_summaries(
                reports[right_label], reports[left_label], right_label, left_label
            ))
    return result


def prediction_error(value: float, final_disc_difference: float) -> dict[str, Any]:
    signed_error = value - final_disc_difference
    predicted_result = result_class(value)
    final_result = result_class(final_disc_difference)
    return {
        "value_disc": value,
        "value_minus_final_disc": signed_error,
        "absolute_error_disc": abs(signed_error),
        "predicted_result": predicted_result,
        "result_correct": predicted_result == final_result,
    }


def final_result_error(
    report: dict[str, Any], final_disc_difference: float
) -> dict[str, Any]:
    observed = report.get("observed")
    if not isinstance(observed, dict):
        fail("Java report is missing the observed root move")
    observed_key = move_key(observed.get("move"))
    observed_root = legal_move_map(report).get(observed_key)
    if observed_root is None:
        fail("observed move is absent from Java legal_moves")
    current_value = float(report["current_value_disc"])
    observed_static = float(observed_root["static_value_disc"])
    observed_shallow = float(observed["shallow_value_disc"])
    observed_deep = float(observed["deep_value_disc"])
    deep_best = float(report["deep_best_value_disc"])
    return {
        "viewpoint": "engine/root player at the logged AI turn; values are in discs",
        "final_disc_difference_engine": final_disc_difference,
        "final_result_engine": result_class(final_disc_difference),
        "current_value_minus_final_disc": current_value - final_disc_difference,
        "observed_static_value_minus_final_disc": observed_static - final_disc_difference,
        "observed_shallow_value_minus_final_disc": observed_shallow - final_disc_difference,
        "observed_deep_value_minus_final_disc": observed_deep - final_disc_difference,
        "deep_best_value_minus_final_disc": deep_best - final_disc_difference,
        "predictions": {
            "current": prediction_error(current_value, final_disc_difference),
            "observed_move_static": prediction_error(observed_static, final_disc_difference),
            "observed_move_shallow": prediction_error(observed_shallow, final_disc_difference),
            "observed_move_deep": prediction_error(observed_deep, final_disc_difference),
            "deep_best_move_deep": prediction_error(deep_best, final_disc_difference),
        },
    }


def write_exclusive(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except FileExistsError:
        fail(f"refusing to overwrite existing output: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", required=True, type=Path)
    parser.add_argument("--ai-source", required=True, type=Path)
    parser.add_argument(
        "--bridge-source", type=Path,
        default=Path(__file__).resolve().parents[1] / "tests" / "JavaRootSearchBridge11.java",
    )
    parser.add_argument(
        "--model", action="append", required=True,
        help="repeat LABEL=PARAMETER_PATH; include baseline, value_11a and value_11b",
    )
    parser.add_argument("--baseline-label", required=True)
    parser.add_argument("--shallow-depth", type=int, default=3)
    parser.add_argument("--deep-depth", type=int, default=7)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--all-positions", action="store_true",
        help=(
            "include automatic and requested-range records, not only sidecar focus; "
            "required for game-02 --include-stones regression sets"
        ),
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    if not (1 <= args.shallow_depth <= args.deep_depth <= 16):
        fail("depths must satisfy 1 <= shallow <= deep <= 16")
    if args.timeout_seconds <= 0:
        fail("timeout-seconds must be positive")

    models: dict[str, Path] = {}
    model_hashes: dict[str, str] = {}
    for raw_model in args.model:
        label, path = parse_model(raw_model)
        if label in models:
            fail(f"duplicate model label: {label}")
        models[label] = path
        model_hashes[label] = parameter_check(path)
    if args.baseline_label not in models:
        fail("--baseline-label must name one of --model")
    if len(models) < 2:
        fail("at least a baseline and one candidate model are required")

    positions_path = args.positions.resolve()
    positions = load_positions(positions_path, focus_only=not args.all_positions)
    output_path = args.output.resolve()
    manifest_path = args.manifest.resolve()
    for path in (output_path, manifest_path):
        if path.exists():
            fail(f"refusing to overwrite existing output: {path}")

    records: list[dict[str, Any]] = []
    completed_searches = 0
    total_searches = len(positions) * len(models)
    with tempfile.TemporaryDirectory(prefix="othello11-root-diagnostic-") as raw_temp:
        classes = Path(raw_temp)
        compile_bridge(args.ai_source.resolve(), args.bridge_source.resolve(), classes)
        for position in positions:
            reports: dict[str, dict[str, Any]] = {}
            for label, parameter in models.items():
                print(
                    f"CUI [root-diagnostic {completed_searches + 1}/{total_searches}] "
                    f"position={position['position_id']} model={label}",
                    file=sys.stderr,
                    flush=True,
                )
                report = run_bridge(
                    classes, parameter, position,
                    args.shallow_depth, args.deep_depth, args.timeout_seconds,
                )
                if report.get("parameter_sha256") != model_hashes[label]:
                    fail(f"{label}: Java/Python parameter SHA-256 disagreement")
                reports[label] = report
                completed_searches += 1
            baseline = reports[args.baseline_label]
            baseline_observed = baseline.get("observed") or {}
            comparisons: dict[str, Any] = {}
            for label, report in reports.items():
                if label == args.baseline_label:
                    continue
                observed = report.get("observed") or {}
                comparisons[label] = {
                    "baseline_label": args.baseline_label,
                    "candidate_label": label,
                    "current_value_delta_disc": (
                        float(report["current_value_disc"]) - float(baseline["current_value_disc"])
                    ),
                    "observed_shallow_rank_delta": (
                        int(observed.get("shallow_rank", 0)) -
                        int(baseline_observed.get("shallow_rank", 0))
                    ),
                    "observed_deep_rank_delta": (
                        int(observed.get("deep_rank", 0)) -
                        int(baseline_observed.get("deep_rank", 0))
                    ),
                    "observed_deep_best_gap_delta_disc": (
                        float(observed.get("deep_best_gap_disc", 0.0)) -
                        float(baseline_observed.get("deep_best_gap_disc", 0.0))
                    ),
                    "deep_best_move_changed": (
                        report.get("deep_best_move") != baseline.get("deep_best_move")
                    ),
                    "delta_definition": (
                        "candidate minus baseline; a negative rank delta means the "
                        "candidate ranks that move higher"
                    ),
                    "all_root_moves": all_root_move_deltas(report, baseline),
                    "root_rank_summaries": compare_root_rank_summaries(
                        report, baseline, label, args.baseline_label
                    ),
                }
            final_disc_raw = position.get("source_final_disc_difference_engine")
            if (
                not isinstance(final_disc_raw, (int, float)) or
                isinstance(final_disc_raw, bool) or not math.isfinite(float(final_disc_raw))
            ):
                fail(f"{position['position_id']}: final engine disc difference is missing")
            final_disc = float(final_disc_raw)
            logged_final_result = position.get("source_final_result_engine")
            if logged_final_result != result_class(final_disc):
                fail(
                    f"{position['position_id']}: final result/disc-difference disagreement: "
                    f"{logged_final_result!r} versus {final_disc}"
                )
            records.append({
                "schema": OUTPUT_SCHEMA,
                "position_id": position["position_id"],
                "game_id": position["game_id"],
                "focus_role": position.get("focus_role"),
                "hypothesis": (
                    "A_book_mode_transition"
                    if position.get("focus_role") in {
                        "book_transition_origin", "book_transition_destination"
                    }
                    else "B_value_move_ranking"
                ),
                "board": position["board"],
                "player": position["player"],
                "observed_move": position["observed_move"],
                "observed_opponent_reply": position.get("observed_opponent_reply"),
                "logged_current_value_engine_disc": position.get("observed_value_engine_disc"),
                "logged_next_ai_value_engine_disc": position.get("next_ai_turn_value_engine_disc"),
                "logged_two_ply_value_change_engine_disc": position.get(
                    "observed_two_ply_value_change_engine_disc"
                ),
                "two_ply_sequence_valid": position["two_ply_sequence_valid"],
                "two_ply_sequence_definition": position[
                    "two_ply_sequence_definition"
                ],
                "two_ply_unavailable_reason": position.get(
                    "two_ply_unavailable_reason"
                ),
                "source_final_result_engine": logged_final_result,
                "source_final_disc_difference_engine": final_disc,
                "final_result_error_viewpoint": (
                    "engine/root player at the logged AI turn; values are in discs"
                ),
                "shallow_depth": args.shallow_depth,
                "deep_depth": args.deep_depth,
                "baseline_label": args.baseline_label,
                "root_ranking_contract": ROOT_RANKING_CONTRACT,
                "model_reports": reports,
                "candidate_vs_baseline": comparisons,
                "model_pair_root_rank_summary_comparisons": (
                    pairwise_root_rank_comparisons(reports)
                ),
                "final_result_error_by_model": {
                    label: final_result_error(report, final_disc)
                    for label, report in reports.items()
                },
                "two_ply_diagnosis_by_model": {
                    label: (
                        diagnosis(
                            report,
                            position.get("observed_two_ply_value_change_engine_disc"),
                            position.get("focus_role"),
                        )
                        if position["two_ply_sequence_valid"]
                        else [
                            "two_ply_sequence_unavailable:"
                            + str(position["two_ply_unavailable_reason"])
                        ]
                    )
                    for label, report in reports.items()
                },
                "diagnostic_only": True,
                "training_eligible": False,
                "adoption_gate_eligible": False,
            })

    output_text = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )
    manifest = {
        "schema": OUTPUT_SCHEMA,
        "positions": str(positions_path),
        "positions_sha256": sha256(positions_path),
        "ai_source": str(args.ai_source.resolve()),
        "ai_source_sha256": sha256(args.ai_source.resolve()),
        "bridge_source": str(args.bridge_source.resolve()),
        "bridge_source_sha256": sha256(args.bridge_source.resolve()),
        "models": {
            label: {"path": str(models[label]), "sha256": model_hashes[label]}
            for label in models
        },
        "baseline_label": args.baseline_label,
        "shallow_depth": args.shallow_depth,
        "deep_depth": args.deep_depth,
        "root_ranking_contract": ROOT_RANKING_CONTRACT,
        "position_count": len(records),
        "output": str(output_path),
        "diagnostic_only": True,
        "training_eligible": False,
        "adoption_gate_eligible": False,
        "warning": "Fixed-depth ranks on five observed games are diagnostic, not adoption evidence.",
    }
    write_exclusive(output_path, output_text)
    write_exclusive(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
