# Candidate experiment order

Keep the Java width-16 bot unchanged as the fixed reference. Use colour-swapped
pairs, the same random-opening seed, and the same 115 ms internal budget.

1. `Player.cpp` (`cpp16_baseline`) vs Java width 16: 10 pairs smoke.
2. Repeat with 128 pairs screening.
3. `Player_cpp16_optimized.cpp` vs `cpp16_baseline`: 10, then 128 pairs.
4. `Player_cpp48.cpp` and `Player_cpp_egaroucid_enhanced.cpp` are independent
   candidates. Compare each with the best accepted width-16 candidate.
5. Only candidates that pass screening proceed to a new-seed 512-pair match.

The adoption target is at least 52% score over 1,024 games, with zero illegal
moves, timeouts, crashes, or stdout contamination. Also compare completed
depth, nodes, evaluator calls, and p50/p95/p99 latency. A CodinGame leaderboard
rank is supporting evidence, not a controlled A/B result.

The width-48 file is intentionally not the default. Its generated size is very
close to CodinGame's 100,000 UTF-16-unit cap, its phase initialization is
deferred, and its heavier evaluator previously reduced completed depth in the
Java experiment.
