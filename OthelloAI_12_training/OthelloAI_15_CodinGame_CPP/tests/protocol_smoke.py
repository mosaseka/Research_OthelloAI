#!/usr/bin/env python3
"""Exercise CodinGame input/output, EOF handling, and move deadlines."""

from __future__ import annotations

import argparse
import subprocess
import time


DIRECTIONS = tuple(
    (dy, dx)
    for dy in (-1, 0, 1)
    for dx in (-1, 0, 1)
    if (dy, dx) != (0, 0)
)


def initial_board() -> list[list[str]]:
    board = [["." for _ in range(8)] for _ in range(8)]
    board[3][3], board[3][4], board[4][3], board[4][4] = "1", "0", "0", "1"
    return board


def legal(board: list[list[str]], player: int) -> list[tuple[int, int]]:
    opponent = str(player ^ 1)
    own = str(player)
    out = []
    for y in range(8):
        for x in range(8):
            if board[y][x] != ".":
                continue
            for dy, dx in DIRECTIONS:
                cy, cx, seen = y + dy, x + dx, False
                while 0 <= cy < 8 and 0 <= cx < 8 and board[cy][cx] == opponent:
                    cy, cx, seen = cy + dy, cx + dx, True
                if seen and 0 <= cy < 8 and 0 <= cx < 8 and board[cy][cx] == own:
                    out.append((y, x))
                    break
    return out


def apply(board: list[list[str]], player: int, move: tuple[int, int]) -> None:
    y, x = move
    board[y][x] = str(player)
    for dy, dx in DIRECTIONS:
        cy, cx = y + dy, x + dx
        captured = []
        while 0 <= cy < 8 and 0 <= cx < 8 and board[cy][cx] == str(player ^ 1):
            captured.append((cy, cx));cy += dy;cx += dx
        if captured and 0 <= cy < 8 and 0 <= cx < 8 and board[cy][cx] == str(player):
            for fy, fx in captured:
                board[fy][fx] = str(player)


def coord(move: tuple[int, int]) -> str:
    return f"{chr(97 + move[1])}{move[0] + 1}"


def parse(text: str) -> tuple[int, int]:
    token = text.strip().split()[0].lower()
    return int(token[1]) - 1, ord(token[0]) - 97


def send_turn(process: subprocess.Popen[str], board: list[list[str]], player: int) -> float:
    moves = legal(board, player)
    assert process.stdin is not None and process.stdout is not None
    payload = ["".join(row) for row in board] + [str(len(moves))] + [coord(m) for m in moves]
    start = time.perf_counter()
    process.stdin.write("\n".join(payload) + "\n");process.stdin.flush()
    answer = process.stdout.readline()
    elapsed = time.perf_counter() - start
    if not answer:
        raise AssertionError("engine closed stdout")
    if parse(answer) not in moves:
        raise AssertionError(f"illegal output: {answer!r}; legal={moves}")
    apply(board, player, parse(answer))
    return elapsed


def run(executable: str) -> None:
    process = subprocess.Popen(
        [executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
    )
    assert process.stdin is not None
    board = initial_board();process.stdin.write("0\n8\n");process.stdin.flush()
    first = send_turn(process, board, 0)
    opponent = legal(board, 1)[0];apply(board, 1, opponent)
    normal = send_turn(process, board, 0)
    process.stdin.close();process.wait(timeout=2.0)
    stderr = process.stderr.read() if process.stderr else ""
    if process.returncode != 0:
        raise AssertionError(f"exit={process.returncode}; stderr={stderr}")
    if first >= 2.0:
        raise AssertionError(f"first turn exceeded 2,000 ms: {first*1000:.1f} ms")
    if normal >= 0.150:
        raise AssertionError(f"normal turn exceeded 150 ms: {normal*1000:.1f} ms")
    print(f"PASS first={first*1000:.1f}ms normal={normal*1000:.1f}ms")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player", required=True)
    args = parser.parse_args();run(args.player);return 0


if __name__ == "__main__":
    raise SystemExit(main())
