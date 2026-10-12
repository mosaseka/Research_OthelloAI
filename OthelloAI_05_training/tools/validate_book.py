#!/usr/bin/env python3
"""Validate resources/book.txt without relying on the Java engine.

The compressed book starts after Black's fixed (4, 5) opening.  Each record is
encoded as zero or more history-coordinate characters, one ASCII space, and one
recommended-coordinate character.  A character's index in ``BOOK_ALPHABET`` is
the row-major square number ``y * 8 + x``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Sequence

if __package__:
    from .arena import BLACK, WHITE, apply_move, board_rows, initial_board
else:
    from arena import BLACK, WHITE, apply_move, board_rows, initial_board


BOOK_ALPHABET = "!#$&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abc"
BOOK_SEPARATOR = " "
FIXED_FIRST_MOVE = (4, 5)

REFERENCE_COUNTS = {
    "record_count": 4_915,
    "min_history_length": 0,
    "max_history_length": 44,
    "registration_attempts": 19_660,
    "distinct_positions": 17_480,
    "duplicate_policy_entries": 1_868,
    "max_policies_per_position": 4,
}


class BookFormatError(ValueError):
    """A compressed book cannot be divided into complete records."""

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.position = position


@dataclass(frozen=True)
class BookRecord:
    history: tuple[int, ...]
    policy: int
    start: int
    policy_position: int


def square(square_index: int) -> tuple[int, int]:
    return divmod(square_index, 8)


def parse_records(text: str) -> list[BookRecord]:
    """Parse the Java loader's compact record grammar, with strict bounds checks."""
    if not text:
        raise BookFormatError("book is empty", 0)
    if "\r" in text or "\n" in text:
        newline_positions = [pos for pos, char in enumerate(text) if char in "\r\n"]
        raise BookFormatError(
            "book must be exactly one line with no terminal newline",
            newline_positions[0],
        )

    alphabet_index = {char: index for index, char in enumerate(BOOK_ALPHABET)}
    allowed = set(BOOK_ALPHABET) | {BOOK_SEPARATOR}
    for position, char in enumerate(text):
        if char not in allowed:
            raise BookFormatError(
                f"character {char!r} is not in the coordinate alphabet",
                position,
            )

    records: list[BookRecord] = []
    position = 0
    while position < len(text):
        start = position
        history: list[int] = []
        while position < len(text) and text[position] != BOOK_SEPARATOR:
            history.append(alphabet_index[text[position]])
            position += 1

        if position == len(text):
            raise BookFormatError("record has no history/policy separator", position)

        position += 1
        policy_position = position
        if position == len(text):
            raise BookFormatError("record ends after its separator", position)
        if text[position] == BOOK_SEPARATOR:
            raise BookFormatError("policy must be one coordinate character", position)

        policy = alphabet_index[text[position]]
        position += 1
        records.append(BookRecord(tuple(history), policy, start, policy_position))

    return records


def transform_coordinate(square_index: int, symmetry: int) -> int:
    """Apply one of the four transformations registered by OthelloAI_05."""
    y, x = square(square_index)
    transforms = (
        (y, x),
        (x, y),
        (7 - x, 7 - y),
        (7 - y, 7 - x),
    )
    transformed_y, transformed_x = transforms[symmetry]
    return transformed_y * 8 + transformed_x


def transform_board(board: Sequence[int], symmetry: int) -> tuple[int, ...]:
    transformed = [-1] * 64
    for square_index, cell in enumerate(board):
        transformed[transform_coordinate(square_index, symmetry)] = cell
    return tuple(transformed)


def _record_error(
    record_index: int,
    kind: str,
    move_index: int,
    player: int,
    record: BookRecord,
) -> dict[str, object]:
    y, x = square(move_index)
    return {
        "record": record_index,
        "kind": kind,
        "player": "black" if player == BLACK else "white",
        "square_index": move_index,
        "move": [y, x],
        "record_start": record.start,
        "policy_position": record.policy_position,
    }


def validate_book(book_path: Path, check_reference_counts: bool = True) -> dict[str, object]:
    raw = book_path.read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise BookFormatError("book is not ASCII", error.start) from error

    records = parse_records(text)

    base_board = apply_move(initial_board(), BLACK, FIXED_FIRST_MOVE)
    history_lengths: list[int] = []
    history_moves_checked = 0
    policy_moves_checked = 0
    history_errors: list[dict[str, object]] = []
    policy_errors: list[dict[str, object]] = []
    registrations: dict[tuple[int, ...], list[int]] = defaultdict(list)

    for record_index, record in enumerate(records):
        history_lengths.append(len(record.history))
        board = base_board
        player = WHITE
        history_valid = True

        for move_index in record.history:
            history_moves_checked += 1
            move = square(move_index)
            try:
                board = apply_move(board, player, move)
            except ValueError:
                history_errors.append(
                    _record_error(record_index, "history", move_index, player, record)
                )
                history_valid = False
                break
            player ^= 1

        if not history_valid:
            continue

        policy_moves_checked += 1
        policy_move = square(record.policy)
        try:
            apply_move(board, player, policy_move)
        except ValueError:
            policy_errors.append(
                _record_error(record_index, "policy", record.policy, player, record)
            )
            continue

        for symmetry in range(4):
            transformed_board = transform_board(board, symmetry)
            transformed_policy = transform_coordinate(record.policy, symmetry)
            registrations[transformed_board].append(transformed_policy)

    policy_entry_counts = [len(policies) for policies in registrations.values()]
    unique_policy_counts = [len(set(policies)) for policies in registrations.values()]
    registration_attempts = sum(policy_entry_counts)
    duplicate_policy_entries = sum(
        len(policies) - len(set(policies)) for policies in registrations.values()
    )

    min_history_length = min(history_lengths) if history_lengths else None
    max_history_length = max(history_lengths) if history_lengths else None
    counts = {
        "record_count": len(records),
        "min_history_length": min_history_length,
        "max_history_length": max_history_length,
        "registration_attempts": registration_attempts,
        "distinct_positions": len(registrations),
        "duplicate_policy_entries": duplicate_policy_entries,
        "max_policies_per_position": max(policy_entry_counts, default=0),
    }

    reference_mismatches: list[dict[str, object]] = []
    if check_reference_counts:
        for name, expected in REFERENCE_COUNTS.items():
            actual = counts[name]
            if actual != expected:
                reference_mismatches.append(
                    {"field": name, "expected": expected, "actual": actual}
                )

    valid = not history_errors and not policy_errors and not reference_mismatches
    summary: dict[str, object] = {
        "valid": valid,
        "book": str(book_path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "format": {
            "encoding": "ascii",
            "byte_count": len(raw),
            "character_count": len(text),
            "line_break_count": text.count("\n") + text.count("\r"),
            "terminal_newline": text.endswith(("\n", "\r")),
            "separator_count": text.count(BOOK_SEPARATOR),
            "alphabet": BOOK_ALPHABET,
            "alphabet_size": len(BOOK_ALPHABET),
            "last_character": text[-1] if text else None,
            "complete_terminal_record": bool(text and text[-1] in BOOK_ALPHABET),
        },
        "base_position": {
            "fixed_first_move": list(FIXED_FIRST_MOVE),
            "next_player": "white",
            "rows": board_rows(base_board),
        },
        "records": {
            "count": len(records),
            "history_moves_checked": history_moves_checked,
            "policy_moves_checked": policy_moves_checked,
            "min_history_length": min_history_length,
            "max_history_length": max_history_length,
            "mean_history_length": fmean(history_lengths) if history_lengths else None,
            "history_length_histogram": {
                str(length): count
                for length, count in sorted(Counter(history_lengths).items())
            },
        },
        "legality": {
            "history_error_count": len(history_errors),
            "policy_error_count": len(policy_errors),
            "history_errors": history_errors[:50],
            "policy_errors": policy_errors[:50],
            "errors_truncated": len(history_errors) > 50 or len(policy_errors) > 50,
        },
        "symmetry_registration": {
            "symmetry_count": 4,
            "registration_attempts": registration_attempts,
            "distinct_positions": len(registrations),
            "unique_position_policy_pairs": sum(unique_policy_counts),
            "duplicate_policy_entries": duplicate_policy_entries,
            "max_policies_per_position": max(policy_entry_counts, default=0),
            "max_unique_policies_per_position": max(unique_policy_counts, default=0),
            "policy_entry_count_histogram": {
                str(count): positions
                for count, positions in sorted(Counter(policy_entry_counts).items())
            },
            "unique_policy_count_histogram": {
                str(count): positions
                for count, positions in sorted(Counter(unique_policy_counts).items())
            },
        },
        "reference_checks": {
            "enabled": check_reference_counts,
            "expected": REFERENCE_COUNTS if check_reference_counts else None,
            "mismatches": reference_mismatches,
        },
    }
    return summary


def make_argument_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Strictly validate the compressed Othello opening book."
    )
    parser.add_argument(
        "--book",
        type=Path,
        default=project_root / "resources" / "book.txt",
        help="compressed book path (default: resources/book.txt)",
    )
    parser.add_argument(
        "--no-reference-checks",
        action="store_true",
        help="accept structurally valid alternative books with different aggregate counts",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print the JSON summary",
    )
    return parser


def _error_summary(book_path: Path, error: Exception) -> dict[str, object]:
    summary: dict[str, object] = {
        "valid": False,
        "book": str(book_path.resolve()),
        "error": {
            "type": type(error).__name__,
            "message": str(error),
        },
    }
    if isinstance(error, BookFormatError):
        summary["error"]["position"] = error.position  # type: ignore[index]
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = make_argument_parser().parse_args(argv)
    try:
        summary = validate_book(
            args.book,
            check_reference_counts=not args.no_reference_checks,
        )
    except (OSError, BookFormatError) as error:
        summary = _error_summary(args.book, error)

    indent = 2 if args.pretty else None
    print(json.dumps(summary, ensure_ascii=False, indent=indent, sort_keys=True))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
