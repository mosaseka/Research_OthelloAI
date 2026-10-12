$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Config = Join-Path $ProjectRoot `
    'config\value_13a_width48_mse.generated.json'
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw 'Run .\scripts\prepare_width48.ps1 after the second width-16 epoch.'
}
Set-Location -LiteralPath $ProjectRoot
& python .\training\train_wide_evaluator.py `
    --config $Config `
    --device cuda `
    --pipeline-verified
if ($LASTEXITCODE -ne 0) {
    throw "width48 MSE training failed with exit code $LASTEXITCODE"
}
