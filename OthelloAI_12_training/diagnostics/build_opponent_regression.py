#!/usr/bin/env python3
"""Build diagnostic-only regression positions from parsed opponent games.

This tool never emits examples in the evaluator training schema.  It selects
positions that are useful for explaining a game (large evaluation changes,
sign changes, late play, caller-requested stone ranges, and sidecar-pinned
focus positions), and labels every output as ineligible for training or
candidate adoption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


INPUT_SCHEMA = "original-11-opponent-log-diagnostic-v1"
OUTPUT_SCHEMA = "original-11-opponent-regression-v2"
STRICT_TWO_PLY_DEFINITION = (
    "immediate_non_pass_opponent_move_then_immediate_non_pass_ai_move"
)


def fail(message: str) -> "NoReturn":
    raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSON {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    fail(f"{path}:{number}: record is not an object")
                if value.get("schema") != INPUT_SCHEMA:
                    fail(f"{path}:{number}: unexpected schema {value.get('schema')!r}")
                if value.get("diagnostic_only") is not True:
                    fail(f"{path}:{number}: diagnostic_only must be true")
                if value.get("training_eligible") is not False:
                    fail(f"{path}:{number}: training_eligible must be false")
                if value.get("adoption_gate_eligible") is not False:
                    fail(f"{path}:{number}: adoption_gate_eligible must be false")
                rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSONL {path}: {exc}")
    if not rows:
        fail(f"no records in {path}")
    return rows


def phase(stones: int) -> int:
    return max(0, min(3, (stones - 4) // 10 - 2))


def parse_stone_range(value: str) -> tuple[int, int]:
    parts = value.split(":", 1)
    if len(parts) != 2:
        fail(f"invalid stone range {value!r}; expected MIN:MAX")
    try:
        minimum, maximum = (int(part) for part in parts)
    except ValueError:
        fail(f"invalid stone range {value!r}; MIN and MAX must be integers")
    if not (4 <= minimum <= maximum <= 63):
        fail(f"invalid stone range {value!r}; require 4 <= MIN <= MAX <= 63")
    return minimum, maximum


def strict_two_ply_followup(
    rows: list[dict[str, Any]], index: int
) -> tuple[int | None, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Return only an immediate opponent move followed by an immediate AI move.

    A pass or any additional transition makes the pair unavailable.  Partial
    records are deliberately discarded so no later reply can be mislabeled as
    the observed move's direct two-ply continuation.
    """
    game_id = rows[index]["game_id"]
    opponent_index = index + 1
    if opponent_index >= len(rows):
        return None, None, None, "missing_immediate_opponent_transition"
    opponent = rows[opponent_index]
    if opponent.get("game_id") != game_id:
        return None, None, None, "game_boundary_before_immediate_opponent_transition"
    if opponent.get("is_ai_move"):
        return None, None, None, "expected_immediate_opponent_transition"
    if opponent.get("is_pass"):
        return None, None, None, "immediate_opponent_transition_is_pass"

    next_ai_index = index + 2
    if next_ai_index >= len(rows):
        return None, None, None, "missing_immediate_next_ai_transition"
    next_ai = rows[next_ai_index]
    if next_ai.get("game_id") != game_id:
        return None, None, None, "game_boundary_before_immediate_next_ai_transition"
    if not next_ai.get("is_ai_move"):
        return None, None, None, "additional_opponent_transition_before_next_ai_turn"
    if next_ai.get("is_pass"):
        return None, None, None, "immediate_next_ai_transition_is_pass"
    return next_ai_index, next_ai, opponent, None


def important_reasons(
    current: dict[str, Any], next_ai: dict[str, Any] | None, swing_threshold: float
) -> list[str]:
    reasons: list[str] = []
    current_eval = current.get("evaluation_engine_disc_before_move")
    next_eval = next_ai.get("evaluation_engine_disc_before_move") if next_ai else None
    if isinstance(current_eval, (int, float)) and isinstance(next_eval, (int, float)):
        swing = float(next_eval) - float(current_eval)
        if abs(swing) >= swing_threshold:
            reasons.append("large_two_ply_evaluation_change")
        if current_eval != 0 and next_eval != 0 and math.copysign(1.0, current_eval) != math.copysign(1.0, next_eval):
            reasons.append("evaluation_sign_change")
    if int(current["empties_before"]) <= 20:
        reasons.append("late_game")
    if int(current["move_row"]) in {0, 7} and int(current["move_col"]) in {0, 7}:
        reasons.append("observed_corner_move")
    return reasons


def regression_record(
    current: dict[str, Any],
    next_ai: dict[str, Any] | None,
    opponent: dict[str, Any] | None,
    reasons: list[str],
    focus_role: str | None,
    source_path: Path,
    two_ply_unavailable_reason: str | None,
) -> dict[str, Any]:
    two_ply_sequence_valid = two_ply_unavailable_reason is None
    if two_ply_sequence_valid != (next_ai is not None and opponent is not None):
        fail("internal strict two-ply state is inconsistent")
    current_eval = current.get("evaluation_engine_disc_before_move")
    next_eval = next_ai.get("evaluation_engine_disc_before_move") if next_ai else None
    swing = None
    if isinstance(current_eval, (int, float)) and isinstance(next_eval, (int, float)):
        swing = float(next_eval) - float(current_eval)
    position_id = (
        f"{current['game_id']}-stones{int(current['stones_before']):02d}-"
        f"ply{int(current['ply']):02d}"
    )
    return {
        "schema": OUTPUT_SCHEMA,
        "position_id": position_id,
        "game_id": current["game_id"],
        "source_parsed_jsonl": str(source_path),
        "source_ply": current["ply"],
        "board": current["board_before"],
        "player": current["player"],
        "side_to_move": current["side_to_move"],
        "stones": current["stones_before"],
        "empties": current["empties_before"],
        "phase": phase(int(current["stones_before"])),
        "observed_move": [current["move_row"], current["move_col"]],
        "observed_move_algebraic": current["move_algebraic"],
        "observed_value_engine_disc": current_eval,
        "board_after_observed_move": current["board_after"],
        "observed_opponent_reply": (
            [opponent["move_row"], opponent["move_col"]]
            if two_ply_sequence_valid else None
        ),
        "observed_opponent_reply_algebraic": (
            opponent["move_algebraic"] if two_ply_sequence_valid else None
        ),
        "board_after_observed_opponent_reply": (
            opponent["board_after"] if two_ply_sequence_valid else None
        ),
        "next_ai_turn_stones": (
            next_ai.get("stones_before") if two_ply_sequence_valid else None
        ),
        "next_ai_turn_value_engine_disc": (
            next_eval if two_ply_sequence_valid else None
        ),
        "observed_two_ply_value_change_engine_disc": (
            swing if two_ply_sequence_valid else None
        ),
        "same_phase_to_next_ai_turn": (
            phase(int(current["stones_before"])) == phase(int(next_ai["stones_before"]))
            if two_ply_sequence_valid else None
        ),
        "two_ply_sequence_valid": two_ply_sequence_valid,
        "two_ply_sequence_definition": STRICT_TWO_PLY_DEFINITION,
        "two_ply_unavailable_reason": two_ply_unavailable_reason,
        "importance_reasons": sorted(set(reasons)),
        "focus_role": focus_role,
        "source_final_result_engine": current.get("final_result_engine"),
        "source_final_disc_difference_engine": current.get(
            "source_game_result_engine_disc_difference"
        ),
        "diagnostic_only": True,
        "training_eligible": False,
        "adoption_gate_eligible": False,
    }


def validate_focus(
    rows: list[dict[str, Any]], metadata: dict[str, Any]
) -> dict[int, str]:
    focus = metadata.get("observed_focus")
    if focus is None:
        return {}
    if not isinstance(focus, dict):
        fail("observed_focus must be an object")
    is_book_transition = "stones_before_first_engine_move" in focus
    stones = int(
        focus["stones_before_first_engine_move"] if is_book_transition
        else focus["stones_before_engine_move"]
    )
    move = [
        int(value) for value in (
            focus["first_engine_move"] if is_book_transition else focus["engine_move"]
        )
    ]
    expected_eval = float(
        focus["evaluation_before_first_engine_move"] if is_book_transition
        else focus["evaluation_before_move"]
    )
    matches = [
        index for index, row in enumerate(rows)
        if (
            row.get("is_ai_move") and not row.get("is_pass") and
            int(row["stones_before"]) == stones
        )
    ]
    if len(matches) != 1:
        fail(f"focus stones={stones}: expected one AI position, found {len(matches)}")
    focus_index = matches[0]
    row = rows[focus_index]
    if [int(row["move_row"]), int(row["move_col"])] != move:
        fail("focus engine_move disagrees with parsed log")
    if abs(float(row["evaluation_engine_disc_before_move"]) - expected_eval) > 1e-9:
        fail("focus evaluation_before_move disagrees with parsed log")
    if is_book_transition:
        expected_seconds = float(focus["search_seconds_before_first_engine_move"])
        if abs(float(row["search_seconds"]) - expected_seconds) > 1e-9:
            fail("book focus first search time disagrees with parsed log")
    next_index, next_ai, _opponent, two_ply_reason = strict_two_ply_followup(
        rows, focus_index
    )
    if two_ply_reason is not None or next_ai is None:
        fail(f"focus does not have a strict two-ply continuation: {two_ply_reason}")
    expected_next = float(
        focus["evaluation_before_next_engine_move"] if is_book_transition
        else focus["evaluation_at_next_engine_turn"]
    )
    if abs(float(next_ai["evaluation_engine_disc_before_move"]) - expected_next) > 1e-9:
        fail("focus next-turn evaluation disagrees with parsed log")
    if is_book_transition:
        if int(next_ai["stones_before"]) != int(focus["stones_before_next_engine_move"]):
            fail("book focus next stones disagrees with parsed log")
        if [int(next_ai["move_row"]), int(next_ai["move_col"])] != [
            int(value) for value in focus["next_engine_move"]
        ]:
            fail("book focus next move disagrees with parsed log")
        expected_seconds = float(focus["search_seconds_before_next_engine_move"])
        if abs(float(next_ai["search_seconds"]) - expected_seconds) > 1e-9:
            fail("book focus next search time disagrees with parsed log")
        return {
            focus_index: "book_transition_origin",
            int(next_index): "book_transition_destination",
        }
    if bool(focus.get("same_phase_transition")) != (
            phase(stones) == phase(int(next_ai["stones_before"]))):
        fail("focus same_phase_transition disagrees with parsed log")
    return {
        focus_index: "collapse_origin",
        int(next_index): "post_reply_position",
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
    parser.add_argument("--parsed", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="exclusive JSONL output")
    parser.add_argument("--manifest", required=True, type=Path, help="exclusive JSON manifest")
    parser.add_argument("--swing-threshold", type=float, default=3.0)
    parser.add_argument("--max-automatic", type=int, default=16)
    parser.add_argument(
        "--include-stones", action="append", default=[], metavar="MIN:MAX",
        help=(
            "force every non-pass AI position in this inclusive stone-count range; "
            "repeat for multiple ranges"
        ),
    )
    args = parser.parse_args()
    if args.swing_threshold <= 0 or args.max_automatic < 1:
        fail("swing-threshold and max-automatic must be positive")
    requested_ranges = [parse_stone_range(value) for value in args.include_stones]

    parsed_path = args.parsed.resolve()
    metadata_path = args.metadata.resolve()
    rows = load_jsonl(parsed_path)
    metadata = load_json(metadata_path)
    if metadata.get("usage") != "diagnostic_only":
        fail("metadata usage must be diagnostic_only")
    if metadata.get("training_eligible") is not False:
        fail("metadata training_eligible must be false")
    if metadata.get("adoption_gate_eligible") is not False:
        fail("metadata adoption_gate_eligible must be false")
    game_ids = {row["game_id"] for row in rows}
    if metadata.get("game_id") not in game_ids:
        fail("metadata game_id is absent from parsed records")
    for minimum, maximum in requested_ranges:
        matches = [
            row for row in rows
            if (
                row.get("is_ai_move") and not row.get("is_pass") and
                minimum <= int(row["stones_before"]) <= maximum
            )
        ]
        if not matches:
            fail(
                f"requested stone range {minimum}:{maximum} contains no non-pass AI position"
            )

    focus_roles = validate_focus(rows, metadata)
    candidates: list[tuple[int, float, list[str], str | None]] = []
    for index, current in enumerate(rows):
        if not current.get("is_ai_move") or current.get("is_pass"):
            continue
        next_index, next_ai, opponent, two_ply_reason = strict_two_ply_followup(
            rows, index
        )
        reasons = important_reasons(current, next_ai, args.swing_threshold)
        focus_role = None
        if index in focus_roles:
            focus_role = focus_roles[index]
            reasons.append("sidecar_pinned_focus")
            if focus_role == "collapse_origin":
                reasons.append("two_ply_collapse_origin")
            elif focus_role == "post_reply_position":
                reasons.append("two_ply_collapse_destination")
            elif focus_role == "book_transition_origin":
                reasons.append("book_hypothesis_origin")
            elif focus_role == "book_transition_destination":
                reasons.append("book_hypothesis_destination")
        stones = int(current["stones_before"])
        if any(minimum <= stones <= maximum for minimum, maximum in requested_ranges):
            reasons.append("requested_stone_range")
        if not reasons:
            continue
        swing = 0.0
        if next_ai is not None:
            left = current.get("evaluation_engine_disc_before_move")
            right = next_ai.get("evaluation_engine_disc_before_move")
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                swing = abs(float(right) - float(left))
        priority = 1_000_000.0 if focus_role else swing + (10.0 if "evaluation_sign_change" in reasons else 0.0)
        candidates.append((index, priority, reasons, focus_role))

    forced = [
        candidate for candidate in candidates
        if candidate[3] is not None or "requested_stone_range" in candidate[2]
    ]
    automatic = sorted(
        (
            candidate for candidate in candidates
            if candidate[3] is None and "requested_stone_range" not in candidate[2]
        ),
        key=lambda item: (-item[1], item[0]),
    )[:args.max_automatic]
    selected_by_index = {item[0]: item for item in forced + automatic}
    records: list[dict[str, Any]] = []
    for index in sorted(selected_by_index):
        _, _, reasons, focus_role = selected_by_index[index]
        next_index, next_ai, opponent, two_ply_reason = strict_two_ply_followup(
            rows, index
        )
        records.append(
            regression_record(
                rows[index], next_ai, opponent, reasons, focus_role, parsed_path,
                two_ply_reason,
            )
        )
    emitted_roles = {r["focus_role"] for r in records if r["focus_role"] is not None}
    if set(focus_roles.values()) != emitted_roles:
        fail("not every sidecar-pinned focus position was emitted")

    output_path = args.output.resolve()
    manifest_path = args.manifest.resolve()
    if output_path == manifest_path:
        fail("output and manifest paths collide")
    for path in (output_path, manifest_path):
        if path.exists():
            fail(f"refusing to overwrite existing output: {path}")
    output_text = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )
    manifest = {
        "schema": OUTPUT_SCHEMA,
        "source_parsed_jsonl": str(parsed_path),
        "source_parsed_sha256": sha256(parsed_path),
        "metadata_file": str(metadata_path),
        "metadata_sha256": sha256(metadata_path),
        "record_count": len(records),
        "focus_origin_count": sum(r["focus_role"] == "collapse_origin" for r in records),
        "focus_post_reply_count": sum(r["focus_role"] == "post_reply_position" for r in records),
        "book_transition_origin_count": sum(
            r["focus_role"] == "book_transition_origin" for r in records
        ),
        "book_transition_destination_count": sum(
            r["focus_role"] == "book_transition_destination" for r in records
        ),
        "selection": {
            "swing_threshold": args.swing_threshold,
            "max_automatic": args.max_automatic,
            "include_stones": [
                {"minimum": minimum, "maximum": maximum}
                for minimum, maximum in requested_ranges
            ],
            "requested_stone_range_forced_count": sum(
                "requested_stone_range" in record["importance_reasons"]
                for record in records
            ),
            "sidecar_focus_forced": bool(focus_roles),
        },
        "strict_two_ply_record_count": sum(
            bool(record["two_ply_sequence_valid"]) for record in records
        ),
        "two_ply_sequence_definition": STRICT_TWO_PLY_DEFINITION,
        "two_ply_unavailable_record_count": sum(
            not bool(record["two_ply_sequence_valid"]) for record in records
        ),
        "two_ply_unavailable_reasons": {
            reason: sum(record["two_ply_unavailable_reason"] == reason for record in records)
            for reason in sorted({
                record["two_ply_unavailable_reason"] for record in records
                if record["two_ply_unavailable_reason"] is not None
            })
        },
        "output": str(output_path),
        "diagnostic_only": True,
        "training_eligible": False,
        "adoption_gate_eligible": False,
        "warning": "These positions explain five observed games only; they are not training or adoption evidence.",
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
