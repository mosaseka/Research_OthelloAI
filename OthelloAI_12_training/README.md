# original_11 value training and diagnostics

This directory is independent from `original_10_training`. It trains only
candidate value functions for `original_11`; it never modifies
`original_09`, `original_10`, `original_11`, or `Client.java`. A generated
candidate remains under `artifacts/` until validation, explicit staging, and
arena A/B are all complete.

The production feature schema is `exact-mobility-v1`, with exactly 25,436
finite values. Training and validation use all four phases with unchanged
loss weights `[1, 1, 1, 1]`. Production configurations forbid record limits
and finite step limits.

## Environment

Run commands from this directory. The long-running copy may be placed at
`C:\Code\OthelloAI_11_training`; configured datasets already refer to the
prepared data under `C:\Code\OthelloAI_05_training`. The adopted source value
and Java source are read from the Box `original_11` directory. Java checks are
compiled with `javac --release 11`.

Required software:

- Python with PyTorch; for GPU execution, its CUDA build must report CUDA as
  available.
- A Java 11-compatible JDK providing both `java` and `javac`.
- The verified prepared Egaroucid v2 manifest and all train/val/test shards.

All launch scripts are in `scripts/README.md`. Except for the bounded dry-run,
the launchers are plan-only until `-Execute` is given.

## 0. Opponent-log diagnostics (not training data)

The repository contains raw/sidecar pairs for games 02, 04, and 05:

```text
diagnostics/opponent_logs/game_02_20260722_raw.txt
diagnostics/opponent_logs/game_02_20260722_metadata.json
diagnostics/opponent_logs/game_04_20260722_raw.txt
diagnostics/opponent_logs/game_04_20260722_metadata.json
diagnostics/opponent_logs/game_05_20260722_raw.txt
diagnostics/opponent_logs/game_05_20260722_metadata.json
```

Five losses were observed (approximately -2, -8, -1, -8, -8 discs), but raw
logs 01 and 03 are not available and must not be reconstructed or guessed.
Every diagnostic output is fixed to `training_eligible=false` and
`adoption_gate_eligible=false`.

The sidecar contract requires `usage=diagnostic_only`, matching source file,
engine colour and final score. The parser recognizes concatenated one-line
Client output, infers every move, replays it with independent Othello rules,
checks PUT/count/final-result consistency, and records source/metadata hashes.
If a log explicitly represents a pass by repeating a board snapshot, it is
accepted only when the mover has no legal move and the opponent does; its move
fields are null and `is_pass=true`. Outputs are exclusive; choose a new prefix
to rerun.

The diagnostic chain is fail-closed. Sidecars must contain
`usage="diagnostic_only"`, `training_eligible=false`, and
`adoption_gate_eligible=false`. Parsed records, regression records, Java bridge
reports, comparison records, and their manifests use the boolean fields
`diagnostic_only=true`, `training_eligible=false`, and
`adoption_gate_eligible=false`. A missing or different value stops the next
stage. The parser schema is `original-11-opponent-log-diagnostic-v1`; strict
regression records use `original-11-opponent-regression-v2`.

Example for game 04 (repeat with `02` and `05`):

```powershell
python .\diagnostics\parse_opponent_log.py `
  --input .\diagnostics\opponent_logs\game_04_20260722_raw.txt `
  --metadata .\diagnostics\opponent_logs\game_04_20260722_metadata.json `
  --output-prefix .\diagnostics\output\game_04_20260722

python .\diagnostics\build_opponent_regression.py `
  --parsed .\diagnostics\output\game_04_20260722.jsonl `
  --metadata .\diagnostics\opponent_logs\game_04_20260722_metadata.json `
  --output .\diagnostics\regression_sets\game_04_important.jsonl `
  --manifest .\diagnostics\regression_sets\game_04_important_manifest.json
```

For game 02, force the requested 30--34 and 38--44 stone positions in addition
to the normal automatic selection (the ranges do not consume
`--max-automatic` slots):

```powershell
python .\diagnostics\build_opponent_regression.py `
  --parsed .\diagnostics\output\game_02_20260722.jsonl `
  --metadata .\diagnostics\opponent_logs\game_02_20260722_metadata.json `
  --include-stones 30:34 --include-stones 38:44 `
  --output .\diagnostics\regression_sets\game_02_important.jsonl `
  --manifest .\diagnostics\regression_sets\game_02_important_manifest.json
```

Keep two hypotheses separate:

- Hypothesis A (game 05, 42/44 stones): possible book/mode transition. Its
  0.22 to -8.00 change and later 0.0-second moves require book-hit diagnostics;
  value ranks alone cannot establish a book hit.
- Hypothesis B (game 04, 29/31 stones): value/search move ranking. The pinned
  observed move is `[0,4]`, with logged value `+0.82` before it and `-4.45`
  at the next AI turn in the same phase.

`build_opponent_regression.py` forces both endpoints of each sidecar focus into
its output. These small observed-game sets are regression/explanation inputs
only, never fitting or adoption evidence.

Two-ply diagnostics are emitted only for the exact transition sequence
"immediate non-pass opponent move, then immediate non-pass AI move". The exact
machine-readable contract is
`two_ply_sequence_definition="immediate_non_pass_opponent_move_then_immediate_non_pass_ai_move"`.
`two_ply_sequence_valid` is true only for that sequence. If a PASS, game
boundary, missing transition, or additional opponent ply intervenes, all
reply/next-AI/two-ply value fields are null and
`two_ply_unavailable_reason` states why; no later turn is relabeled as a
two-ply continuation.

## 1. Bounded dry-run first

This reads the eight-record file fixture, performs one forward/backward update,
checks finite train/validation loss, atomically saves and reloads a format-2
checkpoint including optimizer/scheduler/early-stop/RNG state, exports 25,436
values in a temporary directory, and runs a small Java/Python parity check.
It does not read production datasets and leaves no persistent candidate.

```powershell
python .\tools\dry_run_value_pipeline.py --config .\config\dry_run_value.json
```

Equivalent launcher:

```powershell
.\scripts\run_dry_run.ps1
```

Do not start a long stage unless this reports every check passed.

## 2. One-epoch full-pass timing only

First print the plan:

```powershell
python .\tools\timing_value_pipeline.py `
  --config .\config\timing_only_value.json --device cuda
```

Then explicitly execute:

```powershell
python .\tools\timing_value_pipeline.py `
  --config .\config\timing_only_value.json --device cuda --execute
```

This uses the same production train/validation functions, batch size,
augmentation and four-phase full-pass supply as 11a/11b. It runs exactly one
training epoch and normal validation, records elapsed time/items per second,
GPU identity and both checkpoints under `artifacts/timing_only_runs/`, and
skips heldout test and export. `timing_manifest.json` is explicitly not an
adoption artifact. If interrupted, no partial-epoch checkpoint is used; rerun
the timing epoch from the beginning in a new exclusive run directory.

## 3. Train value_11a

The preferred 11a path imports the verified original_10 run ending at epoch
index 2 (three completed epochs), reuses its AdamW state, overrides only its
learning rate to the configured lower value, and starts the newly introduced
scheduler/early-stop/RNG tracking explicitly. The pinned legacy run directory
is:

```text
C:\Code\OthelloAI_10_training\artifacts\value_training_runs\run_20260720T102520Z_seed20260720
```

`resume.legacy_expected_parameter_init` intentionally names the historical
`original_10/resources/param.txt` string saved inside that checkpoint. It is a
history-integrity assertion, not the initialization file for original_11. The
current adopted `original_11/resources/value_param.txt` is separately verified
against source SHA-256 `ff16...ab6b1` before the checkpoint state is applied.

Plan-only preflight:

```powershell
python .\tools\resume_value_training.py `
  --config .\config\value_11a_resume.json `
  --run-dir C:\Code\OthelloAI_10_training\artifacts\value_training_runs\run_20260720T102520Z_seed20260720 `
  --device cuda
```

Add `--execute` only after reviewing the printed command. The pipeline runs
prepared-data verification, the required phase-stratified 2,048-example
overfit gate, then full-pass production training. Normal training does not use
the overfit subset.

If that exact legacy checkpoint or any required sidecar is unavailable, do not
substitute another checkpoint. Use the independent fresh fallback:

```powershell
python .\training\run_training_pipeline.py `
  --config .\config\value_11a_fresh.json --stage all --device cuda --dry-run

python .\training\run_training_pipeline.py `
  --config .\config\value_11a_fresh.json --stage all --device cuda
```

## 4. Train independent value_11b

11b starts from the adopted value with independent seed `20260721`; its first
run rejects every legacy/external checkpoint. Apart from seed/identity it uses
the same data, LR, scheduler, early stopping and phase weights as 11a.

```powershell
python .\training\run_training_pipeline.py `
  --config .\config\value_11b.json --stage all --device cuda --dry-run

python .\training\run_training_pipeline.py `
  --config .\config\value_11b.json --stage all --device cuda
```

## 5. Resume an interrupted original_11 run

Production checkpoints are format 2 and atomically bind model, AdamW,
scheduler, early-stop state, Python/Torch CPU/CUDA RNG, stable run identity,
source-model hash, data contract and a lineage ID. A safe resume always needs
the sibling `checkpoint_best.pt` and selects `checkpoint_last.pt`; never resume
from the best checkpoint.

For 11a, 11a-fresh, or 11b after at least one completed original_11 epoch:

```powershell
python .\tools\continue_value_training.py `
  --config .\config\value_11b.json `
  --checkpoint .\artifacts\value_11b_runs\run_YYYYMMDDTHHMMSSZ_seed20260721\checkpoint_last.pt `
  --device cuda
```

Review the plan, then add `--execute`. Replace the config/checkpoint pair with
the matching 11a variant when applicable. The helper rejects cross-variant,
legacy, external, completed, early-stopped, and mismatched-sidecar runs. The
trainer performs the authoritative format-2 payload/lineage checks. A Ctrl+C
during an epoch discards that partial epoch; continuation starts again at the
first epoch after the last complete checkpoint and creates a new exclusive run
directory. The required overfit gate is rerun by `--stage all`.

## 6. Validate candidates mechanically

Use the candidate path and SHA-256 written by its export manifest. The baseline
path and expected SHA-256 are pinned by the gate config and cannot be replaced
on the command line. First run the preflight:

```powershell
python .\tools\validate_candidate.py `
  --config .\config\candidate_gate_11a.json `
  --candidate .\artifacts\value_11a_candidate_001.txt `
  --expect-candidate-sha256 <64-hex-from-export-manifest> `
  --report .\artifacts\candidate_validation_value_11a_001.json `
  --dry-run
```

Remove only `--dry-run` to run the gate. For 11b, use its matching config/path.
The report requires:

- exactly 25,436 finite values and bound candidate/baseline hashes;
- 4,096-position Java/Python parity in exact-mobility mode;
- population-weighted overall/phase RMSE, at least 1% or 0.1-disc overall
  improvement, and no phase-3 regression;
- D4 direction-span inspection and non-worsening.

RMSE and D4 compare baseline and candidate through the same exact-mobility
feature path. A report is eligible for arena only when both
`decision.pass=true` and `decision.eligible_for_ab=true`.

## 7. Explain game-02/game-04/game-05 positions with fixed-depth Java search

After both candidate files exist, compare all legal moves and opponent replies.
This compiles the unchanged production source plus a diagnostic-only bridge in
a temporary directory. Example for game 04:

```powershell
python .\diagnostics\compare_candidate_values.py `
  --positions .\diagnostics\regression_sets\game_04_important.jsonl `
  --ai-source "C:\Users\mosas\Box\01_授業関連\3-1\計算機科学応用演習\2026_1\0_課題\2026_07_15_ネットワークプログラミング\original_11\OthelloAI_11.java" `
  --model original_10="C:\Users\mosas\Box\01_授業関連\3-1\計算機科学応用演習\2026_1\0_課題\2026_07_15_ネットワークプログラミング\original_10\resources\value_param.txt" `
  --model value_11a=.\artifacts\value_11a_candidate_001.txt `
  --model value_11b=.\artifacts\value_11b_candidate_001.txt `
  --baseline-label original_10 --shallow-depth 3 --deep-depth 7 `
  --output .\diagnostics\output\game_04_value_compare.jsonl `
  --manifest .\diagnostics\output\game_04_value_compare_manifest.json
```

Game 02's 30--34 and 38--44 stone positions have no sidecar `focus_role`.
Therefore its comparison must include `--all-positions`; omitting it is a hard
error instead of silently discarding the requested ranges:

```powershell
python .\diagnostics\compare_candidate_values.py `
  --positions .\diagnostics\regression_sets\game_02_important.jsonl `
  --all-positions `
  --ai-source "C:\Users\mosas\Box\01_授業関連\3-1\計算機科学応用演習\2026_1\0_課題\2026_07_15_ネットワークプログラミング\original_11\OthelloAI_11.java" `
  --model original_10="C:\Users\mosas\Box\01_授業関連\3-1\計算機科学応用演習\2026_1\0_課題\2026_07_15_ネットワークプログラミング\original_10\resources\value_param.txt" `
  --model value_11a=.\artifacts\value_11a_candidate_001.txt `
  --model value_11b=.\artifacts\value_11b_candidate_001.txt `
  --baseline-label original_10 --shallow-depth 3 --deep-depth 7 `
  --output .\diagnostics\output\game_02_value_compare.jsonl `
  --manifest .\diagnostics\output\game_02_value_compare_manifest.json
```

The output includes current value, every legal root move, static/shallow/deep
fixed-depth value and rank, observed rank, deep-best gap, every legal opponent
reply, the model-best reply, observed reply rank, and continuation value.  For
each candidate, `candidate_vs_baseline.all_root_moves` explicitly records every
root move's value/rank delta from `original_10` (candidate minus baseline;
negative rank delta means a higher candidate rank).

For each model,
`model_reports.<label>.root_rank_summaries.<static|shallow|deep>` contains
`best_move`, `best_value_disc`, `runner_up_move`, `runner_up_value_disc`, and
`best_minus_runner_up_gap_disc`. The viewpoint is the root player, larger is
better, values are discs, and the gap is best minus runner-up. Runner-up fields
are null when only one legal root move exists.

`candidate_vs_baseline.<candidate>.root_rank_summaries` stores these summary
deltas against `original_10`. In addition,
`model_pair_root_rank_summary_comparisons` contains every unordered model pair,
including value_11a versus value_11b; its declared delta is `right minus left`.

The comparison record and manifest both contain `root_ranking_contract`.
Static, shallow, and deep values are ordered descending using
`java.lang.Double.compare(right_value, left_value)` (larger is better),
then ties in the unrounded Java `double` score (before eight-decimal JSON
formatting) are broken by ascending zero-based row-major policy cell number
(`row * 8 + column`). Ranks are ordinal after this total ordering: they are
always `1,2,...,legal_move_count`, so equal values do not share competition or
dense ranks.

It also records the game's final engine result and disc difference.  Under
`final_result_error_by_model`, current/static/shallow/deep predictions are
compared with that final disc difference using signed error, absolute error and
win/draw/loss correctness.  These values all use the engine/root player at the
logged AI turn as the viewpoint and are measured in discs.  Run the same
command with game 05 paths to inspect its pinned 42/44-stone boards, but treat
those results as hypothesis-A supporting diagnostics only; the separate book
diagnostic must determine actual book hits.

## 8. Stage, then arena-test; do not adopt automatically

Staging is plan-only by default and now requires an explicit runtime target so
relocating this training tree to `C:\Code` cannot accidentally stage under the
wrong directory:

```powershell
python .\tools\stage_validated_candidate.py `
  --candidate .\artifacts\value_11a_candidate_001.txt `
  --validation-report .\artifacts\candidate_validation_value_11a_001.json `
  --variant value_11a `
  --target-root "C:\Users\mosas\Box\01_授業関連\3-1\計算機科学応用演習\2026_1\0_課題\2026_07_15_ネットワークプログラミング\original_11\resources\candidates"
```

Add `--commit` only after checking the plan. Commit writes a unique sibling
temporary directory, verifies hashes and metadata, then atomically renames it
to a numbered candidate directory. It does not replace active resources.

Only after the prescribed smoke/screening/1,024-game/9.5-second arena sequence
passes should a separately authorized adoption replace active resources.
Neither opponent diagnostics nor a successful mechanical gate is sufficient
by itself.
