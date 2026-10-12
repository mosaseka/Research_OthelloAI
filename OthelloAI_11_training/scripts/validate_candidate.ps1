param(
  [Parameter(Mandatory=$true)][ValidateSet("value_11a", "value_11b")][string]$Variant,
  [Parameter(Mandatory=$true)][string]$Candidate,
  [Parameter(Mandatory=$true)][string]$CandidateSha256,
  [Parameter(Mandatory=$true)][string]$Report,
  [switch]$Execute
)
$Root = Split-Path -Parent $PSScriptRoot
$ConfigName = if ($Variant -eq "value_11a") { "candidate_gate_11a.json" } else { "candidate_gate_11b.json" }
$Arguments = @(
  (Join-Path $Root "tools\validate_candidate.py"),
  "--config", (Join-Path $Root "config\$ConfigName"),
  "--candidate", $Candidate,
  "--expect-candidate-sha256", $CandidateSha256,
  "--report", $Report
)
if (-not $Execute) { $Arguments += "--dry-run" }
& python @Arguments
exit $LASTEXITCODE
