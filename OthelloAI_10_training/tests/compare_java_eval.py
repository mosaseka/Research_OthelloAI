"""Compare exact-mobility-v1 Python and original_10 Java evaluation.

The script compiles the unchanged runtime source together with the test-only
bridge in a temporary directory.  The bridge loads ``--param`` directly as an
exact-mobility candidate; no model bundle is needed.

Acceptance criteria:

* all final integer scores are exactly equal;
* phase, signed exact mobility, and both surround features are exactly equal;
* clamped pre-cast values differ by no more than ``--tolerance``.
"""

from __future__ import annotations

import argparse
from collections import Counter
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_DIR = PROJECT_ROOT / "training"
sys.path.insert(0, str(TRAINING_DIR))

from java_eval import Evaluator, FEATURE_SCHEMA  # noqa: E402


EXPECTED_FEATURE_SCHEMA = "exact-mobility-v1"
DEFAULT_AI_SOURCE = Path(
    os.environ.get(
        "OTHELLO_AI_SOURCE",
        str(
            Path.home()
            / "Box"
            / "01_授業関連"
            / "3-1"
            / "計算機科学応用演習"
            / "2026_1"
            / "0_課題"
            / "2026_07_15_ネットワークプログラミング"
            / "original_10"
            / "OthelloAI_10.java"
        ),
    )
)

DIRECTIONS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)

JavaResult = tuple[int, float, int, int, int, int]
Position = tuple[str, int]


def initial_board() -> tuple[str, ...]:
    board = ["."] * 64
    board[3 * 8 + 3] = "1"
    board[3 * 8 + 4] = "0"
    board[4 * 8 + 3] = "0"
    board[4 * 8 + 4] = "1"
    return tuple(board)


def flips_for_move(
    board: tuple[str, ...], player: int, place: int,
) -> tuple[int, ...]:
    if board[place] != ".":
        return ()
    own = str(player)
    opponent = str(1 - player)
    row, column = divmod(place, 8)
    flips: list[int] = []
    for dy, dx in DIRECTIONS:
        y = row + dy
        x = column + dx
        line: list[int] = []
        while (
            0 <= y < 8
            and 0 <= x < 8
            and board[y * 8 + x] == opponent
        ):
            line.append(y * 8 + x)
            y += dy
            x += dx
        if (
            line
            and 0 <= y < 8
            and 0 <= x < 8
            and board[y * 8 + x] == own
        ):
            flips.extend(line)
    return tuple(flips)


def legal_moves(
    board: tuple[str, ...], player: int,
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    result = []
    for place, cell in enumerate(board):
        if cell != ".":
            continue
        flips = flips_for_move(board, player, place)
        if flips:
            result.append((place, flips))
    return tuple(result)


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


def random_reachable_positions(count: int, seed: int) -> list[Position]:
    if count <= 0:
        raise ValueError("position count must be positive")
    rng = random.Random(seed)
    result: list[Position] = []
    seen: set[Position] = set()

    while len(result) < count:
        board = initial_board()
        player = 0
        consecutive_passes = 0
        while consecutive_passes < 2 and len(result) < count:
            compact = "".join(board)
            key = (compact, player)
            if key not in seen:
                seen.add(key)
                result.append(key)
            moves = legal_moves(board, player)
            if not moves:
                consecutive_passes += 1
                player = 1 - player
                continue
            consecutive_passes = 0
            board = play_move(board, player, rng.choice(moves))
            player = 1 - player
    return result


def compile_bridge(
    build_dir: Path,
    javac: str,
    ai_source: Path,
    timeout: float,
) -> None:
    source = ai_source.expanduser().resolve()
    bridge = PROJECT_ROOT / "tests" / "JavaEvalBridge10.java"
    if not source.is_file():
        raise FileNotFoundError(
            f"original_10 Java source does not exist: {source}; "
            "pass --ai-source or set OTHELLO_AI_SOURCE"
        )
    if source.name != "OthelloAI_10.java":
        raise ValueError(
            f"--ai-source must name OthelloAI_10.java, got {source.name}"
        )
    if not bridge.is_file():
        raise FileNotFoundError(f"Java bridge does not exist: {bridge}")

    command = [
        javac,
        "-encoding", "UTF-8",
        "-d", str(build_dir),
        str(source),
        str(bridge),
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "javac failed\n"
            f"command={command!r}\n"
            f"stdout:\n{completed.stdout[-8000:]}\n"
            f"stderr:\n{completed.stderr[-8000:]}"
        )


def query_java(
    build_dir: Path,
    java: str,
    param_path: Path,
    positions: Sequence[Position],
    timeout: float,
) -> list[JavaResult]:
    payload = "".join(f"{player}\t{board}\n" for board, player in positions)
    command = [
        java,
        "-Xmx1g",
        "-cp", str(build_dir),
        "JavaEvalBridge10",
        str(param_path.resolve()),
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        input=payload,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Java bridge failed\n"
            f"command={command!r}\n"
            f"stdout:\n{completed.stdout[-8000:]}\n"
            f"stderr:\n{completed.stderr[-8000:]}"
        )

    rows = [
        line.split()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    if len(rows) != len(positions):
        raise RuntimeError(
            f"Java returned {len(rows)} rows for {len(positions)} positions; "
            f"stderr tail:\n{completed.stderr[-4000:]}"
        )

    result: list[JavaResult] = []
    for row_number, row in enumerate(rows, 1):
        if len(row) != 6:
            raise RuntimeError(f"invalid Java row {row_number}: {row!r}")
        result.append((
            int(row[0]),
            float(row[1]),
            int(row[2]),
            int(row[3]),
            int(row[4]),
            int(row[5]),
        ))
    return result


def format_board(board: str) -> str:
    return "\n".join(
        board[offset:offset + 8] for offset in range(0, 64, 8)
    )


def compare(
    positions: Sequence[Position],
    java_results: Sequence[JavaResult],
    evaluator: Evaluator,
    tolerance: float,
) -> tuple[float, float, Counter[int]]:
    max_error = 0.0
    total_error = 0.0
    phases: Counter[int] = Counter()

    for index, ((board, player), java_result) in enumerate(
        zip(positions, java_results), 1,
    ):
        details = evaluator.evaluate_details(board, player)
        (
            java_value,
            java_raw,
            java_phase,
            java_canput,
            java_surround_black,
            java_surround_white,
        ) = java_result
        raw_is_finite = (
            math.isfinite(details.raw_value) and math.isfinite(java_raw)
        )
        error = (
            abs(details.raw_value - java_raw)
            if raw_is_finite
            else math.inf
        )
        max_error = max(max_error, error)
        total_error += error
        phases[details.phase] += 1

        expected_features = (
            details.phase,
            details.canput,
            details.surround_black,
            details.surround_white,
        )
        java_features = (
            java_phase,
            java_canput,
            java_surround_black,
            java_surround_white,
        )
        if (
            details.value != java_value
            or expected_features != java_features
            or error > tolerance
        ):
            raise AssertionError(
                f"mismatch at position {index}/{len(positions)} "
                f"(player={player})\n"
                f"{format_board(board)}\n"
                f"Python: value={details.value}, "
                f"raw={details.raw_value:.17g}, "
                f"features={expected_features}\n"
                f"Java:   value={java_value}, raw={java_raw:.17g}, "
                f"features={java_features}\n"
                f"absolute raw error={error:.3e}, "
                f"tolerance={tolerance:.3e}"
            )
    return max_error, total_error / len(positions), phases


def self_test() -> None:
    board = initial_board()
    moves = tuple(move[0] for move in legal_moves(board, 0))
    if moves != (19, 26, 37, 44):
        raise AssertionError(f"unexpected initial legal moves: {moves}")
    positions = random_reachable_positions(96, 20260720)
    if len(positions) != 96 or len(set(positions)) != 96:
        raise AssertionError("reachable-position generator is not unique")
    for compact, player in positions:
        if (
            len(compact) != 64
            or set(compact) - {"0", "1", "."}
            or player not in (0, 1)
            or 64 - compact.count(".") < 4
        ):
            raise AssertionError("reachable-position generator emitted bad data")
    print("PASS: compare_java_eval self-test")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=20_260_720)
    parser.add_argument("--tolerance", type=float, default=1e-12)
    parser.add_argument(
        "--param",
        type=Path,
        default=PROJECT_ROOT / "resources" / "param.txt",
    )
    parser.add_argument(
        "--ai-source",
        type=Path,
        default=DEFAULT_AI_SOURCE,
        help=(
            "path to the unchanged OthelloAI_10.java runtime source "
            "(or set OTHELLO_AI_SOURCE)"
        ),
    )
    parser.add_argument("--java", default=shutil.which("java") or "java")
    parser.add_argument("--javac", default=shutil.which("javac") or "javac")
    parser.add_argument("--compile-timeout", type=float, default=180.0)
    parser.add_argument("--query-timeout", type=float, default=300.0)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="test only the deterministic reachable-position generator",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if FEATURE_SCHEMA != EXPECTED_FEATURE_SCHEMA:
        parser.error(
            f"training/java_eval.py schema is {FEATURE_SCHEMA!r}, "
            f"expected {EXPECTED_FEATURE_SCHEMA!r}"
        )
    if args.positions <= 0:
        parser.error("--positions must be positive")
    if not math.isfinite(args.tolerance) or args.tolerance < 0.0:
        parser.error("--tolerance must be finite and non-negative")
    if args.compile_timeout <= 0.0 or args.query_timeout <= 0.0:
        parser.error("timeouts must be positive")
    if not args.param.is_file():
        parser.error(f"--param does not exist: {args.param}")

    positions = random_reachable_positions(args.positions, args.seed)
    evaluator = Evaluator(args.param)
    with tempfile.TemporaryDirectory(
        prefix="original10-java-eval-",
    ) as temporary:
        build_dir = Path(temporary)
        compile_bridge(
            build_dir,
            args.javac,
            args.ai_source,
            args.compile_timeout,
        )
        java_results = query_java(
            build_dir,
            args.java,
            args.param,
            positions,
            args.query_timeout,
        )

    max_error, mean_error, phases = compare(
        positions,
        java_results,
        evaluator,
        args.tolerance,
    )
    if args.positions >= 128 and set(phases) != {0, 1, 2, 3}:
        raise AssertionError(
            f"random sample did not cover all phases: {dict(phases)}"
        )
    players = Counter(player for _, player in positions)
    print(
        f"PASS: {len(positions)} reachable positions, seed={args.seed}, "
        "integer mismatches=0, feature mismatches=0"
    )
    print(
        f"raw max_abs_error={max_error:.3e}, "
        f"mean_abs_error={mean_error:.3e}, "
        f"tolerance={args.tolerance:.3e}"
    )
    print(
        f"phase_counts={dict(sorted(phases.items()))}, "
        f"player_counts={dict(sorted(players.items()))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
