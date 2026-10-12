#!/usr/bin/env python3
"""Compile Player.java and smoke-test the CodinGame Othello protocol.

The test intentionally treats stdout as a wire protocol: every expected line
must contain only one lowercase coordinate such as ``d3``. Diagnostics written
by the bot to stderr are captured and shown only when a test fails.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Iterable, List, Optional, Sequence, Tuple, Union


COORDINATE = re.compile(r"[a-h][1-8]\Z")
EOF_MARKER = object()
OTHELLO_DIRECTIONS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)


class SmokeFailure(RuntimeError):
    """A compile, protocol, timing, or process-lifecycle check failed."""


@dataclass(frozen=True)
class Turn:
    rows: Tuple[str, ...]
    actions: Tuple[str, ...]

    def packet(self) -> str:
        if len(self.rows) != 8 or any(len(row) != 8 for row in self.rows):
            raise ValueError("a smoke-test board must contain eight 8-cell rows")
        lines = list(self.rows)
        lines.append(str(len(self.actions)))
        lines.extend(self.actions)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class OutputLine:
    received_ns: int
    text: str


QueueItem = Union[OutputLine, object]


def coordinate(row: int, column: int) -> str:
    return chr(ord("a") + column) + str(row + 1)


def coordinate_cell(move: str) -> Tuple[int, int]:
    if COORDINATE.fullmatch(move) is None:
        raise SmokeFailure(f"invalid coordinate in reference rules: {move!r}")
    return int(move[1]) - 1, ord(move[0]) - ord("a")


def captured_cells(
    rows: Sequence[str], player: int, row: int, column: int
) -> List[Tuple[int, int]]:
    if not (0 <= row < 8 and 0 <= column < 8) or rows[row][column] != ".":
        return []
    own = str(player)
    opponent = str(1 - player)
    captured: List[Tuple[int, int]] = []
    for delta_row, delta_column in OTHELLO_DIRECTIONS:
        ray: List[Tuple[int, int]] = []
        current_row = row + delta_row
        current_column = column + delta_column
        while (
            0 <= current_row < 8
            and 0 <= current_column < 8
            and rows[current_row][current_column] == opponent
        ):
            ray.append((current_row, current_column))
            current_row += delta_row
            current_column += delta_column
        if (
            ray
            and 0 <= current_row < 8
            and 0 <= current_column < 8
            and rows[current_row][current_column] == own
        ):
            captured.extend(ray)
    return captured


def reference_legal_moves(rows: Sequence[str], player: int) -> Tuple[str, ...]:
    moves: List[str] = []
    for row in range(8):
        for column in range(8):
            if captured_cells(rows, player, row, column):
                moves.append(coordinate(row, column))
    return tuple(moves)


def reference_apply(
    rows: Sequence[str], player: int, move: str
) -> Tuple[str, ...]:
    row, column = coordinate_cell(move)
    flips = captured_cells(rows, player, row, column)
    if not flips:
        raise SmokeFailure(
            f"reference transition rejected illegal player {player} move {move}"
        )
    board = [list(board_row) for board_row in rows]
    board[row][column] = str(player)
    for flip_row, flip_column in flips:
        board[flip_row][flip_column] = str(player)
    return tuple("".join(board_row) for board_row in board)


INITIAL = Turn(
    rows=(
        "........",
        "........",
        "........",
        "...10...",
        "...01...",
        "........",
        "........",
        "........",
    ),
    actions=("d3", "c4", "f5", "e6"),
)

# Standard initial position after black has played d3.
WHITE_AFTER_D3 = Turn(
    rows=(
        "........",
        "........",
        "...0....",
        "...00...",
        "...01...",
        "........",
        "........",
        "........",
    ),
    actions=("c3", "e3", "c5"),
)

# Minimal positions make the coordinate mapping unambiguous while remaining
# legal Othello positions for black. They also exercise actionCount == 1.
ONLY_A1 = Turn(
    rows=(
        ".10.....",
        "........",
        "........",
        "........",
        "........",
        "........",
        "........",
        "........",
    ),
    actions=("a1",),
)

ONLY_H8 = Turn(
    rows=(
        "........",
        "........",
        "........",
        "........",
        "........",
        "........",
        "........",
        ".....01.",
    ),
    actions=("h8",),
)


class BotProcess:
    def __init__(
        self,
        java: str,
        class_dir: Path,
        bot_args: Sequence[str],
    ) -> None:
        command = [java, "-cp", str(class_dir), "Player", *bot_args]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(class_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise SmokeFailure(f"failed to launch Java bot: {exc}") from exc

        self.stdout_queue: "queue.Queue[QueueItem]" = queue.Queue()
        self.stderr_tail: Deque[str] = deque(maxlen=80)
        self.closed = False
        self.stdout_thread = threading.Thread(
            target=self._pump_stdout, name="player-stdout", daemon=True
        )
        self.stderr_thread = threading.Thread(
            target=self._pump_stderr, name="player-stderr", daemon=True
        )
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _pump_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for raw_line in self.process.stdout:
                self.stdout_queue.put(
                    OutputLine(
                        time.perf_counter_ns(), raw_line.rstrip("\r\n")
                    )
                )
        finally:
            self.stdout_queue.put(EOF_MARKER)

    def _pump_stderr(self) -> None:
        assert self.process.stderr is not None
        for raw_line in self.process.stderr:
            self.stderr_tail.append(raw_line.rstrip("\r\n"))

    def stderr_diagnostic(self) -> str:
        if not self.stderr_tail:
            return ""
        return "\nPlayer stderr (tail):\n" + "\n".join(self.stderr_tail)

    def _write(self, text: str) -> None:
        if self.process.stdin is None:
            raise SmokeFailure("Player stdin is unavailable")
        try:
            self.process.stdin.write(text)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise SmokeFailure(
                f"Player closed stdin before the test completed: {exc}"
                + self.stderr_diagnostic()
            ) from exc

    def send_initial_turn(self, player_id: int, turn: Turn) -> None:
        self._write(f"{player_id}\n8\n" + turn.packet())

    def send_turn(self, turn: Turn) -> None:
        self._write(turn.packet())

    def expect_move(
        self,
        label: str,
        started_ns: int,
        official_limit_ms: int,
        timing_slack_ms: int,
        accepted: Iterable[str],
    ) -> Tuple[str, float]:
        # Waiting slightly beyond the limit lets us distinguish a slow answer
        # from a process that never answers. The measured timestamp remains
        # strict unless --timing-slack-ms was explicitly supplied.
        queue_timeout = (official_limit_ms + timing_slack_ms + 500) / 1000.0
        try:
            item = self.stdout_queue.get(timeout=queue_timeout)
        except queue.Empty as exc:
            raise SmokeFailure(
                f"{label}: no stdout response within {queue_timeout:.3f}s"
                + self.stderr_diagnostic()
            ) from exc

        if item is EOF_MARKER:
            raise SmokeFailure(
                f"{label}: Player exited before returning a move"
                + self.stderr_diagnostic()
            )
        assert isinstance(item, OutputLine)
        elapsed_ms = (item.received_ns - started_ns) / 1_000_000.0
        move = item.text

        if COORDINATE.fullmatch(move) is None:
            raise SmokeFailure(
                f"{label}: stdout must be exactly one coordinate, got {move!r}"
                + self.stderr_diagnostic()
            )
        accepted_set = set(accepted)
        if move not in accepted_set:
            raise SmokeFailure(
                f"{label}: returned {move!r}, expected one of "
                f"{sorted(accepted_set)!r}" + self.stderr_diagnostic()
            )

        allowed_ms = official_limit_ms + timing_slack_ms
        if elapsed_ms > allowed_ms:
            raise SmokeFailure(
                f"{label}: response took {elapsed_ms:.3f} ms "
                f"(allowed {allowed_ms} ms; official limit "
                f"{official_limit_ms} ms)" + self.stderr_diagnostic()
            )

        self.assert_stdout_quiet(label)
        return move, elapsed_ms

    def assert_stdout_quiet(self, label: str, grace_ms: int = 10) -> None:
        deadline = time.perf_counter() + grace_ms / 1000.0
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return
            try:
                item = self.stdout_queue.get(timeout=remaining)
            except queue.Empty:
                return
            if item is EOF_MARKER:
                raise SmokeFailure(
                    f"{label}: Player exited while another turn was expected"
                    + self.stderr_diagnostic()
                )
            assert isinstance(item, OutputLine)
            raise SmokeFailure(
                f"{label}: unexpected extra stdout line {item.text!r}"
                + self.stderr_diagnostic()
            )

    def close_and_expect_clean_exit(self, eof_limit_ms: int) -> None:
        if self.closed:
            return
        self.closed = True
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            return_code = self.process.wait(timeout=eof_limit_ms / 1000.0)
        except subprocess.TimeoutExpired as exc:
            self.abort()
            raise SmokeFailure(
                f"Player did not exit within {eof_limit_ms} ms after EOF"
                + self.stderr_diagnostic()
            ) from exc

        self.stdout_thread.join(timeout=0.5)
        self.stderr_thread.join(timeout=0.5)
        extra_lines: List[str] = []
        while True:
            try:
                item = self.stdout_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, OutputLine):
                extra_lines.append(item.text)
        if extra_lines:
            raise SmokeFailure(
                f"unexpected stdout after the final move: {extra_lines!r}"
                + self.stderr_diagnostic()
            )
        if return_code != 0:
            raise SmokeFailure(
                f"Player exited with status {return_code}"
                + self.stderr_diagnostic()
            )

    def abort(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except OSError:
            pass
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            self.process.kill()
        try:
            self.process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


def compile_player(
    javac: str,
    player_source: Path,
    class_dir: Path,
    timeout_seconds: int,
) -> None:
    command = [
        javac,
        "-encoding",
        "UTF-8",
        "-d",
        str(class_dir),
        str(player_source),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(player_source.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SmokeFailure(f"javac could not be completed: {exc}") from exc
    if completed.returncode != 0:
        details = (completed.stdout + completed.stderr).strip()
        raise SmokeFailure(
            "javac -encoding UTF-8 failed"
            + (f":\n{details}" if details else "")
        )
    if not (class_dir / "Player.class").is_file():
        raise SmokeFailure("javac succeeded but Player.class was not generated")


def exercise_black_process(
    java: str,
    class_dir: Path,
    bot_args: Sequence[str],
    first_limit_ms: int,
    turn_limit_ms: int,
    timing_slack_ms: int,
    eof_limit_ms: int,
) -> List[Tuple[str, str, float]]:
    started_ns = time.perf_counter_ns()
    bot = BotProcess(java, class_dir, bot_args)
    results: List[Tuple[str, str, float]] = []
    try:
        bot.send_initial_turn(0, INITIAL)
        move, elapsed = bot.expect_move(
            "initial black",
            started_ns,
            first_limit_ms,
            timing_slack_ms,
            INITIAL.actions,
        )
        results.append(("initial black", move, elapsed))

        # Exercise a real warm turn in the same process. Apply the bot's black
        # move, choose the first legal white reply deterministically, and send
        # the resulting position back to black with every reference-legal
        # action. This catches state-loop bugs hidden by one-move positions.
        after_black = reference_apply(INITIAL.rows, 0, move)
        white_actions = reference_legal_moves(after_black, 1)
        if not white_actions:
            raise SmokeFailure(
                "reference rules found no white reply after the initial move"
            )
        white_reply = white_actions[0]
        after_white = reference_apply(after_black, 1, white_reply)
        warm_black_actions = reference_legal_moves(after_white, 0)
        if len(warm_black_actions) < 2:
            raise SmokeFailure(
                "warm continuation must expose multiple legal black moves; "
                f"got {warm_black_actions!r} after white {white_reply}"
            )
        warm_turn = Turn(rows=after_white, actions=warm_black_actions)

        started_ns = time.perf_counter_ns()
        bot.send_turn(warm_turn)
        move, elapsed = bot.expect_move(
            f"same-process warm black after white {white_reply}",
            started_ns,
            turn_limit_ms,
            timing_slack_ms,
            warm_black_actions,
        )
        results.append(("warm legal continuation", move, elapsed))

        started_ns = time.perf_counter_ns()
        bot.send_turn(ONLY_A1)
        move, elapsed = bot.expect_move(
            "same-process actionCount=1 a1",
            started_ns,
            turn_limit_ms,
            timing_slack_ms,
            ONLY_A1.actions,
        )
        results.append(("actionCount=1 a1", move, elapsed))

        started_ns = time.perf_counter_ns()
        bot.send_turn(ONLY_H8)
        move, elapsed = bot.expect_move(
            "same-process actionCount=1 h8",
            started_ns,
            turn_limit_ms,
            timing_slack_ms,
            ONLY_H8.actions,
        )
        results.append(("actionCount=1 h8", move, elapsed))

        bot.close_and_expect_clean_exit(eof_limit_ms)
        return results
    finally:
        bot.abort()


def exercise_white_process(
    java: str,
    class_dir: Path,
    bot_args: Sequence[str],
    first_limit_ms: int,
    timing_slack_ms: int,
    eof_limit_ms: int,
) -> Tuple[str, str, float]:
    started_ns = time.perf_counter_ns()
    bot = BotProcess(java, class_dir, bot_args)
    try:
        bot.send_initial_turn(1, WHITE_AFTER_D3)
        move, elapsed = bot.expect_move(
            "white after black d3",
            started_ns,
            first_limit_ms,
            timing_slack_ms,
            WHITE_AFTER_D3.actions,
        )
        bot.close_and_expect_clean_exit(eof_limit_ms)
        return "white after d3", move, elapsed
    finally:
        bot.abort()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    default_player = Path(__file__).resolve().parents[1] / "Player.java"
    parser = argparse.ArgumentParser(
        description="Compile and protocol-smoke-test CodinGame Player.java."
    )
    parser.add_argument("--player", type=Path, default=default_player)
    parser.add_argument("--javac", default=shutil.which("javac") or "javac")
    parser.add_argument("--java", default=shutil.which("java") or "java")
    parser.add_argument("--compile-timeout-s", type=int, default=60)
    parser.add_argument("--first-limit-ms", type=int, default=2000)
    parser.add_argument("--turn-limit-ms", type=int, default=150)
    parser.add_argument("--eof-limit-ms", type=int, default=1500)
    parser.add_argument(
        "--timing-slack-ms",
        type=int,
        default=0,
        help=(
            "local diagnostic allowance added to timing checks; use 0 for "
            "the official CodinGame limits"
        ),
    )
    parser.add_argument(
        "--bot-arg",
        action="append",
        default=[],
        help="argument passed to Player (repeatable)",
    )
    parser.add_argument(
        "--legal-only",
        action="store_true",
        help=(
            "pass --legal-only to Player if a development template provides "
            "that explicit test mode; the generated release Player should "
            "pass without it"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    player_source = args.player.resolve()
    if not player_source.is_file():
        print(f"ERROR: Player.java not found: {player_source}", file=sys.stderr)
        return 2
    if args.first_limit_ms <= 0 or args.turn_limit_ms <= 0:
        print("ERROR: timing limits must be positive", file=sys.stderr)
        return 2
    if args.timing_slack_ms < 0:
        print("ERROR: --timing-slack-ms must be non-negative", file=sys.stderr)
        return 2

    bot_args = list(args.bot_arg)
    if args.legal_only:
        bot_args.append("--legal-only")

    try:
        with tempfile.TemporaryDirectory(prefix="othello-cg-smoke-") as temp:
            class_dir = Path(temp)
            compile_player(
                args.javac,
                player_source,
                class_dir,
                args.compile_timeout_s,
            )
            results = exercise_black_process(
                args.java,
                class_dir,
                bot_args,
                args.first_limit_ms,
                args.turn_limit_ms,
                args.timing_slack_ms,
                args.eof_limit_ms,
            )
            results.append(
                exercise_white_process(
                    args.java,
                    class_dir,
                    bot_args,
                    args.first_limit_ms,
                    args.timing_slack_ms,
                    args.eof_limit_ms,
                )
            )
    except SmokeFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS: javac UTF-8, protocol, stdout purity, timing, and EOF")
    for label, move, elapsed_ms in results:
        print(f"  {label}: {move} ({elapsed_ms:.3f} ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
