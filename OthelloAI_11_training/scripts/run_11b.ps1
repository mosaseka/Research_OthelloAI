param(
  [string]$Device = "cuda",
  [switch]$Execute
)
$Root = Split-Path -Parent $PSScriptRoot
$Arguments = @(
  (Join-Path $Root "training\run_training_pipeline.py"),
  "--config", (Join-Path $Root "config\value_11b.json"),
  "--stage", "all",
  "--device", $Device
)
if (-not $Execute) { $Arguments += "--dry-run" }
& python @Arguments
exit $LASTEXITCODE
