param(
  [Parameter(Mandatory=$true)][string]$Config,
  [Parameter(Mandatory=$true)][string]$Checkpoint,
  [string]$Device = "cuda",
  [switch]$Execute
)
$Root = Split-Path -Parent $PSScriptRoot
$Arguments = @(
  (Join-Path $Root "tools\continue_value_training.py"),
  "--config", $Config,
  "--checkpoint", $Checkpoint,
  "--device", $Device
)
if ($Execute) { $Arguments += "--execute" }
& python @Arguments
exit $LASTEXITCODE
