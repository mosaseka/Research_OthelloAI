param(
  [string]$JavaClassPath = "C:\Code\OthelloAI_11_CodinGame",
  [int]$ParityPositions = 4096
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

python .\tests\protocol_smoke.py --player .\build\Player.exe
if ($LASTEXITCODE -ne 0) { throw "protocol smoke failed" }
python .\tests\perft_regression.py --player .\build\Player.exe
if ($LASTEXITCODE -ne 0) { throw "perft regression failed" }
python .\tests\endgame_solver_regression.py --player .\build\Player.exe
if ($LASTEXITCODE -ne 0) { throw "endgame regression failed" }
python .\tests\compare_java_cpp.py --cpp .\build\Player.exe --java-classpath $JavaClassPath --positions $ParityPositions
if ($LASTEXITCODE -ne 0) { throw "fast lazy parity failed" }
python .\tests\compare_java_cpp.py --cpp .\build\Player_cpp16_lazy_reference.exe --java-classpath $JavaClassPath --positions $ParityPositions
if ($LASTEXITCODE -ne 0) { throw "lazy reference parity failed" }
python .\tests\compare_java_cpp.py --cpp .\build\Player_cpp16_optimized.exe --java-classpath $JavaClassPath --positions $ParityPositions --raw-tolerance 0.00005
if ($LASTEXITCODE -ne 0) { throw "optimized parity failed" }
python .\tests\protocol_smoke.py --player .\build\Player_cpp16_optimized.exe
if ($LASTEXITCODE -ne 0) { throw "optimized protocol smoke failed" }
python .\tests\protocol_smoke.py --player .\build\Player_cpp16_lazy_reference.exe
if ($LASTEXITCODE -ne 0) { throw "lazy reference protocol smoke failed" }
python .\tests\protocol_smoke.py --player .\build\Player_cpp_egaroucid_enhanced.exe
if ($LASTEXITCODE -ne 0) { throw "enhanced protocol smoke failed" }
if (Test-Path .\build\Player_cpp48.exe) {
  python .\tests\protocol_smoke.py --player .\build\Player_cpp48.exe
  if ($LASTEXITCODE -ne 0) { throw "cpp48 protocol smoke failed" }
}
python .\tools\validate_source.py .\Player.cpp .\candidates\Player_cpp16_lazy_reference.cpp .\candidates\Player_cpp16_optimized.cpp .\candidates\Player_cpp_egaroucid_enhanced.cpp .\candidates\Player_cpp48.cpp
if ($LASTEXITCODE -ne 0) { throw "source validation failed" }
python .\tools\benchmark_protocol.py --player .\build\Player_diagnostics.exe --turns 40 --opponent-delay-ms 100 --json .\build\benchmark_fast_lazy.json
if ($LASTEXITCODE -ne 0) { throw "fast lazy benchmark failed" }
python .\tools\benchmark_protocol.py --player .\build\Player_cpp16_lazy_reference_diagnostics.exe --turns 40 --opponent-delay-ms 100 --json .\build\benchmark_lazy_reference.json
if ($LASTEXITCODE -ne 0) { throw "lazy reference benchmark failed" }

Write-Host "All regression checks passed."
