# original_13 width-48 evaluator training

This directory is independent from `C:\Code\OthelloAI_12_training`.
Nothing here is read by the currently running width-16 job.

## Experiment isolation

Both candidates start from the same function-preserving width-48 expansion of
the best model from the completed two-epoch width-16 run.  Deterministic
zero-sum perturbations are applied to outgoing replica weights: the initial
evaluator output is preserved, but the 48 replicas receive different
gradients and can actually diverge during training.

1. `value_13a_width48_mse`: width 48, final disc difference / 64, MSE.
2. `value_13b_width48_bce`: width 48, win=1/draw=0.5/loss=0,
   `BCEWithLogitsLoss`.

Do not initialize BCE from the trained MSE candidate.  Using the same widened
initialization is necessary to isolate the loss-function change.

## After width-16 epoch 2 finishes

Stop the old job only after its `checkpoint_last.pt` has been written.  Then:

```powershell
Set-Location "C:\Code\OthelloAI_13_training"
powershell -ExecutionPolicy Bypass -File .\scripts\prepare_width48.ps1
```

The preparation script selects the most recently written
`checkpoint_last.pt`, verifies that at least two epochs completed, pairs it
with `checkpoint_best.pt`, and creates:

- `artifacts/width48_initial_from_value12a.txt`
- `artifacts/width48_initial_from_value12a.json`
- `config/value_13a_width48_mse.generated.json`
- `config/value_13b_width48_bce.generated.json`

It duplicates every width-16 hidden unit three times, divides outgoing weights
by three, and adds verified zero-sum symmetry breaking.  The script refuses to
write an initialization unless both function preservation and nonzero symmetry
breaking are confirmed.

## Run MSE first

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_13a_width48_mse.ps1
```

The normal CUI progress bars remain enabled.  The run uses three full-pass
epochs with early stopping after at least two completed epochs.

If an epoch-boundary checkpoint exists after an interruption, continue with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\continue_width48.ps1 -Loss mse
```

## Run BCE only after MSE completes

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_13b_width48_bce.ps1
```

BCE model output is a logit.  Its runtime value transform is explicitly
recorded as `tanh(logit / 2) = 2 * sigmoid(logit) - 1`.

For an interrupted BCE run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\continue_width48.ps1 -Loss bce
```

## Important runtime constraint

Width-48 files contain exactly 142,812 values.  They are **not compatible**
with `original_11` or the current width-16 Java loader, which requires 25,436
values.  Do not copy a width-48 candidate into an existing runtime.

After training and offline validation, a separate Java runtime must be built:

- hidden widths 48/48;
- width-48 parameter count and parser;
- current clamp transform for MSE;
- `tanh(logit / 2)` transform for BCE;
- startup expansion into lookup tables;
- Java/Python parity tests.

Only after those checks may arena A/B testing begin.

## Quantization

Do not combine int8 lookup-table quantization with either learning experiment.
First select the better double/float model, then compare its full-precision and
int8 runtime tables as a separate A/B change.
