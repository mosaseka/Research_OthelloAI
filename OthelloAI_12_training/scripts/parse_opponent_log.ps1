param(
  [Parameter(Mandatory=$true)][string]$Input,
  [Parameter(Mandatory=$true)][string]$Metadata,
  [Parameter(Mandatory=$true)][string]$OutputPrefix
)
$Root = Split-Path -Parent $PSScriptRoot
& python (Join-Path $Root "diagnostics\parse_opponent_log.py") `
  --input $Input --metadata $Metadata --output-prefix $OutputPrefix
exit $LASTEXITCODE
