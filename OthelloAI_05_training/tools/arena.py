#!/usr/bin/env python3
"""Reproducible local A/B arena for the line-oriented Othello AI protocol.

The arena deliberately owns the game rules.  Engines receive their colour once,
then eight board rows per turn, and must answer ``y x`` with an optional numeric
evaluation.  No third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import queue
import random
import re
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence


BOARD_SIZE = 8
BLACK = 0
WHITE = 1
EMPTY = -1
COLOUR_NAMES = {BLACK: "black", WHITE: "white"}
DIRECTIONS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)

MOVE_RE = re.compile(
    r"^\s*([+-]?\d+)\s+([+-]?\d+)(?:\s+(\S+))?\s*$"
)
COMPLETED_RE = re.compile(
    r"completed\s+depth:\s*(\d+).*?\bnps:\s*(\d+)", re.IGNORECASE
)
PLACED_DEPTH_RE = re.compile(r"Placed at:.*?\[depth:\s*(\d+)", re.IGNORECASE)
TIME_UP_DEPTH_RE = re.compile(r"time up.*?using depth\s+(\d+)", re.IGNORECASE)
FINAL_RE = re.compile(
    r"final\s+depth:\s*(\d+).*?\bnps:\s*(\d+)", re.IGNORECASE
)


def initial_board() -> tuple[int, ...]:
    """Return the conventional initial board in row-major order."""
    board = [EMPTY] * (BOARD_SIZE * BOARD_SIZE)
    board[3 * BOARD_SIZE + 3] = WHITE
    board[3 * BOARD_SIZE + 4] = BLACK
    board[4 * BOARD_SIZE + 3] = BLACK
    board[4 * BOARD_SIZE + 4] = WHITE
    return tuple(board)


def _index(y: int, x: int) -> int:
    return y * BOARD_SIZE + x


def _captures(
    board: Sequence[int], player: int, y: int, x: int
) -> tuple[int, ...]:
    if not (0 <= y < BOARD_SIZE and 0 <= x < BOARD_SIZE):
        return ()
    if board[_index(y, x)] != EMPTY:
        return ()

    opponent = player ^ 1
    captured: list[int] = []
    for dy, dx in DIRECTIONS:
        cy, cx = y + dy, x + dx
        line: list[int] = []
        while (
            0 <= cy < BOARD_SIZE
            and 0 <= cx < BOARD_SIZE
            and board[_index(cy, cx)] == opponent
        ):
            line.append(_index(cy, cx))
            cy += dy
            cx += dx
        if (
            line
            and 0 <= cy < BOARD_SIZE
            and 0 <= cx < BOARD_SIZE
            and board[_index(cy, cx)] == player
        ):
            captured.extend(line)
    return tuple(captured)


def legal_moves(board: Sequence[int], player: int) -> list[tuple[int, int]]:
    """Return legal placements in deterministic row-major order."""
    return [
        (y, x)
        for y in range(BOARD_SIZE)
        for x in range(BOARD_SIZE)
        if _captures(board, player, y, x)
    ]


def apply_move(
    board: Sequence[int], player: int, move: tuple[int, int]
) -> tuple[int, ...]:
    """Apply one legal placement, raising ValueError for an illegal move."""
    y, x = move
    captured = _captures(board, player, y, x)
    if not captured:
        raise ValueError(f"illegal move for {COLOUR_NAMES[player]}: {y} {x}")
    result = list(board)
    result[_index(y, x)] = player
    for position in captured:
        result[position] = player
    return tuple(result)


def board_rows(board: Sequence[int]) -> list[str]:
    symbols = {BLACK: "0", WHITE: "1", EMPTY: "."}
    return [
        "".join(symbols[board[_index(y, x)]] for x in range(BOARD_SIZE))
        for y in range(BOARD_SIZE)
    ]


def disc_counts(board: Sequence[int]) -> dict[str, int]:
    return {
        "black": sum(cell == BLACK for cell in board),
        "white": sum(cell == WHITE for cell in board),
        "empty": sum(cell == EMPTY for cell in board),
    }


def is_terminal(board: Sequence[int]) -> bool:
    return not legal_moves(board, BLACK) and not legal_moves(board, WHITE)


def generate_random_opening(
    seed: int, placement_plies: int
) -> tuple[tuple[int, ...], int, list[dict[str, object]]]:
    """Generate a legal opening; passes do not consume placement_plies."""
    if not 0 <= placement_plies <= 60:
        raise ValueError("random opening plies must be between 0 and 60")
    rng = random.Random(seed)
    board = initial_board()
    player = BLACK
    placements = 0
    history: list[dict[str, object]] = []
    consecutive_passes = 0

    while placements < placement_plies and consecutive_passes < 2:
        moves = legal_moves(board, player)
        if not moves:
            history.append(
                {
                    "ply": len(history),
                    "colour": COLOUR_NAMES[player],
                    "move": None,
                }
            )
            consecutive_passes += 1
            player ^= 1
            continue
        consecutive_passes = 0
        move = moves[rng.randrange(len(moves))]
        board = apply_move(board, player, move)
        history.append(
            {
                "ply": len(history),
                "colour": COLOUR_NAMES[player],
                "move": [move[0], move[1]],
            }
        )
        placements += 1
        player ^= 1

    return board, player, history


@dataclass
class EngineFault(Exception):
    kind: str
    stage: str
    message: str
    raw_output: Optional[str] = None
    returncode: Optional[int] = None

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class EngineMove:
    y: int
    x: int
    value: Optional[float]
    raw: str


class StderrDrainer:
    """Continuously drain stderr so verbose engines can never block on a pipe."""

    def __init__(self, stream: object) -> None:
        self._stream = stream
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, name="othello-stderr-drain", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            for raw in iter(self._stream.readline, ""):
                line = raw.rstrip("\r\n")
                with self._lock:
                    self._lines.append(line)
        except (OSError, ValueError):
            # Closing or killing a process can invalidate the pipe mid-read.
            pass

    def join(self, timeout: float) -> None:
        self._thread.join(timeout)

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def tail(self, count: int = 20) -> list[str]:
        with self._lock:
            return list(self._lines[-count:])


class EngineProcess:
    """One engine process with a Queue-backed stdout reader for Windows."""

    _EOF = object()

    def __init__(
        self,
        label: str,
        command: Sequence[str],
        cwd: Path,
        colour: int,
        env: dict[str, str],
        startup_timeout_s: float,
    ) -> None:
        self.label = label
        self.command = list(command)
        self.cwd = cwd
        self.colour = colour
        self._stdout_queue: queue.Queue[object] = queue.Queue()
        self._closed = False

        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=str(self.cwd),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            raise EngineFault(
                "crash", "startup", f"could not start {label}: {exc}"
            ) from exc

        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name=f"othello-{label}-stdout",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr = StderrDrainer(self.process.stderr)

        try:
            ready = self._read_line(startup_timeout_s, stage="startup")
            if ready.strip() != "READY":
                raise EngineFault(
                    "malformed",
                    "startup",
                    f"{label} emitted {ready!r}; expected 'READY'",
                    raw_output=ready,
                    returncode=self.process.poll(),
                )
            self._write(f"{colour}\n", stage="startup")
        except EngineFault:
            self.terminate()
            raise

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for raw in iter(self.process.stdout.readline, ""):
                self._stdout_queue.put(raw.rstrip("\r\n"))
        except (OSError, ValueError):
            pass
        finally:
            self._stdout_queue.put(self._EOF)

    def _read_line(self, timeout_s: float, stage: str) -> str:
        try:
            item = self._stdout_queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            returncode = self.process.poll()
            if returncode is not None:
                raise EngineFault(
                    "crash",
                    stage,
                    f"{self.label} exited with code {returncode}",
                    returncode=returncode,
                ) from exc
            raise EngineFault(
                "timeout",
                stage,
                f"{self.label} did not respond within {timeout_s:.3f} s",
            ) from exc
        if item is self._EOF:
            returncode = self.process.poll()
            raise EngineFault(
                "crash",
                stage,
                f"{self.label} closed stdout"
                + ("" if returncode is None else f" (exit code {returncode})"),
                returncode=returncode,
            )
        assert isinstance(item, str)
        return item

    def _write(self, text: str, stage: str) -> None:
        if self.process.poll() is not None:
            raise EngineFault(
                "crash",
                stage,
                f"{self.label} exited with code {self.process.returncode}",
                returncode=self.process.returncode,
            )
        try:
            assert self.process.stdin is not None
            self.process.stdin.write(text)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise EngineFault(
                "crash",
                stage,
                f"failed to write to {self.label}: {exc}",
                returncode=self.process.poll(),
            ) from exc

    def request_move(self, board: Sequence[int], timeout_s: float) -> EngineMove:
        payload = "\n".join(board_rows(board)) + "\n"
        self._write(payload, stage="move")
        raw = self._read_line(timeout_s, stage="move")
        match = MOVE_RE.fullmatch(raw)
        if match is None:
            raise EngineFault(
                "malformed",
                "move",
                f"{self.label} emitted malformed move {raw!r}",
                raw_output=raw,
                returncode=self.process.poll(),
            )

        y = int(match.group(1))
        x = int(match.group(2))
        value: Optional[float] = None
        if match.group(3) is not None:
            try:
                value = float(match.group(3))
            except ValueError as exc:
                raise EngineFault(
                    "malformed",
                    "move",
                    f"{self.label} emitted a non-numeric value in {raw!r}",
                    raw_output=raw,
                ) from exc
            if not math.isfinite(value):
                raise EngineFault(
                    "malformed",
                    "move",
                    f"{self.label} emitted a non-finite value in {raw!r}",
                    raw_output=raw,
                )
        return EngineMove(y=y, x=x, value=value, raw=raw)

    def terminate(self, shutdown_timeout_s: float = 1.0) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=shutdown_timeout_s)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=shutdown_timeout_s)
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    self.process.wait(timeout=shutdown_timeout_s)
                except subprocess.TimeoutExpired:
                    pass
        self._stdout_thread.join(shutdown_timeout_s)
        self._stderr.join(shutdown_timeout_s)

    def stderr_lines(self) -> list[str]:
        return self._stderr.lines()

    def stderr_tail(self, count: int = 20) -> list[str]:
        return self._stderr.tail(count)


def _extract_turn_metrics(lines: Iterable[str]) -> list[dict[str, Optional[float]]]:
    """Extract one final depth/NPS sample for each engine turn when available."""
    samples: list[dict[str, Optional[float]]] = []
    current: Optional[dict[str, Optional[float]]] = None

    def ensure_current() -> dict[str, Optional[float]]:
        nonlocal current
        if current is None:
            current = {"depth": None, "nps": None}
        return current

    def finish(force: bool = False) -> None:
        nonlocal current
        if current is not None and (
            force or current["depth"] is not None or current["nps"] is not None
        ):
            samples.append(current)
        current = None

    for line in lines:
        if "Waiting for board input" in line:
            finish()
            current = {"depth": None, "nps": None}
            continue

        completed = COMPLETED_RE.search(line)
        if completed:
            sample = ensure_current()
            sample["depth"] = float(completed.group(1))
            sample["nps"] = float(completed.group(2))
            continue

        final = FINAL_RE.search(line)
        if final:
            sample = ensure_current()
            sample["depth"] = float(final.group(1))
            sample["nps"] = float(final.group(2))
            continue

        placed = PLACED_DEPTH_RE.search(line)
        if placed:
            ensure_current()["depth"] = float(placed.group(1))
            finish(force=True)
            continue

        timed_out = TIME_UP_DEPTH_RE.search(line)
        if timed_out:
            ensure_current()["depth"] = float(timed_out.group(1))
            continue

        if line.startswith("Placed at:") or line.strip() == "Pass":
            finish(force=True)

    finish()
    return samples


def _aggregate_metrics(samples: Sequence[dict[str, Optional[float]]]) -> dict[str, object]:
    depths = [sample["depth"] for sample in samples if sample["depth"] is not None]
    nps_values = [sample["nps"] for sample in samples if sample["nps"] is not None]
    return {
        "turns_seen": len(samples),
        "depth_samples": len(depths),
        "nps_samples": len(nps_values),
        "average_depth": None if not depths else sum(depths) / len(depths),
        "average_nps": None if not nps_values else sum(nps_values) / len(nps_values),
    }


def _fault_dict(fault: EngineFault, player: str, engine: Optional[EngineProcess]) -> dict[str, object]:
    return {
        "player": player,
        "type": fault.kind,
        "stage": fault.stage,
        "message": fault.message,
        "raw_output": fault.raw_output,
        "returncode": fault.returncode,
        "stderr_tail": [] if engine is None else engine.stderr_tail(),
    }


def run_game(
    *,
    pair_index: int,
    game_in_pair: int,
    opening_seed: int,
    opening_board: tuple[int, ...],
    opening_player: int,
    opening_history: Sequence[dict[str, object]],
    black_player: str,
    white_player: str,
    commands: dict[str, Sequence[str]],
    working_directories: dict[str, Path],
    engine_env: dict[str, str],
    startup_timeout_s: float,
    move_timeout_s: float,
    shutdown_timeout_s: float,
) -> dict[str, object]:
    started_at = datetime.now(timezone.utc)
    start_clock = time.monotonic()
    colours = {black_player: BLACK, white_player: WHITE}
    engines: dict[str, EngineProcess] = {}
    turns: list[dict[str, object]] = []
    fault_info: Optional[dict[str, object]] = None
    board = opening_board
    player = opening_player

    try:
        for label in ("A", "B"):
            try:
                engines[label] = EngineProcess(
                    label=label,
                    command=commands[label],
                    cwd=working_directories[label],
                    colour=colours[label],
                    env=engine_env,
                    startup_timeout_s=startup_timeout_s,
                )
            except EngineFault as fault:
                fault_info = _fault_dict(fault, label, engines.get(label))
                break

        while fault_info is None:
            moves = legal_moves(board, player)
            if not moves:
                if not legal_moves(board, player ^ 1):
                    break
                actor = black_player if player == BLACK else white_player
                turns.append(
                    {
                        "turn": len(turns),
                        "colour": COLOUR_NAMES[player],
                        "player": actor,
                        "board": board_rows(board),
                        "legal_move_count": 0,
                        "response": None,
                        "value": None,
                        "elapsed_ms": 0.0,
                        "move": None,
                        "pass": True,
                    }
                )
                player ^= 1
                continue

            actor = black_player if player == BLACK else white_player
            before_rows = board_rows(board)
            move_started = time.monotonic()
            try:
                reply = engines[actor].request_move(board, move_timeout_s)
            except EngineFault as fault:
                fault_info = _fault_dict(fault, actor, engines.get(actor))
                break
            elapsed_ms = (time.monotonic() - move_started) * 1000.0

            turn: dict[str, object] = {
                "turn": len(turns),
                "colour": COLOUR_NAMES[player],
                "player": actor,
                "board": before_rows,
                "legal_move_count": len(moves),
                "response": reply.raw,
                "value": reply.value,
                "elapsed_ms": elapsed_ms,
            }

            move = (reply.y, reply.x)
            if move not in moves:
                fault = EngineFault(
                    "illegal",
                    "move",
                    f"{actor} emitted illegal move {reply.raw!r}",
                    raw_output=reply.raw,
                )
                fault_info = _fault_dict(fault, actor, engines.get(actor))
                turn["move"] = [reply.y, reply.x]
                turn["legal_moves"] = [[y, x] for y, x in moves]
                turns.append(turn)
                break

            board = apply_move(board, player, move)
            turn["move"] = [reply.y, reply.x]
            turn["pass"] = False
            turns.append(turn)
            player ^= 1
    finally:
        for engine in engines.values():
            engine.terminate(shutdown_timeout_s)

    metrics: dict[str, object] = {}
    per_engine_samples: dict[str, list[dict[str, Optional[float]]]] = {}
    for label in ("A", "B"):
        samples = (
            _extract_turn_metrics(engines[label].stderr_lines())
            if label in engines
            else []
        )
        per_engine_samples[label] = samples
        metrics[label] = _aggregate_metrics(samples)

    # Attach metrics to matching move records without trusting them for rules.
    sample_positions = {"A": 0, "B": 0}
    for turn in turns:
        if turn.get("pass"):
            continue
        actor = str(turn["player"])
        position = sample_positions[actor]
        actor_samples = per_engine_samples[actor]
        if position < len(actor_samples):
            turn["search"] = actor_samples[position]
        sample_positions[actor] += 1

    counts = disc_counts(board)
    if fault_info is not None:
        loser = str(fault_info["player"])
        winner = "B" if loser == "A" else "A"
        status = "forfeit"
        outcome_a = "win" if winner == "A" else "loss"
        disc_difference_a: Optional[int] = None
    else:
        black_count = counts["black"]
        white_count = counts["white"]
        if black_count == white_count:
            winner = "draw"
            outcome_a = "draw"
        else:
            winning_colour = BLACK if black_count > white_count else WHITE
            winner = black_player if winning_colour == BLACK else white_player
            outcome_a = "win" if winner == "A" else "loss"
        status = "completed"
        a_colour = colours["A"]
        own = black_count if a_colour == BLACK else white_count
        other = white_count if a_colour == BLACK else black_count
        disc_difference_a = own - other

    return {
        "schema_version": 1,
        "pair_index": pair_index,
        "game_in_pair": game_in_pair,
        "opening_seed": opening_seed,
        "opening_placement_plies": sum(
            move["move"] is not None for move in opening_history
        ),
        "opening_history": list(opening_history),
        "starting_board": board_rows(opening_board),
        "starting_player": COLOUR_NAMES[opening_player],
        "black_player": black_player,
        "white_player": white_player,
        "player_a_colour": COLOUR_NAMES[colours["A"]],
        "status": status,
        "winner": winner,
        "outcome_a": outcome_a,
        "score_a": {"win": 1.0, "draw": 0.5, "loss": 0.0}[outcome_a],
        "disc_counts": counts,
        "disc_difference_a": disc_difference_a,
        "board_at_end": board_rows(board),
        "next_player_at_end": COLOUR_NAMES[player],
        "moves": turns,
        "move_count": sum(turn.get("move") is not None for turn in turns),
        "pass_count": sum(turn.get("pass") is True for turn in turns),
        "search": metrics,
        "fault": fault_info,
        "started_at_utc": started_at.isoformat(),
        "duration_ms": (time.monotonic() - start_clock) * 1000.0,
    }


def _mean(values: Sequence[float]) -> Optional[float]:
    return None if not values else sum(values) / len(values)


def wilson_interval(successes: float, trials: int, z: float = 1.959963984540054) -> list[float]:
    """Return a 95% Wilson interval; fractional successes support half-point draws."""
    if trials <= 0:
        return [0.0, 1.0]
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (proportion + z * z / (2.0 * trials)) / denominator
    radius = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z * z / (4.0 * trials * trials)
        )
        / denominator
    )
    return [max(0.0, centre - radius), min(1.0, centre + radius)]


def _perspective_stats(records: Sequence[dict[str, object]], label: str) -> dict[str, object]:
    outcomes: list[str] = []
    disc_differences: list[float] = []
    depth_samples: list[float] = []
    nps_samples: list[float] = []

    for record in records:
        outcome_a = str(record["outcome_a"])
        outcome = outcome_a if label == "A" else {"win": "loss", "loss": "win", "draw": "draw"}[outcome_a]
        outcomes.append(outcome)
        difference = record["disc_difference_a"]
        if difference is not None:
            disc_differences.append(float(difference) * (1.0 if label == "A" else -1.0))
        search = record["search"]
        assert isinstance(search, dict)
        engine_search = search[label]
        assert isinstance(engine_search, dict)
        if engine_search["average_depth"] is not None:
            count = int(engine_search["depth_samples"])
            depth_samples.extend([float(engine_search["average_depth"])] * count)
        if engine_search["average_nps"] is not None:
            count = int(engine_search["nps_samples"])
            nps_samples.extend([float(engine_search["average_nps"])] * count)

    games = len(outcomes)
    wins = outcomes.count("win")
    losses = outcomes.count("loss")
    draws = outcomes.count("draw")
    score = wins + 0.5 * draws
    return {
        "games": games,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "score": score,
        "score_rate": None if games == 0 else score / games,
        "win_rate": None if games == 0 else wins / games,
        "draw_rate": None if games == 0 else draws / games,
        "average_disc_difference": _mean(disc_differences),
        "disc_difference_samples": len(disc_differences),
        "average_depth": _mean(depth_samples),
        "depth_samples": len(depth_samples),
        "average_nps": _mean(nps_samples),
        "nps_samples": len(nps_samples),
        "wilson_95": {
            "score_rate": wilson_interval(score, games),
            "win_rate": wilson_interval(float(wins), games),
            "draw_rate": wilson_interval(float(draws), games),
            "draws_count_as_half_for_score": True,
        },
    }


def _complete_pairs(
    records: Sequence[dict[str, object]],
) -> tuple[list[tuple[dict[str, object], dict[str, object]]], dict[str, int]]:
    grouped: dict[int, list[dict[str, object]]] = {}
    for record in records:
        grouped.setdefault(int(record["pair_index"]), []).append(record)
    result: list[tuple[dict[str, object], dict[str, object]]] = []
    invalid: dict[str, int] = {}
    for pair in grouped.values():
        reason: Optional[str] = None
        games = {int(record["game_in_pair"]): record for record in pair}
        if len(pair) != 2:
            reason = "game_count"
        elif set(games) != {0, 1} or len(games) != 2:
            reason = "game_index"
        elif games[0]["opening_seed"] != games[1]["opening_seed"]:
            reason = "opening_seed"
        elif (
            games[0].get("starting_board") != games[1].get("starting_board")
            or games[0].get("starting_player") != games[1].get("starting_player")
        ):
            reason = "opening_position"
        elif {games[0]["player_a_colour"], games[1]["player_a_colour"]} != {"black", "white"}:
            reason = "colour_exchange"
        elif games[0]["status"] != "completed" or games[1]["status"] != "completed":
            reason = "not_completed"
        if reason is None:
            result.append((games[0], games[1]))
        else:
            invalid[reason] = invalid.get(reason, 0) + 1
    return result, invalid


def _paired_perspective_stats(
    records: Sequence[dict[str, object]], label: str
) -> dict[str, object]:
    pairs, invalid = _complete_pairs(records)
    outcomes: list[str] = []
    pair_scores: list[float] = []
    differences: list[float] = []
    for first, second in pairs:
        score_a = float(first["score_a"]) + float(second["score_a"])
        score = (score_a if label == "A" else 2.0 - score_a) / 2.0
        pair_scores.append(score)
        outcomes.append("win" if score > 0.5 else "loss" if score < 0.5 else "draw")
        discs = (first["disc_difference_a"], second["disc_difference_a"])
        if None not in discs:
            sign = 1.0 if label == "A" else -1.0
            differences.append(sign * sum(float(value) for value in discs) / 2)
    wins, draws = outcomes.count("win"), outcomes.count("draw")
    points = sum(pair_scores)
    return {
        "pairs_recorded": len(pairs) + sum(invalid.values()),
        "complete_pairs": len(pairs),
        "invalid_pairs": sum(invalid.values()),
        "invalid_reasons": dict(sorted(invalid.items())),
        "wins": wins, "draws": draws, "losses": outcomes.count("loss"),
        "score": points,
        "score_rate": None if not pairs else points / len(pairs),
        "average_disc_difference": _mean(differences),
        "disc_difference_samples": len(differences),
        "wilson_95": {"score_rate": wilson_interval(points, len(pairs)),
                      "draws_count_as_half_for_score": True,
                      "unit": "paired_colour_swapped_opening"},
    }


def build_summary(
    records: Sequence[dict[str, object]], config: dict[str, object]
) -> dict[str, object]:
    players: dict[str, object] = {}
    for label in ("A", "B"):
        stats = _perspective_stats(records, label)
        stats["paired"] = _paired_perspective_stats(records, label)
        stats["by_colour"] = {
            colour: _perspective_stats(
                [record for record in records if record[f"{colour}_player"] == label],
                label,
            )
            for colour in ("black", "white")
        }
        players[label] = stats

    faults = [record["fault"] for record in records if record["fault"] is not None]
    by_player = {
        label: sum(fault["player"] == label for fault in faults) for label in ("A", "B")
    }
    fault_types = sorted({str(fault["type"]) for fault in faults})
    by_type = {
        kind: sum(fault["type"] == kind for fault in faults) for kind in fault_types
    }

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "pairs_requested": int(config["pairs"]),
        "games_requested": int(config["pairs"]) * 2,
        "games_recorded": len(records),
        "completed_games": sum(record["status"] == "completed" for record in records),
        "forfeit_games": sum(record["status"] == "forfeit" for record in records),
        "players": players,
        "faults": {
            "total": len(faults),
            "by_player": by_player,
            "by_type": by_type,
        },
        "opening_seeds": [record["opening_seed"] for record in records[::2]],
    }


def parse_command(command: str) -> list[str]:
    """Parse a quoted command string into a platform-appropriate argv list."""
    if not command.strip():
        raise ValueError("AI command must not be empty")
    if command.lstrip().startswith("["):
        value = json.loads(command)
        if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            raise ValueError("JSON AI command must be a non-empty array of strings")
        return value
    parts = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        parts = [
            part[1:-1]
            if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'"
            else part
            for part in parts
        ]
    if not parts:
        raise ValueError("AI command must not be empty")
    return parts


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def make_argument_parser(project_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run reproducible, colour-swapped Othello A/B matches."
    )
    parser.add_argument("--ai-a", required=True, help="quoted command for player A")
    parser.add_argument(
        "--ai-b", help="quoted command for player B (defaults to --ai-a)"
    )
    parser.add_argument("--name-a", default="A")
    parser.add_argument("--name-b", default="B")
    parser.add_argument("--cwd-a", type=Path, default=project_root)
    parser.add_argument("--cwd-b", type=Path, default=project_root)
    parser.add_argument("--pairs", type=_positive_int, default=1)
    parser.add_argument(
        "--random-opening-plies", type=int, default=8, metavar="N"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260715,
        help="deterministic master seed for random openings",
    )
    parser.add_argument(
        "--jsonl", type=Path, default=project_root / "results" / "arena-games.jsonl"
    )
    parser.add_argument(
        "--summary", type=Path, default=project_root / "results" / "arena-summary.json"
    )
    parser.add_argument("--append", action="store_true", help="append JSONL instead of replacing it")
    parser.add_argument("--startup-timeout-ms", type=_positive_int, default=60_000)
    parser.add_argument(
        "--move-timeout-ms",
        type=_positive_int,
        default=None,
        help="arena response deadline; default is derived without changing engine settings",
    )
    parser.add_argument("--shutdown-timeout-ms", type=_positive_int, default=2_000)
    parser.add_argument(
        "--move-time-ms",
        type=_positive_int,
        default=None,
        help="test-only OTHELLO_MOVE_TIME_MS override; omitted in production by default",
    )
    parser.add_argument(
        "--threads",
        type=_positive_int,
        default=None,
        help="test-only OTHELLO_THREADS override; omitted by default",
    )
    parser.add_argument(
        "--engine-seed",
        "--ai-seed",
        type=int,
        default=None,
        help="test-only OTHELLO_SEED override; omitted by default",
    )
    return parser


def _derive_move_timeout_ms(explicit: Optional[int], move_time_override: Optional[int]) -> int:
    if explicit is not None:
        return explicit
    configured = move_time_override
    if configured is None:
        try:
            configured = int(os.environ["OTHELLO_MOVE_TIME_MS"])
        except (KeyError, ValueError):
            configured = None
    if configured is None:
        return 12_000
    return max(configured + 1_000, int(configured * 1.5))


def main(argv: Optional[Sequence[str]] = None) -> int:
    project_root = Path(__file__).resolve().parent.parent
    parser = make_argument_parser(project_root)
    args = parser.parse_args(argv)
    if not 0 <= args.random_opening_plies <= 60:
        parser.error("--random-opening-plies must be between 0 and 60")

    try:
        command_a = parse_command(args.ai_a)
        command_b = parse_command(args.ai_b or args.ai_a)
    except (ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    working_directories = {
        "A": args.cwd_a.resolve(),
        "B": args.cwd_b.resolve(),
    }
    for label, path in working_directories.items():
        if not path.is_dir():
            parser.error(f"--cwd-{label.lower()} is not a directory: {path}")

    engine_env = dict(os.environ)
    requested_overrides: dict[str, object] = {}
    if args.move_time_ms is not None:
        engine_env["OTHELLO_MOVE_TIME_MS"] = str(args.move_time_ms)
        requested_overrides["OTHELLO_MOVE_TIME_MS"] = args.move_time_ms
    if args.threads is not None:
        engine_env["OTHELLO_THREADS"] = str(args.threads)
        requested_overrides["OTHELLO_THREADS"] = args.threads
    if args.engine_seed is not None:
        engine_env["OTHELLO_SEED"] = str(args.engine_seed)
        requested_overrides["OTHELLO_SEED"] = args.engine_seed

    inherited_or_requested = {
        key: engine_env[key]
        for key in ("OTHELLO_MOVE_TIME_MS", "OTHELLO_THREADS", "OTHELLO_SEED")
        if key in engine_env
    }
    move_timeout_ms = _derive_move_timeout_ms(args.move_timeout_ms, args.move_time_ms)
    commands = {"A": command_a, "B": command_b}
    config: dict[str, object] = {
        "player_names": {"A": args.name_a, "B": args.name_b},
        "commands": commands,
        "working_directories": {key: str(value) for key, value in working_directories.items()},
        "pairs": args.pairs,
        "random_opening_plies": args.random_opening_plies,
        "master_seed": args.seed,
        "startup_timeout_ms": args.startup_timeout_ms,
        "move_timeout_ms": move_timeout_ms,
        "shutdown_timeout_ms": args.shutdown_timeout_ms,
        "requested_engine_overrides": requested_overrides,
        "effective_engine_override_environment": inherited_or_requested,
    }

    args.jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "w"
    records: list[dict[str, object]] = []
    master_rng = random.Random(args.seed)

    try:
        with args.jsonl.open(mode, encoding="utf-8", newline="\n") as output:
            for pair_index in range(args.pairs):
                opening_seed = master_rng.getrandbits(64)
                opening_board, opening_player, history = generate_random_opening(
                    opening_seed, args.random_opening_plies
                )
                for game_in_pair, (black_player, white_player) in enumerate(
                    (("A", "B"), ("B", "A"))
                ):
                    record = run_game(
                        pair_index=pair_index,
                        game_in_pair=game_in_pair,
                        opening_seed=opening_seed,
                        opening_board=opening_board,
                        opening_player=opening_player,
                        opening_history=history,
                        black_player=black_player,
                        white_player=white_player,
                        commands=commands,
                        working_directories=working_directories,
                        engine_env=engine_env,
                        startup_timeout_s=args.startup_timeout_ms / 1000.0,
                        move_timeout_s=move_timeout_ms / 1000.0,
                        shutdown_timeout_s=args.shutdown_timeout_ms / 1000.0,
                    )
                    records.append(record)
                    output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    output.flush()
                    print(
                        f"pair {pair_index + 1}/{args.pairs} game {game_in_pair + 1}/2: "
                        f"{record['winner']} ({record['status']})",
                        file=sys.stderr,
                    )
    except KeyboardInterrupt:
        print("arena interrupted; writing summary for completed records", file=sys.stderr)

    summary = build_summary(records, config)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if len(records) == args.pairs * 2 else 130


if __name__ == "__main__":
    raise SystemExit(main())
