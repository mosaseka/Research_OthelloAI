# Version-15 experiment order

Keep `OthelloAI_14_CodinGame_CPP` and the Java width-16 bot unchanged as fixed
references. Use colour-swapped pairs, the same random-opening seed, and the
same 115 ms internal budget.

1. `Player.cpp` (`cpp16_fast_lazy`) vs `Player_cpp16_lazy_reference.cpp`: 10
   pairs smoke. The implementation run ended 9-2-9 for both sides.
2. Repeat the same comparison with 128 pairs screening.
3. Compare `cpp16_fast_lazy` with Java width 16 to measure the complete
   language-and-search change.
4. Treat `Player_cpp16_optimized.cpp`, `Player_cpp48.cpp`, and
   `Player_cpp_egaroucid_enhanced.cpp` as independent experimental candidates.
5. Only candidates that pass screening proceed to a new-seed 512-pair match.

The adoption target is at least 52% score over 1,024 games, with zero illegal
moves, timeouts, crashes, or stdout contamination. Also compare completed
depth, nodes, evaluator calls, and p50/p95/p99 latency. A CodinGame leaderboard
rank is supporting evidence, not a controlled A/B result.

The width-48 file is intentionally not the default. Its generated size is very
close to CodinGame's 100,000 UTF-16-unit cap, its startup is much slower, and
its heavier evaluator previously reduced completed depth in the Java experiment.
