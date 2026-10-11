# Local verification record

Verified on 2026-09-05 with MSYS2 g++ 15.2.0 and Python 3.13.

- All four generated candidates compiled as C++17.
- `Player_cpp48.cpp` also compiled without `-march=native` and without an
  explicit external zlib library.
- The baseline matched standard initial perft counts through depth 8
  (`390216` leaves at depth 8).
- A memoized independent solver matched 13 positions covering 0 through 12
  empty squares, including pass/terminal handling reached by the sample games.
- Across 4,096 deterministic reachable positions, `cpp16_baseline` matched the
  Java width-16 legal masks, integer evaluations, and raw evaluations exactly.
- `cpp16_optimized` had maximum raw error `7.16e-06`; 28/4,096 integer values
  differed because of fixed-point rounding.
- Across 512 deterministic positions, `cpp48` matched the generated Java
  width-48 integer evaluations; maximum raw difference was `1.38e-07`.
- Protocol smoke tests had no malformed/illegal output or abnormal exit.
- With lazy pattern evaluation, the baseline returned the symmetric black
  opening in about 6--7 ms locally. Normal searched responses completed in
  about 115.2 ms. The lazy evaluator does not rely on background work while a
  CodinGame process is paused between turns.
- A two-game arena adapter smoke completed normally and split 1--1.

Local 40-turn diagnostic benchmark:

| Candidate | First | normal p50 | normal p95 | normal p99 | mean completed depth |
|---|---:|---:|---:|---:|---:|
| cpp16_baseline | 6.2 ms | 115.17 ms | 115.24 ms | 115.27 ms | 12.87 |
| cpp16_optimized | 274.2 ms | 115.17 ms | 115.25 ms | 115.26 ms | 13.31 |

These timings are local evidence, not CodinGame guarantees. No 20/256/1,024
game strength experiment has been performed as part of implementation. Keep
`Player.cpp` as the first submission and advance candidates in the documented
order.
