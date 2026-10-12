#!/usr/bin/env python3
"""Verify the embedded CodinGame evaluator against the full-precision model.

The verifier creates deterministic, reachable Othello positions, compiles the
given Player.java into a temporary directory, and queries ``Player --eval`` in
one batch.  No source or model file is modified.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import importlib.util
import math
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
from types import ModuleType


BOARD_CELLS = 64
BOARD_SIZE = 8
PHASES = (0, 1, 2, 3)
DIRECTIONS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


class VerificationError(RuntimeError):
    """A clear validation, toolchain, or subprocess failure."""


@dataclass(frozen=True)
class Position:
    board: str
    player: int
    phase: int
    is_pass: bool


@dataclass(frozen=True)
class ReferenceResult:
    value: int
    raw: float
    phase: int
    mobility: int
    surround_black: int
    surround_white: int


@dataclass(frozen=True)
class JavaResult:
    value: int
    raw: float


class Progress:
    def __init__(self, total: int = 7, width: int = 24) -> None:
        self.total = total
        self.width = width
        self.current = 0

    def step(self, message: str) -> None:
        self.current += 1
        filled = self.width * self.current // self.total
        bar = "#" * filled + "." * (self.width - filled)
        print(
            f"[verify {self.current}/{self.total}] |{bar}| {message}",
            file=sys.stderr,
            flush=True,
        )


def initial_board() -> tuple[str, ...]:
    board = ["."] * BOARD_CELLS
    board[3 * BOARD_SIZE + 3] = "1"
    board[3 * BOARD_SIZE + 4] = "0"
    board[4 * BOARD_SIZE + 3] = "0"
    board[4 * BOARD_SIZE + 4] = "1"
    return tuple(board)


def flips_for_move(
    board: tuple[str, ...], player: int, place: int,
) -> tuple[int, ...]:
    if board[place] != ".":
        return ()
    own = str(player)
    opponent = str(1 - player)
    row, column = divmod(place, BOARD_SIZE)
    flips: list[int] = []
    for dy, dx in DIRECTIONS:
        y = row + dy
        x = column + dx
        line: list[int] = []
        while (
            0 <= y < BOARD_SIZE
            and 0 <= x < BOARD_SIZE
            and board[y * BOARD_SIZE + x] == opponent
        ):
            line.append(y * BOARD_SIZE + x)
            y += dy
            x += dx
        if (
            line
            and 0 <= y < BOARD_SIZE
            and 0 <= x < BOARD_SIZE
            and board[y * BOARD_SIZE + x] == own
        ):
            flips.extend(line)
    return tuple(flips)


def legal_moves(
    board: tuple[str, ...], player: int,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    moves = []
    for place, cell in enumerate(board):
        if cell != ".":
            continue
        flips = flips_for_move(board, player, place)
        if flips:
            moves.append((place, flips))
    return tuple(moves)


def play_move(
    board: tuple[str, ...],
    player: int,
    move: tuple[int, tuple[int, ...]],
) -> tuple[str, ...]:
    place, flips = move
    result = list(board)
    result[place] = str(player)
    for flipped in flips:
        result[flipped] = str(player)
    return tuple(result)


def phase_for_board(board: tuple[str, ...] | str) -> int:
    stones = BOARD_CELLS - board.count(".")
    return max(0, min(3, (stones - 4) // 10 - 2))


def phase_targets(count: int) -> dict[int, int]:
    base, remainder = divmod(count, len(PHASES))
    return {phase: base + (1 if phase < remainder else 0) for phase in PHASES}


def reachable_positions(
    count: int,
    seed: int,
    minimum_passes: int,
    max_games: int,
) -> list[Position]:
    """Return a deterministic, phase-stratified set of reachable positions."""

    if count < len(PHASES):
        raise VerificationError("--positions must be at least 4 to cover every phase")
    if not 0 <= minimum_passes <= count:
        raise VerificationError("--minimum-pass-positions must be in [0, positions]")

    targets = phase_targets(count)
    buckets: dict[int, list[Position]] = {phase: [] for phase in PHASES}
    pass_candidates: list[Position] = []
    seen: set[tuple[str, int]] = set()
    rng = random.Random(seed)

    for _game in range(max_games):
        board = initial_board()
        player = 0
        consecutive_passes = 0

        while consecutive_passes < 2:
            compact = "".join(board)
            moves = legal_moves(board, player)
            opponent_moves = legal_moves(board, 1 - player) if not moves else ()
            is_pass = not moves and bool(opponent_moves)
            key = (compact, player)
            if key not in seen:
                seen.add(key)
                phase = phase_for_board(board)
                position = Position(compact, player, phase, is_pass)
                if len(buckets[phase]) < targets[phase]:
                    buckets[phase].append(position)
                if is_pass:
                    pass_candidates.append(position)

            if (
                all(len(buckets[phase]) >= targets[phase] for phase in PHASES)
                and len(pass_candidates) >= minimum_passes
            ):
                break

            if not moves:
                consecutive_passes += 1
                player = 1 - player
                continue
            consecutive_passes = 0
            board = play_move(board, player, rng.choice(moves))
            player = 1 - player

        if (
            all(len(buckets[phase]) >= targets[phase] for phase in PHASES)
            and len(pass_candidates) >= minimum_passes
        ):
            break
    else:
        raise VerificationError(
            f"could not collect {count} positions and {minimum_passes} passes "
            f"within {max_games} random games"
        )

    selected_keys = {
        (position.board, position.player)
        for bucket in buckets.values()
        for position in bucket
    }
    selected_passes = sum(
        position.is_pass for bucket in buckets.values() for position in bucket
    )
    for candidate in pass_candidates:
        if selected_passes >= minimum_passes:
            break
        key = (candidate.board, candidate.player)
        if key in selected_keys:
            continue
        bucket = buckets[candidate.phase]
        replacement = next(
            (index for index in range(len(bucket) - 1, -1, -1)
             if not bucket[index].is_pass),
            None,
        )
        if replacement is None:
            continue
        old = bucket[replacement]
        selected_keys.remove((old.board, old.player))
        bucket[replacement] = candidate
        selected_keys.add(key)
        selected_passes += 1

    positions = [position for phase in PHASES for position in buckets[phase]]
    if len(positions) != count:
        raise AssertionError(f"generator produced {len(positions)} positions, expected {count}")
    if selected_passes < minimum_passes:
        raise VerificationError(
            f"only {selected_passes} pass positions were selected, expected {minimum_passes}"
        )
    if {position.phase for position in positions} != set(PHASES):
        raise AssertionError("phase-stratified generator lost a phase")
    return positions


def rotate90(board: str) -> str:
    return "".join(
        board[(7 - x) * BOARD_SIZE + y]
        for y in range(BOARD_SIZE)
        for x in range(BOARD_SIZE)
    )


def mirror(board: str) -> str:
    return "".join(
        board[y * BOARD_SIZE + 7 - x]
        for y in range(BOARD_SIZE)
        for x in range(BOARD_SIZE)
    )


def d4_variants(board: str) -> tuple[str, ...]:
    result: list[str] = []
    rotated = board
    for _ in range(4):
        result.extend((rotated, mirror(rotated)))
        rotated = rotate90(rotated)
    return tuple(result)


def stratified_subset(positions: list[Position], count: int) -> list[Position]:
    if not 0 <= count <= len(positions):
        raise VerificationError("--d4-positions must be in [0, positions]")
    targets = phase_targets(count)
    result: list[Position] = []
    for phase in PHASES:
        phase_positions = [position for position in positions if position.phase == phase]
        if len(phase_positions) < targets[phase]:
            raise VerificationError(f"not enough phase {phase} positions for D4 sample")
        result.extend(phase_positions[: targets[phase]])
    return result


def load_java_eval(training_root: Path) -> ModuleType:
    source = training_root / "training" / "wide_java_eval.py"
    if not source.is_file():
        raise VerificationError(f"wide_java_eval.py does not exist: {source}")
    spec = importlib.util.spec_from_file_location("othello13_reference_wide_java_eval", source)
    if spec is None or spec.loader is None:
        raise VerificationError(f"cannot load Python reference evaluator: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise VerificationError(f"failed to import {source}: {error}") from error
    return module


def reference_evaluate(module: ModuleType, evaluator: object, position: Position) -> ReferenceResult:
    encoded = module.encode_board(position.board, position.player)
    phase = evaluator.phase_index(encoded.stone_count)
    mobility = module._exact_canput(position.board, position.player)
    surround_black = min(module.MAX_SURROUND, evaluator._surround(encoded.lines, 0))
    surround_white = min(module.MAX_SURROUND, evaluator._surround(encoded.lines, 1))
    additions = evaluator.add_networks[phase].predict(
        mobility, surround_black, surround_white
    )
    dense = evaluator.all_dense[phase]
    raw = evaluator.all_bias[phase] + evaluator._calc_pattern(phase, encoded.lines)
    raw += sum(dense[11 + index] * value for index, value in enumerate(additions))
    if position.player != 0:
        raw = -raw
    value = int(max(-1.0, min(1.0, raw)) * module.SCORE_WEIGHT)
    return ReferenceResult(
        value, raw, phase, mobility, surround_black, surround_white
    )


def compile_player(
    player: Path,
    build_dir: Path,
    javac: str,
    timeout_seconds: float,
) -> None:
    if not player.is_file():
        raise VerificationError(f"Player source does not exist: {player}")
    command = [javac, "-encoding", "UTF-8", "-d", str(build_dir), str(player.resolve())]
    try:
        completed = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError(f"javac failed to run: {error}") from error
    if completed.returncode != 0:
        raise VerificationError(
            "javac failed\n"
            f"command={command!r}\n"
            f"stdout:\n{completed.stdout[-4000:]}\n"
            f"stderr:\n{completed.stderr[-8000:]}"
        )


def java_payload(positions: list[Position]) -> str:
    parts: list[str] = []
    for position in positions:
        parts.append(f"{position.player}\n")
        parts.extend(
            position.board[offset : offset + BOARD_SIZE] + "\n"
            for offset in range(0, BOARD_CELLS, BOARD_SIZE)
        )
    return "".join(parts)


def query_java(
    build_dir: Path,
    positions: list[Position],
    java: str,
    timeout_seconds: float,
) -> list[JavaResult]:
    command = [java, "-Xmx768m", "-cp", str(build_dir), "Player", "--eval"]
    try:
        completed = subprocess.run(
            command,
            input=java_payload(positions),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError(f"Player --eval failed to run: {error}") from error
    if completed.returncode != 0:
        raise VerificationError(
            "Player --eval failed\n"
            f"command={command!r}\n"
            f"stdout tail:\n{completed.stdout[-4000:]}\n"
            f"stderr tail:\n{completed.stderr[-8000:]}"
        )

    rows = [line.split() for line in completed.stdout.splitlines() if line.strip()]
    if len(rows) != len(positions):
        raise VerificationError(
            f"Player returned {len(rows)} rows for {len(positions)} positions; "
            f"stderr tail:\n{completed.stderr[-4000:]}"
        )

    results: list[JavaResult] = []
    for row_number, row in enumerate(rows, 1):
        if len(row) != 2:
            raise VerificationError(f"invalid Player --eval row {row_number}: {row!r}")
        try:
            value = int(row[0])
            raw = float(row[1])
        except ValueError as error:
            raise VerificationError(
                f"invalid numeric Player --eval row {row_number}: {row!r}"
            ) from error
        if not math.isfinite(raw):
            raise VerificationError(f"non-finite Java raw value at row {row_number}")
        results.append(JavaResult(value, raw))
    return results


def print_coverage(positions: list[Position], references: list[ReferenceResult]) -> None:
    phase_counts = Counter(result.phase for result in references)
    player_counts = Counter(position.player for position in positions)
    pass_counts = Counter(position.phase for position in positions if position.is_pass)
    stone_ranges: dict[int, tuple[int, int]] = {}
    for phase in PHASES:
        stones = [BOARD_CELLS - p.board.count(".") for p in positions if p.phase == phase]
        stone_ranges[phase] = (min(stones), max(stones))

    mobility = [result.mobility for result in references]
    surround_black = [result.surround_black for result in references]
    surround_white = [result.surround_white for result in references]
    print("Coverage:")
    print(f"  phases={dict(sorted(phase_counts.items()))} stone_ranges={stone_ranges}")
    print(f"  players={dict(sorted(player_counts.items()))} pass_by_phase={dict(sorted(pass_counts.items()))}")
    print(
        f"  mobility=[{min(mobility)},{max(mobility)}] "
        f"distinct={len(set(mobility))}"
    )
    print(
        f"  surround_black=[{min(surround_black)},{max(surround_black)}] "
        f"surround_white=[{min(surround_white)},{max(surround_white)}]"
    )


def verify(args: argparse.Namespace) -> bool:
    progress = Progress()
    progress.step("loading the full-precision Python evaluator")
    module = load_java_eval(args.training_root)
    try:
        evaluator = module.Evaluator(args.param)
    except Exception as error:
        raise VerificationError(f"cannot load reference parameters: {error}") from error

    progress.step(
        f"generating {args.positions:,} reachable phase-stratified positions"
    )
    positions = reachable_positions(
        args.positions, args.seed, args.minimum_pass_positions, args.max_games
    )
    d4_bases = stratified_subset(positions, args.d4_positions)
    d4_positions = [
        Position(variant, base.player, base.phase, base.is_pass)
        for base in d4_bases
        for variant in d4_variants(base.board)
    ]

    progress.step("evaluating the unquantized Python candidate")
    references = [reference_evaluate(module, evaluator, position) for position in positions]
    if any(result.phase != position.phase for result, position in zip(references, positions)):
        raise AssertionError("generator and evaluator phase calculations disagree")

    progress.step("compiling Player.java in a temporary directory")
    with tempfile.TemporaryDirectory(prefix="othello10-eval-") as temporary:
        build_dir = Path(temporary)
        compile_player(args.player, build_dir, args.javac, args.compile_timeout_seconds)

        progress.step(
            f"batch-querying Java for {len(positions) + len(d4_positions):,} positions"
        )
        java_results = query_java(
            build_dir,
            positions + d4_positions,
            args.java,
            args.eval_timeout_seconds,
        )

    progress.step("measuring quantization error and D4 invariance")
    main_java = java_results[: len(positions)]
    integer_errors = [
        abs(java_result.value - reference.value)
        for java_result, reference in zip(main_java, references)
    ]
    raw_errors = [
        abs(java_result.raw - reference.raw)
        for java_result, reference in zip(main_java, references)
    ]

    phase_errors: dict[int, list[int]] = {phase: [] for phase in PHASES}
    for position, error in zip(positions, integer_errors):
        phase_errors[position.phase].append(error)

    d4_java = java_results[len(positions) :]
    d4_integer_spans: list[int] = []
    d4_raw_spans: list[float] = []
    for index in range(len(d4_bases)):
        group = d4_java[index * 8 : index * 8 + 8]
        values = [item.value for item in group]
        raws = [item.raw for item in group]
        d4_integer_spans.append(max(values) - min(values))
        d4_raw_spans.append(max(raws) - min(raws))

    progress.step("applying evaluator acceptance criteria")
    integer_max = max(integer_errors, default=0)
    integer_mean = statistics.fmean(integer_errors) if integer_errors else 0.0
    raw_max = max(raw_errors, default=0.0)
    raw_mean = statistics.fmean(raw_errors) if raw_errors else 0.0
    d4_max_span = max(d4_integer_spans, default=0)
    selected_passes = sum(position.is_pass for position in positions)
    coverage_ok = (
        {position.phase for position in positions} == set(PHASES)
        and selected_passes >= args.minimum_pass_positions
    )

    checks = {
        "integer_max": integer_max <= args.max_integer_error,
        "integer_mean": integer_mean <= args.max_mean_integer_error,
        "d4_integer_span": d4_max_span == 0,
        "coverage": coverage_ok,
    }

    print("\n=== Evaluator verification ===")
    print(f"Main positions: {len(positions):,} (seed={args.seed})")
    print(f"D4 positions: {len(d4_bases):,} x 8 = {len(d4_positions):,}")
    print_coverage(positions, references)
    print("Integer error (Java units, 100 units = 1 disc):")
    print(
        f"  max={integer_max} (limit {args.max_integer_error}) "
        f"mean={integer_mean:.6f} (limit {args.max_mean_integer_error:.6f}) "
        f"mismatches={sum(error != 0 for error in integer_errors):,}"
    )
    for phase in PHASES:
        errors = phase_errors[phase]
        print(
            f"  phase {phase}: n={len(errors):,} max={max(errors)} "
            f"mean={statistics.fmean(errors):.6f}"
        )
    print("Raw error:")
    print(
        f"  max={raw_max:.12g} ({raw_max * 64:.6f} disc) "
        f"mean={raw_mean:.12g} ({raw_mean * 64:.6f} disc)"
    )
    print("D4:")
    print(
        f"  integer max span={d4_max_span} "
        f"raw max span={max(d4_raw_spans, default=0.0):.12g}"
    )
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'} {name}")

    passed = all(checks.values())
    print(f"\nFINAL: {'PASS' if passed else 'FAIL'}")
    return passed


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    project = default_project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player", type=Path, default=project / "Player.java")
    parser.add_argument("--param", type=Path, default=project / "model" / "param.txt")
    parser.add_argument(
        "--training-root",
        type=Path,
        default=Path(r"C:\Code\OthelloAI_13_training"),
    )
    parser.add_argument("--positions", type=int, default=4096)
    parser.add_argument("--d4-positions", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--minimum-pass-positions", type=int, default=8)
    parser.add_argument("--max-games", type=int, default=100_000)
    parser.add_argument("--max-integer-error", type=int, default=50)
    parser.add_argument("--max-mean-integer-error", type=float, default=10.0)
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--java", default="java")
    parser.add_argument("--compile-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--eval-timeout-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)
    if args.positions <= 0:
        parser.error("--positions must be positive")
    if args.d4_positions < 0:
        parser.error("--d4-positions must not be negative")
    if args.max_integer_error < 0 or args.max_mean_integer_error < 0:
        parser.error("error limits must not be negative")
    if args.compile_timeout_seconds <= 0 or args.eval_timeout_seconds <= 0:
        parser.error("timeouts must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return 0 if verify(args) else 1
    except VerificationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
