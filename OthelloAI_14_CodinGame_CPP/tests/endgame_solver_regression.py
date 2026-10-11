#!/usr/bin/env python3
"""Compare the C++ exact solver with a small memoized reference solver."""

from __future__ import annotations

import argparse
from functools import lru_cache
import random
import subprocess


DIRECTIONS=tuple((dy,dx) for dy in (-1,0,1) for dx in (-1,0,1) if (dy,dx)!=(0,0))


def initial()->tuple[int,...]:
    b=[-1]*64;b[27],b[28],b[35],b[36]=1,0,0,1;return tuple(b)


def flips(board:tuple[int,...],p:int,cell:int)->tuple[int,...]:
    if board[cell]!=-1:return ()
    y,x=divmod(cell,8);out=[]
    for dy,dx in DIRECTIONS:
        cy,cx=y+dy,x+dx;line=[]
        while 0<=cy<8 and 0<=cx<8 and board[cy*8+cx]==(p^1):line.append(cy*8+cx);cy+=dy;cx+=dx
        if line and 0<=cy<8 and 0<=cx<8 and board[cy*8+cx]==p:out.extend(line)
    return tuple(out)


def moves(board:tuple[int,...],p:int)->list[int]:return [c for c in range(64) if flips(board,p,c)]


def apply(board:tuple[int,...],p:int,cell:int)->tuple[int,...]:
    b=list(board);b[cell]=p
    for c in flips(board,p,cell):b[c]=p
    return tuple(b)


def terminal(board:tuple[int,...],p:int)->int:
    diff=board.count(p)-board.count(p^1);vacant=board.count(-1)
    return diff+vacant if diff>0 else diff-vacant if diff<0 else 0


@lru_cache(maxsize=None)
def solve(board:tuple[int,...],p:int,skipped:bool=False)->tuple[int,int]:
    legal=moves(board,p)
    if not legal:return (terminal(board,p),-1) if skipped else (-solve(board,p^1,True)[0],-1)
    best=-100;best_move=-1
    for cell in legal:
        value=-solve(apply(board,p,cell),p^1,False)[0]
        if value>best:best,best_move=value,cell
    return best,best_move


def make_positions(seed:int)->list[tuple[int,tuple[int,...]]]:
    rng=random.Random(seed);targets=set(range(13));out=[]
    while targets:
        board=initial();p=0;skips=0
        while skips<2:
            empty=board.count(-1)
            if empty in targets:out.append((p,board));targets.remove(empty)
            legal=moves(board,p)
            if legal:board=apply(board,p,rng.choice(legal));skips=0
            else:skips+=1
            p^=1
    return out


def rows(board:tuple[int,...])->list[str]:
    sym={-1:".",0:"0",1:"1"};return ["".join(sym[v] for v in board[y*8:y*8+8]) for y in range(8)]


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--player",required=True);parser.add_argument("--seed",type=int,default=20260905);args=parser.parse_args()
    items=make_positions(args.seed);payload="".join(str(p)+"\n"+"\n".join(rows(b))+"\n" for p,b in items)
    result=subprocess.run([args.player,"--solve"],input=payload,text=True,capture_output=True,encoding="utf-8",timeout=300,check=True)
    lines=result.stdout.splitlines()
    if len(lines)!=len(items):raise SystemExit("FAIL solver output count")
    for index,((p,b),line) in enumerate(zip(items,lines)):
        actual=int(line.split()[0]);expected,_=solve(b,p)
        if actual!=expected:raise SystemExit(f"FAIL position={index} empty={b.count(-1)} actual={actual} expected={expected}")
    print(f"PASS positions={len(items)} empties=0..12 cache={solve.cache_info().currsize}")
    return 0


if __name__=="__main__":raise SystemExit(main())
