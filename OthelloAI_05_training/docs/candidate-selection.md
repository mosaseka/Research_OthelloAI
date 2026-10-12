# Evaluator candidate selection

`resources/param.txt` is the immutable baseline. Candidate files stay under
`artifacts/` and must pass `tools/validate_candidate.py` before any A/B stage.

## Mechanical gate

Run from `original_05`:

```powershell
python tools/validate_candidate.py `
  --candidate artifacts/param_candidate_001.txt `
  --baseline resources/param.txt `
  --config config/candidate_gate.json `
  --report artifacts/param_candidate_001-validation.json
```

The command exits zero only when all of these checks pass:

- both files contain exactly 25,436 finite values;
- the candidate is exactly equal to Java on 4,096 deterministic reachable
  positions, including integer value, raw value, phase, and auxiliary indices;
- the held-out split seed and ratios exactly match `config/train_full.json`;
- overall held-out RMSE improves by at least 1% **or** 0.1 disc;
- phase 3 RMSE does not worsen;
- D4 direction spans are measured for every phase and satisfy any optional
  limits in `config/candidate_gate.json`.

The held-out sample is the deterministic lowest-hash stratified sample from
the training test split. The report records phase counts and a sample SHA-256.
Overall RMSE combines the four sampled phase MSE values using the exact
held-out population counts observed during the full scan; it is not an
equal-phase average. Phase RMSE values remain separately visible.
D4 is an inspection gate by default: its spans are always reported, while a
numerical limit or non-worsening requirement can be preregistered in config.

Raw Egaroucid data is streamed from its ZIP and must not be committed.

## Paired A/B stages

Compile once, then use one command template for both processes. The runner
replaces only `{param}`, so search code, classpath, heap, working directory,
threads, engine seed, and opening generation are identical.

```powershell
javac -encoding UTF-8 -d build/current OthelloAI_05.java
$engine = 'java -Xmx1g -Dothello.param={param} -cp build/current OthelloAI_05'
$common = @(
  '--candidate-param', 'artifacts/param_candidate_001.txt',
  '--baseline-param', 'resources/param.txt',
  '--gate-report', 'artifacts/param_candidate_001-validation.json',
  '--engine-command', $engine
)
python tools/run_ab_stage.py --stage smoke @common
python tools/run_ab_stage.py --stage screening @common
python tools/run_ab_stage.py --stage acceptance @common
python tools/run_ab_stage.py --stage practical @common
```

Each later command locates the preceding summary in the candidate/hash result
directory and refuses to start unless it passed. It also verifies candidate
and baseline SHA-256 values against both the validation report and preceding
stage. Existing stage output is not overwritten unless `--overwrite` is
explicitly supplied.

The preregistered settings in `config/ab_stages.json` are:

| Stage | Pairs | Games | Move limit | Advance rule |
|---|---:|---:|---:|---|
| smoke | 10 | 20 | 50 ms | complete, fault-free |
| screening | 128 | 256 | 150 ms | complete, fault-free, pair score >= 50%, mean discs >= 0 |
| acceptance | 512 | 1,024 | 200 ms | complete, fault-free, pair 95% CI lower bound > 50%, mean discs > 0 |
| practical | 32 | 64 | 9.5 s | allowed only after acceptance; complete and fault-free |

Stages use distinct preregistered opening seeds, so screening positions are not
reused as adoption evidence. Within every pair, the exact same opening is
played twice with colours exchanged.

## Statistical unit

One independent observation is a complete colour-swapped pair, not one game.
For A, pair score is `(game0 score + game1 score) / 2`, so its possible values
are 0, 0.25, 0.5, 0.75, and 1. The Wilson interval uses the sum of those scores
as successes and the number of complete pairs as trials. Pair W/D/L is shown
separately by comparing pair score with 0.5; it is never substituted for the
fractional score in the interval.

Mean disc difference is first averaged over the two games and then over pairs.
Incomplete, mismatched-opening, or non-colour-swapped pairs are excluded from
strength statistics and make `require_complete` fail. Timeout, illegal move,
malformed output, crash, or any other forfeit makes the zero-fault gate fail.
