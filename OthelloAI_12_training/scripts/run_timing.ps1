param(
  [string]$Device = "cuda",
  [switch]$Execute
)
$Root = Split-Path -Parent $PSScriptRoot
$Arguments = @(
  (Join-Path $Root "tools\timing_value_pipeline.py"),
  "--config", (Join-Path $Root "config\timing_only_value.json"),
  "--device", $Device
)
if ($Execute) { $Arguments += "--execute" }
& python @Arguments
exit $LASTEXITCODE
