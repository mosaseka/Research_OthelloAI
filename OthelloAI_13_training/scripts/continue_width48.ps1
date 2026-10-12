[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('mse', 'bce')]
    [string]$Loss
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ($Loss -eq 'mse') {
    $Config = Join-Path $ProjectRoot `
        'config\value_13a_width48_mse.generated.json'
    $RunsRoot = Join-Path $ProjectRoot `
        'artifacts\value_13a_width48_mse_runs'
} else {
    $Config = Join-Path $ProjectRoot `
        'config\value_13b_width48_bce.generated.json'
    $RunsRoot = Join-Path $ProjectRoot `
        'artifacts\value_13b_width48_bce_runs'
}
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw 'Generated config is missing. Run prepare_width48.ps1 first.'
}
$Checkpoint = Get-ChildItem -LiteralPath $RunsRoot -Recurse `
    -Filter checkpoint_last.pt -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $Checkpoint) {
    throw "No checkpoint_last.pt was found under $RunsRoot"
}
Set-Location -LiteralPath $ProjectRoot
& python .\training\train_wide_evaluator.py `
    --config $Config `
    --resume $Checkpoint.FullName `
    --device cuda `
    --pipeline-verified
if ($LASTEXITCODE -ne 0) {
    throw "width48 $Loss continuation failed with exit code $LASTEXITCODE"
}
