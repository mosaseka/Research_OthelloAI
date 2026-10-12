#!/usr/bin/env python3
"""Parse concatenated Client opponent logs into diagnostic-only records.

The logs produced by the course Client may contain an entire game on one
physical line.  This parser therefore recognizes the board grammar instead of
depending on line breaks.  Every board transition is replayed with an
independent Othello move implementation before any output is committed.
Repeated snapshots are accepted only as an explicit, legally validated pass;
the pass record has nullable move coordinates.

The generated files are deliberately a diagnostic schema.  They are not a
training-data converter and every record carries ``training_eligible=false``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "original-11-opponent-log-diagnostic-v1"
CELL = r"([.XO])"
BOARD_PATTERN = r"A\s+B\s+C\s+D\s+E\s+F\s+G\s+H\s*"
for _row in range(1, 9):
    BOARD_PATTERN += str(_row) + r"\s+" + r"\s+".join([CELL] * 8) + r"\s*"
BOARD_PATTERN += r"Black\s+X\s+(\d+)\s*-\s*(\d+)\s+O\s+White"
BOARD_RE = re.compile(BOARD_PATTERN, re.IGNORECASE)
START_RE = re.compile(r"START\s+(BLACK|WHITE)", re.IGNORECASE)
PUT_RE = re.compile(r"PUT\s+(-?\d+)\s+(-?\d+)", re.IGNORECASE)
EVAL_RE = re.compile(r"AI評価値\s*:\s*([+-]?\d+(?:\.\d+)?)")
TIME_RE = re.compile(r"Searching\s*\[[^\]]*\]\s*([0-9]+(?:\.[0-9]+)?)\s*s", re.IGNORECASE)


@dataclass(frozen=True)
class BoardSnapshot:
    board: str
    black: int
    white: int
    start: int
    end: int


def fail(message: str) -> "NoReturn":
    raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read metadata {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"metadata must be a JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_metadata(metadata: dict[str, Any], metadata_path: Path, source: Path) -> None:
    if metadata.get("usage") != "diagnostic_only":
        fail(f"{metadata_path}: usage must be diagnostic_only")
    if metadata.get("training_eligible") is not False:
        fail(f"{metadata_path}: training_eligible must be false")
    if metadata.get("adoption_gate_eligible") is not False:
        fail(f"{metadata_path}: adoption_gate_eligible must be false")
    declared = metadata.get("source_file")
    if declared != source.name:
        fail(f"{metadata_path}: source_file={declared!r}, expected {source.name!r}")
    colour = str(metadata.get("engine_colour", "")).lower()
    if colour not in {"black", "white"}:
        fail(f"{metadata_path}: engine_colour must be black or white")


def parse_board(match: re.Match[str]) -> BoardSnapshot:
    groups = match.groups()
    cells = "".join(groups[:64]).upper()
    black = int(groups[64])
    white = int(groups[65])
    if cells.count("X") != black or cells.count("O") != white:
        fail(
            f"board count mismatch near character {match.start()}: "
            f"grid X/O={cells.count('X')}/{cells.count('O')}, label={black}/{white}"
        )
    if black + white + cells.count(".") != 64:
        fail(f"invalid board near character {match.start()}")
    return BoardSnapshot(cells, black, white, match.start(), match.end())


DIRECTIONS = ((-1, -1), (-1, 0), (-1, 1), (0, -1),
              (0, 1), (1, -1), (1, 0), (1, 1))


def apply_move(board: str, player: str, row: int, col: int) -> str | None:
    if not (0 <= row < 8 and 0 <= col < 8) or board[row * 8 + col] != ".":
        return None
    opponent = "O" if player == "X" else "X"
    flips: list[int] = []
    for dr, dc in DIRECTIONS:
        r, c = row + dr, col + dc
        ray: list[int] = []
        while 0 <= r < 8 and 0 <= c < 8 and board[r * 8 + c] == opponent:
            ray.append(r * 8 + c)
            r += dr
            c += dc
        if ray and 0 <= r < 8 and 0 <= c < 8 and board[r * 8 + c] == player:
            flips.extend(ray)
    if not flips:
        return None
    result = list(board)
    result[row * 8 + col] = player
    for index in flips:
        result[index] = player
    return "".join(result)


def has_legal_move(board: str, player: str) -> bool:
    for index, cell in enumerate(board):
        if cell == "." and apply_move(board, player, index // 8, index % 8) is not None:
            return True
    return False


def infer_and_validate_transition(
    before: BoardSnapshot,
    after: BoardSnapshot,
    expected_player: str,
    supplied_move: tuple[int, int] | None,
    context: str,
) -> tuple[int | None, int | None, bool]:
    if before.board == after.board:
        if before.black != after.black or before.white != after.white:
            fail(f"{context}: repeated board has inconsistent counts")
        if supplied_move not in {None, (-1, -1)}:
            fail(f"{context}: pass has invalid PUT {supplied_move}")
        if has_legal_move(before.board, expected_player):
            fail(f"{context}: pass is illegal because the mover has a legal move")
        opponent = "O" if expected_player == "X" else "X"
        if not has_legal_move(before.board, opponent):
            fail(f"{context}: repeated terminal board is not a single-player pass")
        return None, None, True
    placements = [
        index for index, (old, new) in enumerate(zip(before.board, after.board))
        if old == "." and new != "."
    ]
    if len(placements) != 1:
        fail(f"{context}: expected one newly occupied cell, got {placements}")
    index = placements[0]
    row, col = divmod(index, 8)
    if after.board[index] != expected_player:
        fail(
            f"{context}: placed {after.board[index]}, expected {expected_player} "
            f"at ({row},{col})"
        )
    if supplied_move is not None and supplied_move != (row, col):
        fail(f"{context}: PUT {supplied_move} disagrees with board move {(row, col)}")
    replayed = apply_move(before.board, expected_player, row, col)
    if replayed is None:
        fail(f"{context}: inferred move ({row},{col}) is illegal")
    if replayed != after.board:
        fail(f"{context}: board after move does not match legal Othello replay")
    if after.black + after.white != before.black + before.white + 1:
        fail(f"{context}: disc total did not increase by exactly one")
    return row, col, False


def board_matches(segment: str) -> list[BoardSnapshot]:
    return [parse_board(match) for match in BOARD_RE.finditer(segment)]


def parse_game(segment: str, metadata: dict[str, Any], game_index: int) -> list[dict[str, Any]]:
    start_match = START_RE.search(segment)
    if start_match is None:
        fail(f"game {game_index}: START BLACK/WHITE not found")
    declared_start = start_match.group(1).lower()
    engine_colour = str(metadata["engine_colour"]).lower()
    if declared_start != engine_colour:
        fail(
            f"game {game_index}: START says {declared_start}, metadata says {engine_colour}"
        )
    boards = board_matches(segment)
    if len(boards) < 2:
        fail(f"game {game_index}: expected at least two board snapshots")

    game_id_base = str(metadata.get("game_id") or f"game_{game_index:03d}")
    game_id = game_id_base if game_index == 1 else f"{game_id_base}_{game_index:03d}"
    engine_token = "X" if engine_colour == "black" else "O"
    opponent_token = "O" if engine_token == "X" else "X"
    final_difference = int(metadata["final_disc_difference_engine"])
    final_result = "win" if final_difference > 0 else ("loss" if final_difference < 0 else "draw")
    final_discs = metadata.get("final_discs") or {}
    rows: list[dict[str, Any]] = []
    for transition_index in range(1, len(boards)):
        before = boards[transition_index - 1]
        after = boards[transition_index]
        event = segment[before.end:after.start]
        is_ai = "YOUR TURN" in event.upper()
        is_opponent = "OPPONENT TURN" in event.upper()
        if is_ai == is_opponent:
            fail(
                f"{game_id} transition {transition_index}: cannot uniquely determine mover"
            )
        expected = engine_token if is_ai else opponent_token
        repeated_board = before.board == after.board
        put_matches = list(PUT_RE.finditer(event))
        if is_ai and not repeated_board and len(put_matches) != 1:
            fail(
                f"{game_id} transition {transition_index}: AI transition requires one PUT"
            )
        if is_ai and repeated_board and len(put_matches) > 1:
            fail(
                f"{game_id} transition {transition_index}: AI pass has ambiguous PUT markers"
            )
        if not is_ai and put_matches:
            fail(
                f"{game_id} transition {transition_index}: opponent transition contains PUT"
            )
        supplied = None
        if put_matches:
            supplied = (int(put_matches[0].group(1)), int(put_matches[0].group(2)))
        row, col, is_pass = infer_and_validate_transition(
            before, after, expected, supplied,
            f"{game_id} transition {transition_index}",
        )
        eval_matches = list(EVAL_RE.finditer(event))
        time_matches = list(TIME_RE.finditer(event))
        if is_ai and not is_pass and len(eval_matches) != 1:
            fail(
                f"{game_id} transition {transition_index}: AI evaluation is missing or ambiguous"
            )
        if is_ai and not is_pass and len(time_matches) != 1:
            fail(
                f"{game_id} transition {transition_index}: search time is missing or ambiguous"
            )
        if is_ai and is_pass and (len(eval_matches) > 1 or len(time_matches) > 1):
            fail(
                f"{game_id} transition {transition_index}: AI pass diagnostics are ambiguous"
            )
        rows.append({
            "schema": SCHEMA,
            "game_id": game_id,
            "transition_index": transition_index,
            "ply": transition_index,
            "ply_from_initial_log_board": transition_index,
            "stones_before": before.black + before.white,
            "stones": before.black + before.white,
            "empties_before": 64 - before.black - before.white,
            "empties": 64 - before.black - before.white,
            "side_to_move": "black" if expected == "X" else "white",
            "side": "black" if expected == "X" else "white",
            "player": 0 if expected == "X" else 1,
            "is_ai_move": is_ai,
            "is_ai": is_ai,
            "is_pass": is_pass,
            "board_before": before.board,
            "board": before.board,
            "board_after": after.board,
            "move": None if is_pass else [row, col],
            "move_row": row,
            "move_col": col,
            "move_algebraic": None if is_pass else chr(ord("A") + col) + str(row + 1),
            "evaluation_engine_disc_before_move": (
                float(eval_matches[0].group(1)) if eval_matches else None
            ),
            "ai_eval_disc": (
                float(eval_matches[0].group(1)) if eval_matches else None
            ),
            "search_seconds": float(time_matches[0].group(1)) if time_matches else None,
            "black_before": before.black,
            "white_before": before.white,
            "black_after": after.black,
            "white_after": after.white,
            "engine": metadata.get("engine"),
            "engine_colour": engine_colour,
            "source_game_result_engine_disc_difference": metadata.get(
                "final_disc_difference_engine"
            ),
            "source_game_result_engine": final_result,
            "final_result_engine": final_result,
            "final_engine_discs": final_discs.get("engine"),
            "final_opponent_discs": final_discs.get("opponent"),
            "diagnostic_only": True,
            "training_eligible": False,
            "adoption_gate_eligible": False,
        })

    final_expected = metadata.get("final_discs")
    if isinstance(final_expected, dict):
        last = boards[-1]
        actual_engine = last.black if engine_colour == "black" else last.white
        actual_opponent = last.white if engine_colour == "black" else last.black
        if final_expected.get("engine") != actual_engine or final_expected.get("opponent") != actual_opponent:
            fail(
                f"{game_id}: final board {actual_engine}-{actual_opponent} disagrees with metadata"
            )
        if int(metadata["final_disc_difference_engine"]) != actual_engine - actual_opponent:
            fail(f"{game_id}: final_disc_difference_engine disagrees with final board")
    return rows


def split_games(text: str) -> list[str]:
    starts = list(START_RE.finditer(text))
    if not starts:
        fail("no START BLACK/WHITE marker found")
    return [
        text[match.start():(starts[index + 1].start() if index + 1 < len(starts) else len(text))]
        for index, match in enumerate(starts)
    ]


def write_exclusive_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except FileExistsError:
        fail(f"refusing to overwrite existing output: {path}")


def json_lines(records: Iterable[dict[str, Any]]) -> str:
    return "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="raw Client log")
    parser.add_argument("--metadata", type=Path, help="diagnostic sidecar JSON")
    parser.add_argument(
        "--output-prefix", required=True, type=Path,
        help="exclusive output prefix; .csv/.jsonl/_summary.json are created",
    )
    args = parser.parse_args()

    source = args.input.resolve()
    metadata_path = (
        args.metadata.resolve() if args.metadata else
        source.with_name(source.name.replace("_raw.txt", "_metadata.json"))
    )
    metadata = load_json(metadata_path)
    validate_metadata(metadata, metadata_path, source)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read raw log {source}: {exc}")

    records: list[dict[str, Any]] = []
    for game_index, segment in enumerate(split_games(text), 1):
        records.extend(parse_game(segment, metadata, game_index))
    if not records:
        fail("no moves were parsed")

    prefix = args.output_prefix.resolve()
    csv_path = Path(str(prefix) + ".csv")
    jsonl_path = Path(str(prefix) + ".jsonl")
    summary_path = Path(str(prefix) + "_summary.json")
    if len({csv_path, jsonl_path, summary_path}) != 3:
        fail("output paths collide")
    for path in (csv_path, jsonl_path, summary_path):
        if path.exists():
            fail(f"refusing to overwrite existing output: {path}")

    csv_fields = list(records[0].keys())
    csv_lines: list[str] = []
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=csv_fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    csv_content = buffer.getvalue()
    summary = {
        "schema": SCHEMA,
        "source_file": str(source),
        "source_sha256": sha256(source),
        "metadata_file": str(metadata_path),
        "metadata_sha256": sha256(metadata_path),
        "game_ids": sorted({record["game_id"] for record in records}),
        "transitions": len(records),
        "moves": sum(not bool(record["is_pass"]) for record in records),
        "passes": sum(bool(record["is_pass"]) for record in records),
        "ai_moves": sum(bool(record["is_ai_move"]) for record in records),
        "all_transitions_legally_replayed": True,
        "source_game_result_engine": records[0]["source_game_result_engine"],
        "source_game_result_engine_disc_difference": records[0][
            "source_game_result_engine_disc_difference"
        ],
        "final_engine_discs": records[0]["final_engine_discs"],
        "final_opponent_discs": records[0]["final_opponent_discs"],
        "diagnostic_only": True,
        "training_eligible": False,
        "adoption_gate_eligible": False,
        "outputs": {
            "csv": str(csv_path),
            "jsonl": str(jsonl_path),
        },
    }
    write_exclusive_text(csv_path, csv_content)
    write_exclusive_text(jsonl_path, json_lines(records))
    write_exclusive_text(
        summary_path, json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
