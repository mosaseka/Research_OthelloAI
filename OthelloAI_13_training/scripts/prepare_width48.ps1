[CmdletBinding()]
param(
    [string]$SourceRunsRoot =
        'C:\Code\OthelloAI_12_training\artifacts\value_12a_runs',
    [switch]$Overwrite
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LastCheckpoint = Get-ChildItem -LiteralPath $SourceRunsRoot -Recurse `
    -Filter checkpoint_last.pt -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $LastCheckpoint) {
    throw "checkpoint_last.pt was not found under $SourceRunsRoot"
}
$BestCheckpoint = Join-Path $LastCheckpoint.Directory.FullName 'checkpoint_best.pt'
if (-not (Test-Path -LiteralPath $BestCheckpoint -PathType Leaf)) {
    throw "checkpoint_best.pt is missing beside $($LastCheckpoint.FullName)"
}

$Initialization = Join-Path $ProjectRoot `
    'artifacts\width48_initial_from_value12a.txt'
$InitializationManifest = Join-Path $ProjectRoot `
    'artifacts\width48_initial_from_value12a.json'
$MseConfig = Join-Path $ProjectRoot `
    'config\value_13a_width48_mse.generated.json'
$BceConfig = Join-Path $ProjectRoot `
    'config\value_13b_width48_bce.generated.json'
$OverwriteArgument = @()
if ($Overwrite) {
    $OverwriteArgument = @('--overwrite')
}

Write-Host "Width-16 last checkpoint: $($LastCheckpoint.FullName)"
Write-Host "Width-16 best checkpoint: $BestCheckpoint"

& python (Join-Path $ProjectRoot 'tools\prepare_width48_initial.py') `
    --checkpoint $LastCheckpoint.FullName `
    --best-checkpoint $BestCheckpoint `
    --output $Initialization `
    --manifest $InitializationManifest `
    @OverwriteArgument
if ($LASTEXITCODE -ne 0) {
    throw "width-48 initialization failed with exit code $LASTEXITCODE"
}

& python (Join-Path $ProjectRoot 'tools\materialize_width48_config.py') `
    --template (Join-Path $ProjectRoot `
        'config\value_13a_width48_mse.template.json') `
    --initialization-manifest $InitializationManifest `
    --output $MseConfig `
    @OverwriteArgument
if ($LASTEXITCODE -ne 0) {
    throw "MSE config materialization failed with exit code $LASTEXITCODE"
}

& python (Join-Path $ProjectRoot 'tools\materialize_width48_config.py') `
    --template (Join-Path $ProjectRoot `
        'config\value_13b_width48_bce.template.json') `
    --initialization-manifest $InitializationManifest `
    --output $BceConfig `
    @OverwriteArgument
if ($LASTEXITCODE -ne 0) {
    throw "BCE config materialization failed with exit code $LASTEXITCODE"
}

Write-Host ''
Write-Host 'Preparation complete. Start MSE first with:'
Write-Host 'powershell -ExecutionPolicy Bypass -File .\scripts\run_13a_width48_mse.ps1'
