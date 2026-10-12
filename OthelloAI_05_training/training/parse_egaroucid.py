"""Validate and summarize Egaroucid board/score records inside the ZIP.

The archive is read directly with :mod:`zipfile`; no member is extracted.
By default only the first 10,000 records (in deterministic member-name order)
are checked.  ``--verify-all`` validates every record and checks the official
25,514,097-record stone-count distribution.

This module uses only Python's standard library and never requires a network
connection.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
import zipfile


ASSET_NAME = "Egaroucid_Train_Data.zip"
EXPECTED_RECORDS = 25_514_097
EXPECTED_STONE_COUNTS: dict[int, int] = {
    4: 1,
    5: 1,
    6: 3,
    7: 14,
    8: 60,
    9: 322,
    10: 1_773,
    11: 10_649,
    12: 67_245,
    13: 434_029,
    **{stones: 500_000 for stones in range(14, 64)},
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = PROJECT_ROOT / "data" / "raw" / ASSET_NAME
LINE_PATTERN = re.compile(rb"([XO-]{64}) ([+-]?[0-9]+)")
MIN_SCORE = -64
MAX_SCORE = 64


class DatasetError(RuntimeError):
    """A ZIP structure, record-format, or expected-count failure."""


@dataclass
class Statistics:
    records: int = 0
    score_sum: int = 0
    score_min: int | None = None
    score_max: int | None = None
    x_cells: int = 0
    o_cells: int = 0
    empty_cells: int = 0
    count_by_stones: Counter[int] = field(default_factory=Counter)
    count_by_score: Counter[int] = field(default_factory=Counter)
    records_by_member: Counter[str] = field(default_factory=Counter)

    def add(self, member: str, board: bytes, score: int) -> None:
        x_count = board.count(b"X")
        o_count = board.count(b"O")
        empty_count = board.count(b"-")
        stones = x_count + o_count
        self.records += 1
        self.score_sum += score
        self.score_min = score if self.score_min is None else min(self.score_min, score)
        self.score_max = score if self.score_max is None else max(self.score_max, score)
        self.x_cells += x_count
        self.o_cells += o_count
        self.empty_cells += empty_count
        self.count_by_stones[stones] += 1
        self.count_by_score[score] += 1
        self.records_by_member[member] += 1

    def as_json(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "scores": {
                "minimum": self.score_min,
                "maximum": self.score_max,
                "mean": self.score_sum / self.records if self.records else None,
                "sum": self.score_sum,
                "counts": ordered_counter(self.count_by_score),
            },
            "cells": {
                "X_player": self.x_cells,
                "O_opponent": self.o_cells,
                "empty": self.empty_cells,
            },
            "records_by_stone_count": ordered_counter(self.count_by_stones),
            "records_by_member": dict(sorted(self.records_by_member.items())),
        }


def ordered_counter(counter: Counter[int]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter)}


def parse_record(raw_line: bytes, member: str, line_number: int) -> tuple[bytes, int]:
    line = raw_line.rstrip(b"\r\n")
    match = LINE_PATTERN.fullmatch(line)
    if match is None:
        raise DatasetError(
            f"invalid record format at {member}:{line_number}; "
            "expected exactly 64 X/O/- cells, one space, and a signed integer score"
        )
    board, score_text = match.groups()
    score = int(score_text)
    if not MIN_SCORE <= score <= MAX_SCORE:
        raise DatasetError(
            f"score out of range at {member}:{line_number}: "
            f"expected [{MIN_SCORE}, {MAX_SCORE}], got {score}"
        )
    stones = board.count(b"X") + board.count(b"O")
    if not 4 <= stones <= 64:
        raise DatasetError(
            f"stone count out of range at {member}:{line_number}: expected [4, 64], got {stones}"
        )
    return board, score


def data_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = [
        info
        for info in archive.infolist()
        if not info.is_dir() and info.filename.lower().endswith(".txt")
    ]
    members.sort(key=lambda info: (info.filename.casefold(), info.filename))
    if not members:
        raise DatasetError("ZIP contains no .txt data members")
    encrypted = [info.filename for info in members if info.flag_bits & 0x1]
    if encrypted:
        raise DatasetError(f"encrypted ZIP members are not supported: {encrypted[0]}")
    duplicate_names = [name for name, count in Counter(info.filename for info in members).items() if count > 1]
    if duplicate_names:
        raise DatasetError(f"ZIP contains duplicate data member name: {duplicate_names[0]}")
    return members


def scan_open_archive(
    archive: zipfile.ZipFile, limit: int | None
) -> tuple[Statistics, dict[str, Any]]:
    statistics = Statistics()
    all_infos = archive.infolist()
    members = data_members(archive)
    archive_summary = {
        "all_members": len(all_infos),
        "data_members": len(members),
        "declared_uncompressed_data_bytes": sum(info.file_size for info in members),
        "declared_compressed_data_bytes": sum(info.compress_size for info in members),
    }
    for info in members:
        try:
            with archive.open(info, "r") as stream:
                for line_number, raw_line in enumerate(stream, 1):
                    board, score = parse_record(raw_line, info.filename, line_number)
                    statistics.add(info.filename, board, score)
                    if limit is not None and statistics.records >= limit:
                        break
        except (RuntimeError, NotImplementedError, OSError, zipfile.BadZipFile) as error:
            raise DatasetError(f"could not read ZIP member {info.filename}: {error}") from error
        if limit is not None and statistics.records >= limit:
            break
    if limit is not None and statistics.records != limit:
        raise DatasetError(
            f"archive ended before sample was complete: requested {limit}, got {statistics.records}"
        )
    return statistics, archive_summary


def scan_archive(path: Path, limit: int | None) -> tuple[Statistics, dict[str, Any]]:
    if not path.is_file():
        raise DatasetError(f"ZIP file does not exist: {path}")
    started = time.monotonic()
    try:
        with zipfile.ZipFile(path, "r") as archive:
            statistics, archive_summary = scan_open_archive(archive, limit)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise DatasetError(f"could not open ZIP {path}: {error}") from error

    archive_summary["elapsed_seconds"] = time.monotonic() - started
    return statistics, archive_summary


def verify_expected_counts(
    statistics: Statistics,
    *,
    expected_records: int = EXPECTED_RECORDS,
    expected_stone_counts: dict[int, int] = EXPECTED_STONE_COUNTS,
) -> None:
    if statistics.records != expected_records:
        raise DatasetError(
            f"record count mismatch: expected {expected_records:,}, got {statistics.records:,}"
        )
    actual = dict(statistics.count_by_stones)
    if actual != expected_stone_counts:
        keys = sorted(set(actual) | set(expected_stone_counts))
        differences = [
            f"{stones}: expected {expected_stone_counts.get(stones, 0):,}, "
            f"got {actual.get(stones, 0):,}"
            for stones in keys
            if actual.get(stones, 0) != expected_stone_counts.get(stones, 0)
        ]
        preview = "; ".join(differences[:8])
        if len(differences) > 8:
            preview += f"; ... ({len(differences)} differing stone counts)"
        raise DatasetError(f"stone-count distribution mismatch: {preview}")


def make_report(
    zip_path: Path,
    statistics: Statistics,
    archive_summary: dict[str, Any],
    mode: str,
    sample_size: int | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "verified",
        "mode": mode,
        "zip": {
            "path": str(zip_path.resolve()),
            "size": zip_path.stat().st_size,
            **archive_summary,
        },
        "format": {
            "board_cells": 64,
            "board_symbols": {"X": "player-to-move", "O": "opponent", "-": "empty"},
            "cell_order": "a1,b1,...,h1,a2,...,h8",
            "score": "signed integer from the player-to-move perspective",
        },
        "sample_size": sample_size,
        "expected_full_records": EXPECTED_RECORDS,
        "statistics": statistics.as_json(),
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    except OSError as error:
        raise DatasetError(f"could not write report {path}: {error}") from error


def run_self_test() -> None:
    boards = [
        b"XXOO" + b"-" * 60,
        b"XXXOO" + b"-" * 59,
        b"XXXOOO" + b"-" * 58,
    ]
    records = [
        boards[0] + b" +0\n",
        boards[1] + b" -12\r\n",
        boards[2] + b" 64\n",
    ]
    valid_buffer = io.BytesIO()
    with zipfile.ZipFile(valid_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("02/0000001.txt", b"".join(records[1:]))
        archive.writestr("01/0000000.txt", records[0])

    valid_buffer.seek(0)
    with zipfile.ZipFile(valid_buffer, "r") as archive:
        sample, _ = scan_open_archive(archive, limit=2)
    assert sample.records == 2
    assert sample.score_min == -12
    assert sample.count_by_stones == Counter({4: 1, 5: 1})

    valid_buffer.seek(0)
    with zipfile.ZipFile(valid_buffer, "r") as archive:
        full, _ = scan_open_archive(archive, limit=None)
    verify_expected_counts(
        full,
        expected_records=3,
        expected_stone_counts={4: 1, 5: 1, 6: 1},
    )
    try:
        verify_expected_counts(
            full,
            expected_records=4,
            expected_stone_counts={4: 1, 5: 1, 6: 1},
        )
    except DatasetError:
        pass
    else:
        raise AssertionError("full-record count mismatch was not detected")

    try:
        parse_record(boards[0] + b" 65\n", "score.txt", 1)
    except DatasetError:
        pass
    else:
        raise AssertionError("out-of-range score was not rejected")

    invalid_buffer = io.BytesIO()
    with zipfile.ZipFile(invalid_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bad.txt", b"not-a-board 0\n")
    invalid_buffer.seek(0)
    try:
        with zipfile.ZipFile(invalid_buffer, "r") as archive:
            scan_open_archive(archive, limit=1)
    except DatasetError:
        pass
    else:
        raise AssertionError("invalid record was not rejected")
    print("parse_egaroucid: self-test passed")


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Egaroucid board/score data directly inside its ZIP. "
            "No files are extracted and no network access is used."
        )
    )
    parser.add_argument(
        "zip_path",
        nargs="?",
        type=Path,
        default=DEFAULT_ZIP,
        help=f"archive to inspect (default: {DEFAULT_ZIP})",
    )
    parser.add_argument(
        "--sample-size",
        type=positive_int,
        default=10_000,
        help="records to validate in sample mode (default: 10000)",
    )
    parser.add_argument(
        "--verify-all",
        action="store_true",
        help=(
            "scan all members and require exactly 25,514,097 records with the official "
            "stone-count distribution"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON statistics report path (stdout is always used as well)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run network-free in-memory-format and ZIP-scanning tests",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.self_test:
            run_self_test()
            return 0
        limit = None if args.verify_all else args.sample_size
        statistics, archive_summary = scan_archive(args.zip_path, limit)
        if args.verify_all:
            verify_expected_counts(statistics)
        report = make_report(
            args.zip_path,
            statistics,
            archive_summary,
            "full" if args.verify_all else "sample",
            None if args.verify_all else args.sample_size,
        )
        if args.output is not None:
            write_json_atomic(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (DatasetError, AssertionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
