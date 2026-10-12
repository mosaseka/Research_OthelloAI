param(
    [string]$Compiler = 'C:\msys64\ucrt64\bin\g++.exe'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildDirectory = Join-Path $ProjectRoot 'build'
$Output = Join-Path $BuildDirectory 'egaroucid_policy_converter.exe'

if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) {
    throw "g++ was not found: $Compiler"
}

New-Item -ItemType Directory -Force -Path $BuildDirectory | Out-Null

Push-Location -LiteralPath $ProjectRoot
try {
    # Relative ASCII paths also work when the Box project path contains
    # Japanese characters that MinGW's narrow argv cannot represent.
    & $Compiler `
        -std=c++17 `
        -O3 `
        -DNDEBUG `
        -march=native `
        -Wall `
        -Wextra `
        -Wpedantic `
        -pthread `
        -static `
        -static-libgcc `
        -static-libstdc++ `
        '.\converter\egaroucid_policy_converter.cpp' `
        -o '.\build\egaroucid_policy_converter.exe'

    if ($LASTEXITCODE -ne 0) {
        throw "C++ converter compilation failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host "Built: $Output"
