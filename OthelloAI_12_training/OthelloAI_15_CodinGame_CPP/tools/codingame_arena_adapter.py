#!/usr/bin/env python3
"""Adapt a CodinGame Othello process to othello_arena.py's stdin protocol."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


EMPTY = -1
DIRECTIONS = tuple(
    (dy, dx)
    for dy in (-1, 0, 1)
    for dx in (-1, 0, 1)
    if (dy, dx) != (0, 0)
)


def legal_moves(rows: list[str], player: int) -> list[tuple[int, int]]:
    opponent = player ^ 1
    result: list[tuple[int, int]] = []
    for y in range(8):
        for x in range(8):
            if rows[y][x] != ".":
                continue
            legal = False
            for dy, dx in DIRECTIONS:
                cy, cx = y + dy, x + dx
                seen = False
                while 0 <= cy < 8 and 0 <= cx < 8 and rows[cy][cx] == str(opponent):
                    seen = True
                    cy += dy
                    cx += dx
                if seen and 0 <= cy < 8 and 0 <= cx < 8 and rows[cy][cx] == str(player):
                    legal = True
                    break
            if legal:
                result.append((y, x))
    return result


def coordinate(move: tuple[int, int]) -> str:
    y, x = move
    return f"{chr(ord('a') + x)}{y + 1}"


def parse_coordinate(text: str) -> tuple[int, int]:
    token = text.strip().split()[0].lower()
    if len(token) < 2 or token[0] not in "abcdefgh" or token[1] not in "12345678":
        raise RuntimeError(f"CodinGame engine emitted malformed move: {text!r}")
    return int(token[1]) - 1, ord(token[0]) - ord("a")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    engines = parser.add_mutually_exclusive_group(required=True)
    engines.add_argument("--engine", help="path to a compiled C++ CodinGame engine")
    engines.add_argument("--java-classpath", help="directory containing Player.class")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = [args.engine] if args.engine else ["java", "-cp", args.java_classpath, "Player"]
    process = subprocess.Popen(
        command,
        cwd=args.cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    assert process.stdin is not None and process.stdout is not None
    print("READY", flush=True)
    colour_line = sys.stdin.readline()
    if not colour_line:
        process.terminate()
        return 0
    colour = int(colour_line.strip())
    process.stdin.write(f"{colour}\n8\n")
    process.stdin.flush()
    try:
        while True:
            rows = [sys.stdin.readline().rstrip("\r\n") for _ in range(8)]
            if not rows[0]:
                break
            if any(len(row) != 8 for row in rows):
                raise RuntimeError("arena supplied an incomplete board")
            moves = legal_moves(rows, colour)
            process.stdin.write("\n".join(rows) + "\n")
            process.stdin.write(f"{len(moves)}\n")
            for move in moves:
                process.stdin.write(coordinate(move) + "\n")
            process.stdin.flush()
            answer = process.stdout.readline()
            if not answer:
                raise RuntimeError(f"CodinGame engine exited with {process.poll()}")
            y, x = parse_coordinate(answer)
            if (y, x) not in moves:
                raise RuntimeError(f"illegal move from CodinGame engine: {answer.strip()}")
            print(f"{y} {x}", flush=True)
    finally:
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
