# Current architecture of OthelloAI_05

This document describes the engine in `original_05`, derived from the validated
`original_04` implementation. The production source and resources are:

```text
OthelloAI_05.java
resources/book.txt
resources/param.txt
```

`resources/param.txt` and `resources/book.txt` are inherited byte-for-byte. New
learned parameters are exported under `artifacts/` and selected with
`-Dothello.param=PATH`; the production parameter is never overwritten implicitly.

## 1. Board representation

`Board` stores:

- `int[38] b`: redundant line encodings of the board;
- `p`: player to move (`0` black, `1` white);
- `policy`: last move as `y * 8 + x`;
- `v`: temporary move-ordering value;
- `n`: number of occupied cells.

The 38 lines are eight rows, eight columns, eleven diagonals in one direction, and eleven in the other. Every line is an eight-digit base-3 integer. A digit is `0` for black, `1` for white, and `2` for empty. Unused positions of short diagonals remain `2`. Local position zero is the most significant ternary digit.

At startup, all `3^8 = 6561` possible line states are expanded into tables:

- `legal_arr[player][line][position]`;
- `move_arr` for the number of flips in both directions;
- `flip_arr` for changing one occupied digit to the mover's color;
- `put_arr` for placing a stone;
- stone-count, mobility-like, frontier-like, reverse, and digit lookup tables.

`place_included` and `local_place` map a global cell to its three or four lines. `move` copies all 38 integers, applies flips on every affected line, places the stone in every containing line, changes `p`, and increments `n`. It assumes the caller already checked legality.

Passes are represented inside search by copying the board, changing only `p`, and retaining `n` and search depth. Two consecutive no-move nodes call `end_game`.

## 2. Legal moves and terminal score

A cell is legal when at least one containing line reports it legal for `p`. The original search scans `vacant_lst`, which is rebuilt from each protocol input. It is not shortened after simulated moves; occupied cells are rejected by the lookup table.

The terminal score counts the first eight line encodings (the rows), converts the black-white difference to the side-to-move perspective, assigns any remaining empty cells to the current winner, and multiplies by 100. The arena separately records the actual final black-white disc difference so this engine convention is not confused with the match result.

## 3. Evaluation function

The evaluator has four phases and eleven learned pattern subnetworks. The phase is:

```text
clamp((occupied - 4) / 10 - 2, 0, 3)
```

With Java integer division, the ranges are 4-33, 34-43, 44-53, and 54-64 occupied cells.

Pattern sizes are:

```text
[8, 8, 8, 5, 6, 7, 8, 10, 10, 10, 10]
```

For each pattern and phase, a small MLP is loaded:

```text
2 * pattern_size one-hot inputs -> 16 -> 16 -> 1
```

Black and white have separate one-hot inputs; empty is zero in both. Every layer output, including the scalar output, uses leaky ReLU `max(x, 0.01*x)`. All ternary states are evaluated during initialization. A pattern-specific geometric reverse is evaluated and added to each table entry.

The auxiliary MLP is:

```text
3 inputs -> 8 -> 8
```

Its inputs are the signed line-counted mobility-like value divided by 30 and black/white frontier-like line counts normalized as `(value - 15) / 15`. These counts deliberately include duplicates across the 38 line representations; they are not exact unique-cell counts. Its full discrete input range is also precomputed.

The final layer combines eleven pattern-group sums and eight auxiliary outputs into one scalar with 19 weights and one bias. The scalar is negated when white is to move, clipped to `[-1, 1]`, multiplied by 6400, and converted to `int` by Java truncation toward zero.

`BoardCache` and `evalCache` are declared but are not used by `evaluate`.

## 4. Parameter file

The production file is `resources/param.txt`; `-Dothello.param=PATH` can select a candidate without overwriting it.

For each of four phases, the read order is:

1. Pattern 0 through pattern 10.
2. For each pattern of size `s`:
   - dense0 weights, input-major: `2*s*16`;
   - bias0: `16`;
   - dense1 weights, previous-layer-major: `16*16`;
   - bias1: `16`;
   - dense2 weights: `16`;
   - bias2: `1`.
3. Auxiliary dense0, input-major: `3*8`.
4. Auxiliary bias0: `8`.
5. Auxiliary dense1, previous-layer-major: `8*8`.
6. Auxiliary bias1: `8`.
7. Final weights: `19`.
8. Final bias: `1`.

The eleven pattern networks require `6235` values per phase because their sizes sum to 90. The auxiliary and final sections require `104 + 20`, for `6359` values per phase and exactly:

```text
4 * 6359 = 25436 values
```

The observed file has exactly 25,436 nonblank finite values and SHA-256 `D2351C23DCD4CD09AEAD2A0D9DAC46F4BFF2FFFC18633C397156330F5FB26B0E`.

## 5. Opening book

The production file is `resources/book.txt`; `-Dothello.book=PATH` may select another file.

It is one compressed line of 105,894 characters. The 64-character alphabet maps its index directly to `y*8+x`:

```text
!#$&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abc
```

Each of 4,915 records is:

```text
zero or more history characters, one ASCII space, one recommended move
```

The next record starts immediately after the recommendation. Histories start from the canonical five-stone position after black plays `(4,5)`, with white to move. The loader replays the history and registers the recommendation under four symmetries. Independent replay found:

- 4,915 source records;
- 19,660 registration attempts;
- 17,480 distinct stored positions;
- zero illegal history or recommendation moves;
- at most four stored policies for one key.

Duplicate identical policies act as probability weights. Book choice uses a seedable `Random`; set `-Dothello.seed=N` or `OTHELLO_SEED=N` for reproducible tests. The observed book SHA-256 is `39EB45BBE3E776462E5E4D1D21A686EEFDB280F35DD4A2C0F8B68509B3135F78`.

## 6. Search

The midgame stack is:

- plain negamax alpha-beta at shallow depth;
- alpha-beta with move ordering;
- NegaScout/PVS with a 100-unit null window;
- a hybrid MTD loop that narrows a wide interval before NegaScout;
- Multi-ProbCut at configured depths;
- iterative deepening at the root;
- root-sibling parallel null-window searches when there are more than four moves.

Move ordering uses prior transposition bounds when available, otherwise `-evaluate(child)`. Endgame ordering also penalizes the opponent's exact legal-move count.

The transposition table has two direct-mapped arrays of 1,048,576 slots. A packed key uses the first eight row lines plus the player to move. Bounds are stored from that player's perspective. The two tables alternate between the preceding iteration and the current iteration. Per-table generations invalidate a table in constant time instead of scanning and allocating more than two million nodes at startup and scanning one million entries per iteration. Parallel in-place updates use a writer lock and a volatile stamp so readers reject torn data.

## 7. Endgame search

`main` switches to `finalSearch` at 44 or more occupied cells (20 or fewer empty cells). With 10-20 empties it first creates an approximate fallback by searching to nine plies short of the end, then attempts the selective endgame search. The last three empty cells have specialized routines.

The inherited implementation already calls final-search variants recursively. In
the root PVS loop, however, a promising non-first move used `max_depth` for its
full-window re-search while the first and null-window child searches used
`max_depth - 1`. At a ten-empty root this incorrectly put the nine-empty child
back on the final-MPC boundary. `OthelloAI_05` defines one
`childDepth = max_depth - 1` and uses it for all three child-search paths.

The regression fixture is a fixed ten-empty position whose evaluation-order
leader is cell 0 but whose strict alpha-beta best move is cell 50 with value
1000. It proves that a non-first candidate is re-searched at depth 9 and that
the production root policy and value match a strict search of every child.

At 10-20 empties the configured final Multi-ProbCut still makes the search selective, so it should not be described as a mathematical proof of the result at all those depths.

## 8. Time management and parallel work

The production default remains 9,500 ms. It is configurable only for testing:

```text
-Dothello.moveTimeMs=N        or OTHELLO_MOVE_TIME_MS=N
-Dothello.threads=N           or OTHELLO_THREADS=N
-Dothello.seed=N              or OTHELLO_SEED=N
```

The deadline reserves up to 75 ms (5% for short limits) for protocol output. Search checks every 2,048 counted nodes. Root setup and some ordering work occur between checks.

Each move receives a generation. Worker threads attach to that generation, and clearing the timer invalidates it. This prevents a cancelled old root task from continuing after timeout and reading a newly rebuilt `vacant_lst` or writing into the next move's table. Node and diagnostic counters remain approximate under parallel execution.

When a book policy is already known, the working version returns it with a static evaluation instead of spending most of the move budget on a depth-10 search whose result did not influence the selected policy.

## 9. Standard I/O protocol

After all tables and resources are loaded, stdout is:

```text
READY
```

The process then reads its color once as one line, `0` or `1`. For every requested move it reads eight rows of eight characters (`0`, `1`, `.`). It outputs:

```text
y x evaluation
```

Coordinates are zero-based. Consumers that read only the first two fields remain compatible. All diagnostics go to stderr. A pass is normally handled by the match controller without asking the AI; if called on a no-move board, the working version emits `-1 -1 value` instead of the Java division artifact `0 -1`.

## 10. Baseline issues found and disposition

| Issue in initial source | Risk | Working status |
|---|---|---|
| Final NegaScout called normal heuristic search | wrong endgame result | fixed and regression-tested |
| Promising final-root sibling was re-searched one ply too deep | candidate-dependent MPC boundary | fixed with one child depth and a strict-root regression fixture |
| TT key omitted player to move | wrong-sign bounds after a pass | fixed and regression-tested |
| Two million TT nodes allocated and one million slots cleared per iteration | startup and search-time loss | lazy allocation plus constant-time generations |
| Parallel TT readers could observe partially overwritten fields | incorrect cutoff | stamped publication added |
| Cancelled root workers could survive into the next input | race with board/vacancy/table state | per-move worker generation added |
| Exact-hit ordering bonus was smaller than one-bound bonus | weaker ordering | made consistent with root ordering |
| Book move was followed by a search that could not change it | needless delay | direct output with evaluation |
| No-legal policy `-1` printed as `0 -1` | malformed standalone pass | explicit `-1 -1` |
| `searched_nodes` and hash diagnostic counters are racy | approximate metrics/time-check cadence | still open; does not define search value |
| Extensive `Board`, list, and tiny bound-array allocation | GC/NPS loss | open for measured follow-up |
| Input and resource parsing had limited validation | poor failure diagnostics | tests validate current resources; hardening remains follow-up |
| Root parallelism waits for futures in submission order | head-of-line delay | open for isolated A/B test |
| Existing learned evaluator is not exactly D4-invariant on every asymmetric position (a regression fixture differed by 7/6400 after 90-degree rotation) | orientation-dependent small score drift | rules are tested exactly; retraining uses D4 grouping/augmentation, runtime 8-way averaging was not adopted because of its cost |

## 11. Reproducibility

The baseline is compiled to a separate output before source changes. `tools/prepare_instrumented_baseline.py` reads the untouched sibling baseline and generates a copy under `build/` with only class-name and test time/thread/seed hooks. Its manifest records both hashes. It never edits the baseline.

`tools/arena.py` is the independent rules authority for A/B games. It generates one legal random opening per pair, runs it twice with A/B colors exchanged, detects illegal moves, timeouts and crashes, and saves the opening, seeds, moves, actual final disc difference, depth, NPS, and summary statistics.
