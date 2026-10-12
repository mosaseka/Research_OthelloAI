param(
  [Parameter(Mandatory=$true)][ValidateSet("value_11a", "value_11a_fresh", "value_11b")][string]$Variant,
  [Parameter(Mandatory=$true)][string]$Candidate,
  [Parameter(Mandatory=$true)][string]$ValidationReport,
  [Parameter(Mandatory=$true)][string]$TargetRoot,
  [switch]$Commit
)
$Root = Split-Path -Parent $PSScriptRoot
$Arguments = @(
  (Join-Path $Root "tools\stage_validated_candidate.py"),
  "--variant", $Variant,
  "--candidate", $Candidate,
  "--validation-report", $ValidationReport,
  "--target-root", $TargetRoot
)
if ($Commit) { $Arguments += "--commit" }
& python @Arguments
exit $LASTEXITCODE
