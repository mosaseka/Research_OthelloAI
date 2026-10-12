# Baseline and A/B experiments

## Baseline identity

The source initially present in `original_04` was compiled separately before modification.

```text
OthelloAI_04.java
SHA-256 A45675E737A908B053F69EC8401C1DF169D12186C50352AE888D547910C039EE
```

For short-time process matches, `tools/prepare_instrumented_baseline.py` reads the untouched sibling source and creates a generated class under ignored `build/`. The only substitutions are class naming and test-time move-limit, thread-count, and RNG-seed hooks. The observed baseline source hash is:

```text
../original_03/OthelloAI_03.java
SHA-256 2edaa4c0a667be288d59a5aecad97b602ad0ada58ad7e817ff510cc7c88b7c3c
```

The resource files, JVM heap, thread count, opening generator, colors, and RNG seed were identical between engines.

## Arena validation

The first self-play smoke test used one paired opening at 50 random placements, 30 ms per move, one thread, and seed 20260715. Both games completed with no fault. Exchanging colors produced one win and one loss for each identical engine and average disc difference zero.

The initial A/B run asked an AI for output even on a pass. That exposed the baseline display bug where policy `-1` becomes `0 -1`, but it did not match the course `Client`, which does not invoke the AI on pass. Its four forfeits were discarded. The arena was corrected to record the pass without sending the board to either process, and all reported A/B runs below use that behavior.

## Aggregate search-change comparison

The `current` engine includes the proven correctness and performance repairs described in `current-architecture.md`; it still uses the original `resources/param.txt` and `resources/book.txt`.

Final validated working source SHA-256:

```text
OthelloAI_04.java
6B9243542982B1781BF0CF922AC29A64774E0634737545365BCAF3A7BC5B4F5E
```

| Move limit | Random opening placements | Games | Current W-D-L | Mean disc diff | Current depth | Baseline depth | Current NPS | Baseline NPS | Faults |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 ms | 24 | 8 | 6-0-2 | +7.25 | 8.24 | 6.82 | 980,685 | 276,809 | 0 |
| 200 ms | 32 | 16 | 8-0-8 | -2.00 | 8.38 | 7.89 | 932,620 | 352,265 | 0 |
| 500 ms | 40 | 8 | 3-0-5 | -0.50 | 8.26 | 8.30 | 576,242 | 187,140 | 0 |
| **Total** | mixed | **32** | **17-0-15** | **+0.69** | **8.31** | **7.62** | **901,392** | **301,005** | **0** |

The aggregate score rate is 53.125%. With no draws, the 95% Wilson interval for the win rate is approximately `[36.45%, 69.13%]`. Therefore these 32 games do **not** establish a statistically reliable playing-strength increase. They do establish, in the measured single-thread short-time settings, about 3.0 times the reported NPS and about 0.69 additional completed ply on average.

Result artifacts:

```text
results/ab-current-vs-baseline-100ms-v2.jsonl
results/ab-current-vs-baseline-100ms-v2-summary.json
results/ab-current-vs-baseline-200ms.jsonl
results/ab-current-vs-baseline-200ms-summary.json
results/ab-current-vs-baseline-500ms.jsonl
results/ab-current-vs-baseline-500ms-summary.json
```

## Adoption decision

- Keep the player-to-move TT key, stamped publication, old-worker cancellation, explicit final-to-final recursion, final root depth correction, and pass formatting because they repair demonstrable correctness or concurrency defects and have direct regression coverage.
- Keep constant-time TT generations because the measured node throughput improves substantially and no fair run produced a timeout, illegal move, or crash.
- Treat the 32-game win result as inconclusive. Do not claim a strength gain from it and do not tune constants against these few openings.
- No candidate evaluation parameters have been trained or adopted. `resources/param.txt` remains byte-for-byte unchanged.
- Before tournament use, run at least several hundred paired games for promising parameter candidates at short limits, followed by a smaller preregistered set near 9.5 seconds. Report conditions separately rather than pooling unlike time/opening distributions.

## Root thread-count check

The current engine was also compared against itself at 200 ms, with A using the production machine's 12 available processors and B forced to one thread. Eight paired games from 24 random opening placements finished without faults.

| Setting | W-D-L | Mean disc diff | Mean depth | Mean NPS |
|---|---:|---:|---:|---:|
| 12 threads | 4-0-4 | -1.75 | 9.26 | 1,254,840 |
| 1 thread | 4-0-4 | +1.75 | 8.85 | 1,047,392 |

This small test gives no win-rate evidence, but 12 threads completed about 0.41 more ply and reported about 20% more NPS. The default remains `availableProcessors`; `othello.threads`/`OTHELLO_THREADS` is retained for deterministic tests and machines where oversubscription must be controlled. Full result: `results/ab-threads12-vs-1-200ms-summary.json`.
