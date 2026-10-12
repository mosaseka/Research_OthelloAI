#!/usr/bin/env python3
"""Compare C++ legal moves and width-16 evaluation with the Java baseline."""

from __future__ import annotations

import argparse
import math
import random
import subprocess


DIRECTIONS = tuple(
    (dy, dx)
    for dy in (-1, 0, 1)
    for dx in (-1, 0, 1)
    if (dy, dx) != (0, 0)
)


def initial() -> list[int]:
    board = [-1] * 64
    board[27], board[28], board[35], board[36] = 1, 0, 0, 1
    return board


def captures(board: list[int], player: int, y: int, x: int) -> list[int]:
    if board[y * 8 + x] != -1:
        return []
    result: list[int] = []
    for dy, dx in DIRECTIONS:
        cy, cx = y + dy, x + dx
        line: list[int] = []
        while 0 <= cy < 8 and 0 <= cx < 8 and board[cy * 8 + cx] == (player ^ 1):
            line.append(cy * 8 + cx);cy += dy;cx += dx
        if line and 0 <= cy < 8 and 0 <= cx < 8 and board[cy * 8 + cx] == player:
            result.extend(line)
    return result


def legal(board: list[int], player: int) -> list[int]:
    return [cell for cell in range(64) if captures(board, player, cell // 8, cell % 8)]


def move(board: list[int], player: int, cell: int) -> None:
    flipped = captures(board, player, cell // 8, cell % 8)
    board[cell] = player
    for other in flipped:
        board[other] = player


def rows(board: list[int]) -> list[str]:
    chars = {0: "0", 1: "1", -1: "."}
    return ["".join(chars[v] for v in board[y * 8 : y * 8 + 8]) for y in range(8)]


def positions(count: int, seed: int) -> list[tuple[int, list[str]]]:
    rng = random.Random(seed);result: list[tuple[int, list[str]]] = []
    while len(result) < count:
        board=initial();player=0;passes=0
        while passes<2 and len(result)<count:
            moves=legal(board,player)
            if moves:
                passes=0
                if rng.random()<0.55:result.append((player,rows(board)))
                move(board,player,rng.choice(moves))
            else:passes+=1
            player^=1
    return result[:count]


def payload(items: list[tuple[int, list[str]]]) -> str:
    return "".join(str(side)+"\n"+"\n".join(board)+"\n" for side,board in items)


def run(command: list[str], data: str) -> list[str]:
    result=subprocess.run(command,input=data,text=True,capture_output=True,encoding="utf-8",timeout=900)
    if result.returncode!=0:raise RuntimeError(f"{command} failed: {result.stderr[-2000:]}")
    return result.stdout.splitlines()


def expected_mask(board: list[str], side: int) -> int:
    flat=[-1 if c=="." else int(c) for row in board for c in row]
    return sum(1<<cell for cell in legal(flat,side))


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpp",required=True)
    parser.add_argument("--java-classpath",required=True)
    parser.add_argument("--positions",type=int,default=4096)
    parser.add_argument("--seed",type=int,default=20260905)
    parser.add_argument("--raw-tolerance",type=float,default=2e-6)
    args=parser.parse_args();items=positions(args.positions,args.seed);data=payload(items)
    cpp_eval=run([args.cpp,"--eval"],data)
    java_eval=run(["java","-cp",args.java_classpath,"Player","--eval"],data)
    cpp_legal=run([args.cpp,"--legal"],data)
    if not(len(cpp_eval)==len(java_eval)==len(cpp_legal)==len(items)):
        raise SystemExit("FAIL output record count mismatch")
    max_raw=0.0;integer_mismatches=0
    for i,(item,ce,je,lm) in enumerate(zip(items,cpp_eval,java_eval,cpp_legal)):
        ci,cr=ce.split();ji,jr=je.split();diff=abs(float(cr)-float(jr));max_raw=max(max_raw,diff)
        if int(ci)!=int(ji):integer_mismatches+=1
        if int(lm,16)!=expected_mask(item[1],item[0]):raise SystemExit(f"FAIL legal mask at position {i}")
        if not math.isfinite(diff) or diff>args.raw_tolerance:raise SystemExit(f"FAIL eval at {i}: cpp={ce}, java={je}")
    print(f"PASS positions={len(items)} max_raw_error={max_raw:.3g} integer_mismatches={integer_mismatches}")
    return 0


if __name__=="__main__":raise SystemExit(main())
