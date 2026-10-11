#!/usr/bin/env python3
"""Measure C++ CodinGame response latency and emit p50/p95/p99 JSON."""

from __future__ import annotations

import argparse
import json
import random
import re
import queue
import statistics
import subprocess
import threading
import time

from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
from protocol_smoke import apply, coord, initial_board, legal, parse  # noqa: E402


def percentile(values:list[float],q:float)->float:
    ordered=sorted(values);return ordered[min(len(ordered)-1,max(0,int(round(q*(len(ordered)-1)))))]


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--player",required=True);parser.add_argument("--turns",type=int,default=200);parser.add_argument("--seed",type=int,default=20260905);parser.add_argument("--opponent-delay-ms",type=int,default=0);parser.add_argument("--json",type=Path);args=parser.parse_args()
    rng=random.Random(args.seed);process=subprocess.Popen([args.player],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",bufsize=1)
    assert process.stdin and process.stdout
    replies:queue.Queue[str|None]=queue.Queue();stderr_lines:list[str]=[]
    def read_stdout()->None:
        assert process.stdout
        for line in process.stdout:replies.put(line)
        replies.put(None)
    threading.Thread(target=read_stdout,daemon=True).start()
    def read_stderr()->None:
        assert process.stderr
        stderr_lines.extend(process.stderr)
    stderr_thread=threading.Thread(target=read_stderr,daemon=True);stderr_thread.start()
    process.stdin.write("0\n8\n");process.stdin.flush();latencies=[];board=initial_board();p=0
    while len(latencies)<args.turns:
        ms=legal(board,p)
        if not ms:
            if not legal(board,p^1):board=initial_board();p=0
            else:p^=1
            continue
        if p==0:
            payload=["".join(r) for r in board]+[str(len(ms))]+[coord(m) for m in ms]
            start=time.perf_counter();process.stdin.write("\n".join(payload)+"\n");process.stdin.flush()
            try:answer=replies.get(timeout=2.1)
            except queue.Empty as error:raise RuntimeError(f"engine timeout at turn {len(latencies)} board={payload[:8]}") from error
            if answer is None:raise RuntimeError(f"engine exited at turn {len(latencies)} code={process.poll()}")
            latencies.append((time.perf_counter()-start)*1000)
            chosen=parse(answer);assert chosen in ms;apply(board,p,chosen)
        else:
            apply(board,p,rng.choice(ms))
            if args.opponent_delay_ms:time.sleep(args.opponent_delay_ms/1000.0)
        p^=1
    process.stdin.close();process.wait(timeout=2);stderr_thread.join(timeout=1);stderr="".join(stderr_lines)
    normal=latencies[1:];metric_rows=[]
    for line in stderr.splitlines():
        match=re.search(r"METRIC variant=(\S+) depth=(\d+) nodes=(\d+) evals=(\d+) tt_hits=(\d+)",line)
        if match:metric_rows.append({"variant":match.group(1),"depth":int(match.group(2)),"nodes":int(match.group(3)),"evaluations":int(match.group(4)),"tt_hits":int(match.group(5))})
    search=metric_rows[1:] if len(metric_rows)==len(latencies) else metric_rows
    report={"turns":len(latencies),"opponent_delay_ms":args.opponent_delay_ms,"first_ms":latencies[0],"normal_turns":len(normal),"mean_ms":statistics.fmean(normal),"p50_ms":percentile(normal,.50),"p95_ms":percentile(normal,.95),"p99_ms":percentile(normal,.99),"max_ms":max(normal),"normal_under_150ms":sum(v<150 for v in normal),"exit_code":process.returncode}
    if search:report["search"]={"metric_rows":len(search),"variant":search[0]["variant"],"completed_depth_mean":statistics.fmean(row["depth"] for row in search),"completed_depth_min":min(row["depth"] for row in search),"completed_depth_max":max(row["depth"] for row in search),"nodes_mean":statistics.fmean(row["nodes"] for row in search),"evaluations_mean":statistics.fmean(row["evaluations"] for row in search),"tt_hits_mean":statistics.fmean(row["tt_hits"] for row in search)}
    text=json.dumps(report,ensure_ascii=False,indent=2);print(text)
    if args.json:args.json.write_text(text+"\n",encoding="utf-8")
    return 0 if process.returncode==0 and report["first_ms"]<2000 and report["normal_under_150ms"]==len(normal) else 1


if __name__=="__main__":raise SystemExit(main())
