param(
  [Parameter(Mandatory=$true)][string]$LegacyRunDir,
  [string]$Device = "cuda",
  [switch]$Execute
)
$Root = Split-Path -Parent $PSScriptRoot
$Arguments = @(
  (Join-Path $Root "tools\resume_value_training.py"),
  "--config", (Join-Path $Root "config\value_11a_resume.json"),
  "--run-dir", $LegacyRunDir,
  "--device", $Device
)
if ($Execute) { $Arguments += "--execute" }
& python @Arguments
exit $LASTEXITCODE
