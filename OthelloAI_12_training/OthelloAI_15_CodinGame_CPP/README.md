# OthelloAI 15 CodinGame C++17 edition

This directory contains the optimized successor to
`C:\Code\OthelloAI_14_CodinGame_CPP`. The default `Player.cpp` is
`cpp16_fast_lazy`; the version-14 behavior remains available as an internal
reference candidate.

## What is implemented

- Official CodinGame Othello input and `d3`-style move output
- 64-bit bitboards for legal moves and flips
- Incrementally updated ternary line/pattern indices
- Four-phase learned N-tuple value evaluator
- Iterative deepening, negamax alpha-beta, PVS/NegaScout, aspiration windows
- Transposition tables and the Java baseline's legacy MPC coefficients
- Exact endgame search at ten or fewer empty squares
- Strict fallback to an official legal action on timeout or initialization error
- No opening book, no policy head, no search parallelism, and no runtime model file
- Persistent root-evaluation cache and lazy additional-feature cache
- Compact transposition metadata and less frequent clock polling
- Exact-search TT move ordering and a specialized one-empty solver

The internal search budget is 115 ms by default. `Player.cpp` loads the compact
25,436-weight model but does not expand every learned pattern entry at startup.
Pattern and additional-feature values are calculated only when first referenced
and are then cached. Repeated leaf positions use a separate evaluation cache.
This preserves the Java evaluator's integer result while avoiding CodinGame
startup timeouts. The standard four-stone opening is symmetric, so the black
first move is returned without search (about 6--7 ms locally); subsequent moves
use the evaluator and normal search. Standard output contains only the chosen
coordinate; diagnostics go to standard error when compiled with
`-DOTHELLO_DIAGNOSTICS=1`.

## Files

- `Player.cpp`: generated `cpp16_fast_lazy`, ready to paste into CodinGame
- `candidates/Player_cpp16_lazy_reference.cpp`: version-14-equivalent reference
- `template/PlayerTemplate.cpp`: common single-file C++17 source template
- `model/width16_param.txt`: 25,436-value model used by the Java rank reference
- `model/width48_param.txt`: 142,812-value width-48 MSE candidate model
- `candidates/Player_cpp16_optimized.cpp`: fixed-point evaluator candidate
- `candidates/Player_cpp48.cpp`: separately gated width-48 candidate
- `candidates/Player_cpp_egaroucid_enhanced.cpp`: optimized evaluator plus
  exact-search TT move ordering and one-empty specialization
- `tools/build_submission.py`: deterministic width-16 source generator
- `tools/build_cpp48_submission.py`: tensor-local 11-bit width-48 generator,
  with a self-contained DEFLATE decoder
- `tools/codingame_arena_adapter.py`: CodinGame protocol to `othello_arena.py`
- `tests/`: protocol, perft, exact-solver, and Java/C++ parity checks
- `build_all.ps1`, `test_all.ps1`: local build and regression entry points
- `arena_match.ps1`: short wrapper for paired arena experiments

Generated binaries and result JSON files are intentionally not source assets.

## Build

PowerShell:

```powershell
Set-Location C:\Code\OthelloAI_15_CodinGame_CPP
powershell -ExecutionPolicy Bypass -File .\build_all.ps1
```

Equivalent baseline-only command:

```powershell
python .\tools\build_submission.py --variant cpp16_fast_lazy --output .\Player.cpp
g++ -std=c++17 -O2 -Wall -Wextra -pedantic -finput-charset=UTF-8 .\Player.cpp -o .\build\Player.exe
```

Do not add `-march=native` or BMI2 requirements to a CodinGame submission until
the target CPU has been verified. `Player.cpp` requires C++17 only.

## Regression checks

```powershell
powershell -ExecutionPolicy Bypass -File .\test_all.ps1
```

The suite checks:

- first-turn and normal-turn protocol deadlines, EOF, legal output, stdout purity
- standard initial-position perft through depth 8
- exact values for independently solved positions with 0 through 12 empties
- 4,096 reachable positions against `C:\Code\OthelloAI_11_CodinGame\Player`
- p50, p95, p99, and maximum response latency

The default fast-lazy candidate is expected to have zero legal-move and integer
evaluation differences from Java. Tiny raw floating-point differences below
`1e-7` are allowed. The fixed-point candidate is deliberately approximate.

## Arena examples

Twenty games (10 colour-swapped pairs), version 15 against its version-14 reference:

```powershell
.\arena_match.ps1 -TypeA cpp -TargetA .\build\Player.exe -NameA cpp15_fast_lazy -TypeB cpp -TargetB .\build\Player_cpp16_lazy_reference.exe -NameB cpp14_lazy_reference -Pairs 10
```

Two C++ candidates:

```powershell
.\arena_match.ps1 -TypeA cpp -TargetA .\build\Player.exe -NameA cpp15_fast_lazy -TypeB cpp -TargetB .\build\Player_cpp16_lazy_reference.exe -NameB cpp14_lazy_reference -Pairs 128
```

The adapter allows for process startup, while the separate protocol test
enforces the actual 2,000/150 ms limits. The baseline's lazy pattern cache does
not rely on background execution between CodinGame turns.

## Candidate policy

`Player.cpp` is the only version-15 file intended for immediate CodinGame
submission. A 20-game smoke against the lazy reference finished 9 wins, 2 draws,
and 9 losses, with no faults. This establishes functional neutrality, not a
statistically significant strength gain. Use 256-game screening and then a
fresh-seed 1,024-game match before claiming improvement. Increase the 115 ms
budget only after CodinGame timing data leaves sufficient margin under 150 ms.

`cpp48` is generated because it currently fits the source gate, but it is not
the default: it sits very close to the 100,000 UTF-16-unit limit and evaluation
cost can reduce completed search depth.

## License and provenance

This work is derived in part from Egaroucid 7.8.2 by Takuto Yamana (Nyanyan),
commit `112981e381801a38604f54714d46eb9d90322b80`. Egaroucid-derived bitboard,
move-ordering, stability-bound, and search ideas remain GPL-3.0-or-later. The
copyright and license header must stay in generated submissions. See `LICENSE`
and `THIRD_PARTY_NOTICES.md`.
