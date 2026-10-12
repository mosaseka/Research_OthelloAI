"""Compare the Python evaluator with Java on random reachable positions.

This script compiles a temporary copy of the test bridge and the unchanged AI,
starts Java once, then sends all positions through the batch protocol.

Example:
    python tests/compare_java_eval.py --positions 4096 --seed 20260715

Acceptance criteria:
* every final integer score must be exactly equal;
* phase and all three auxiliary feature indices must be exactly equal;
* the absolute pre-cast floating-point difference must be <= 1e-12.
"""

from __future__ import annotations

import argparse
from collections import Counter
import locale
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

from java_eval import Evaluator  # noqa: E402


DIRECTIONS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


def initial_board() -> tuple[str, ...]:
    board = ["."] * 64
    board[3 * 8 + 3] = "1"
    board[3 * 8 + 4] = "0"
    board[4 * 8 + 3] = "0"
    board[4 * 8 + 4] = "1"
    return tuple(board)


def flips_for_move(board: tuple[str, ...], player: int, place: int) -> tuple[int, ...]:
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
        while 0 <= y < 8 and 0 <= x < 8 and board[y * 8 + x] == opponent:
            line.append(y * 8 + x)
            y += dy
            x += dx
        if line and 0 <= y < 8 and 0 <= x < 8 and board[y * 8 + x] == own:
            flips.extend(line)
    return tuple(flips)


def legal_moves(board: tuple[str, ...], player: int) -> tuple[tuple[int, tuple[int, ...]], ...]:
    result = []
    for place, cell in enumerate(board):
        if cell == ".":
            flips = flips_for_move(board, player, place)
            if flips:
                result.append((place, flips))
    return tuple(result)


def play_move(
    board: tuple[str, ...], player: int, move: tuple[int, tuple[int, ...]]
) -> tuple[str, ...]:
    place, flips = move
    result = list(board)
    result[place] = str(player)
    for flipped in flips:
        result[flipped] = str(player)
    return tuple(result)


def random_reachable_positions(count: int, seed: int) -> list[tuple[str, int]]:
    if count <= 0:
        raise ValueError("position count must be positive")
    rng = random.Random(seed)
    result: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()

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


def compile_bridge(build_dir: Path, javac: str) -> None:
    source = PROJECT_ROOT / "OthelloAI_05.java"
    bridge = PROJECT_ROOT / "tests" / "JavaEvalBridge.java"
    command = [
        javac, "-encoding", "UTF-8", "-d", str(build_dir),
        str(source), str(bridge),
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding=locale.getencoding(),
        errors="replace",
        capture_output=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "javac failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def query_java(
    build_dir: Path,
    java: str,
    param_path: Path,
    positions: Sequence[tuple[str, int]],
) -> list[tuple[int, float, int, int, int, int]]:
    payload = "".join(f"{player}\t{board}\n" for board, player in positions)
    command = [
        java,
        "-Xmx512m",
        f"-Dothello.param={param_path.resolve()}",
        "-cp", str(build_dir),
        "JavaEvalBridge",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        input=payload,
        text=True,
        encoding=locale.getencoding(),
        errors="replace",
        capture_output=True,
        timeout=240,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Java bridge failed\n"
            f"stdout:\n{completed.stdout[-4000:]}\n"
            f"stderr:\n{completed.stderr[-4000:]}"
        )

    rows = [line.split() for line in completed.stdout.splitlines() if line.strip()]
    if len(rows) != len(positions):
        raise RuntimeError(
            f"Java returned {len(rows)} rows for {len(positions)} positions; "
            f"stderr tail:\n{completed.stderr[-2000:]}"
        )
    result = []
    for row_number, row in enumerate(rows, 1):
        if len(row) != 6:
            raise RuntimeError(f"invalid Java row {row_number}: {row!r}")
        result.append((
            int(row[0]), float(row[1]), int(row[2]),
            int(row[3]), int(row[4]), int(row[5]),
        ))
    return result


def format_board(board: str) -> str:
    return "\n".join(board[offset:offset + 8] for offset in range(0, 64, 8))


def compare(
    positions: Sequence[tuple[str, int]],
    java_results: Sequence[tuple[int, float, int, int, int, int]],
    evaluator: Evaluator,
    tolerance: float,
) -> tuple[float, float, Counter[int]]:
    max_error = 0.0
    total_error = 0.0
    phases: Counter[int] = Counter()
    for index, ((board, player), java_result) in enumerate(zip(positions, java_results), 1):
        details = evaluator.evaluate_details(board, player)
        java_value, java_raw, java_phase, java_canput, java_sur0, java_sur1 = java_result
        error = abs(details.raw_value - java_raw)
        max_error = max(max_error, error)
        total_error += error
        phases[details.phase] += 1

        expected_features = (
            details.phase, details.canput,
            details.surround_black, details.surround_white,
        )
        java_features = (java_phase, java_canput, java_sur0, java_sur1)
        if details.value != java_value or expected_features != java_features or error > tolerance:
            raise AssertionError(
                f"mismatch at position {index}/{len(positions)} (player={player})\n"
                f"{format_board(board)}\n"
                f"Python: value={details.value}, raw={details.raw_value:.17g}, "
                f"features={expected_features}\n"
                f"Java:   value={java_value}, raw={java_raw:.17g}, "
                f"features={java_features}\n"
                f"absolute raw error={error:.3e}, tolerance={tolerance:.3e}"
            )
    return max_error, total_error / len(positions), phases


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=20_260_715)
    parser.add_argument("--tolerance", type=float, default=1e-12)
    parser.add_argument("--param", type=Path, default=PROJECT_ROOT / "resources" / "param.txt")
    parser.add_argument("--java", default=shutil.which("java") or "java")
    parser.add_argument("--javac", default=shutil.which("javac") or "javac")
    args = parser.parse_args(argv)
    if args.tolerance < 0.0:
        parser.error("--tolerance must be non-negative")

    positions = random_reachable_positions(args.positions, args.seed)
    evaluator = Evaluator(args.param)
    # Keep temporary class files under the project build directory.  Besides
    # making cleanup predictable, this also works in workspace-only sandboxes.
    build_parent = PROJECT_ROOT / "build"
    build_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="java-eval-", dir=build_parent) as temporary:
        build_dir = Path(temporary)
        compile_bridge(build_dir, args.javac)
        java_results = query_java(build_dir, args.java, args.param, positions)
    max_error, mean_error, phases = compare(
        positions, java_results, evaluator, args.tolerance,
    )

    if args.positions >= 128 and set(phases) != {0, 1, 2, 3}:
        raise AssertionError(f"random sample did not cover all phases: {dict(phases)}")
    players = Counter(player for _, player in positions)
    print(
        f"PASS: {len(positions)} reachable positions, seed={args.seed}, "
        f"integer mismatches=0, feature mismatches=0"
    )
    print(
        f"raw max_abs_error={max_error:.3e}, mean_abs_error={mean_error:.3e}, "
        f"tolerance={args.tolerance:.3e}"
    )
    print(f"phase_counts={dict(sorted(phases.items()))}, player_counts={dict(sorted(players.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
