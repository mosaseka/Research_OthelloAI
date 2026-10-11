param(
  [int]$BudgetMs = 115,
  [switch]$SkipCpp48
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
New-Item -ItemType Directory -Force .\build | Out-Null

python .\tools\build_submission.py --variant cpp16_baseline --budget-ms $BudgetMs --output .\Player.cpp
if ($LASTEXITCODE -ne 0) { throw "cpp16_baseline generation failed" }
python .\tools\build_submission.py --variant cpp16_optimized --budget-ms $BudgetMs --output .\candidates\Player_cpp16_optimized.cpp
if ($LASTEXITCODE -ne 0) { throw "cpp16_optimized generation failed" }
python .\tools\build_submission.py --variant cpp_egaroucid_enhanced --budget-ms $BudgetMs --output .\candidates\Player_cpp_egaroucid_enhanced.cpp
if ($LASTEXITCODE -ne 0) { throw "cpp_egaroucid_enhanced generation failed" }
if (-not $SkipCpp48) {
  python .\tools\build_cpp48_submission.py --budget-ms $BudgetMs --output .\candidates\Player_cpp48.cpp
  if ($LASTEXITCODE -ne 0) { throw "cpp48 generation failed" }
}

$Common = @("-std=c++17", "-O2", "-Wall", "-Wextra", "-pedantic", "-finput-charset=UTF-8")
& g++ @Common .\Player.cpp -o .\build\Player.exe
if ($LASTEXITCODE -ne 0) { throw "cpp16_baseline compilation failed" }
& g++ @Common .\candidates\Player_cpp16_optimized.cpp -o .\build\Player_cpp16_optimized.exe
if ($LASTEXITCODE -ne 0) { throw "cpp16_optimized compilation failed" }
& g++ @Common .\candidates\Player_cpp_egaroucid_enhanced.cpp -o .\build\Player_cpp_egaroucid_enhanced.exe
if ($LASTEXITCODE -ne 0) { throw "cpp_egaroucid_enhanced compilation failed" }
if (-not $SkipCpp48) {
  & g++ @Common -pthread .\candidates\Player_cpp48.cpp -o .\build\Player_cpp48.exe
  if ($LASTEXITCODE -ne 0) { throw "cpp48 compilation failed" }
}
& g++ @Common -DOTHELLO_DIAGNOSTICS=1 .\Player.cpp -o .\build\Player_diagnostics.exe
if ($LASTEXITCODE -ne 0) { throw "diagnostic compilation failed" }
& g++ @Common -DOTHELLO_DIAGNOSTICS=1 .\candidates\Player_cpp16_optimized.cpp -o .\build\Player_cpp16_optimized_diagnostics.exe
if ($LASTEXITCODE -ne 0) { throw "optimized diagnostic compilation failed" }
& g++ @Common -DOTHELLO_DIAGNOSTICS=1 .\candidates\Player_cpp_egaroucid_enhanced.cpp -o .\build\Player_cpp_egaroucid_enhanced_diagnostics.exe
if ($LASTEXITCODE -ne 0) { throw "enhanced diagnostic compilation failed" }

Write-Host "Build complete: $Root\build"
