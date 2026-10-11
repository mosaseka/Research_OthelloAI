param(
  [Parameter(Mandatory=$true)][ValidateSet("cpp","java")][string]$TypeA,
  [Parameter(Mandatory=$true)][string]$TargetA,
  [Parameter(Mandatory=$true)][ValidateSet("cpp","java")][string]$TypeB,
  [Parameter(Mandatory=$true)][string]$TargetB,
  [string]$NameA = "A",
  [string]$NameB = "B",
  [int]$Pairs = 10,
  [int]$RandomOpeningPlies = 4,
  [int]$Seed = 20260905,
  [string]$Arena = "C:\Code\othello_arena.py",
  [string]$Results = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Adapter = Join-Path $Root "tools\codingame_arena_adapter.py"
if (-not $Results) { $Results = Join-Path $Root "results" }
New-Item -ItemType Directory -Force $Results | Out-Null

function New-AdapterCommand([string]$Type, [string]$Target) {
  $Resolved = (Resolve-Path -LiteralPath $Target).Path
  $Option = if ($Type -eq "cpp") { "--engine" } else { "--java-classpath" }
  $Working = if ($Type -eq "cpp") { Split-Path -Parent $Resolved } else { $Resolved }
  return ('python "{0}" {1} "{2}" --cwd "{3}"' -f $Adapter, $Option, $Resolved, $Working)
}

$CommandA = New-AdapterCommand $TypeA $TargetA
$CommandB = New-AdapterCommand $TypeB $TargetB
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Base = Join-Path $Results "$NameA-vs-$NameB-$Stamp"

python $Arena `
  --ai-a $CommandA --ai-b $CommandB `
  --name-a $NameA --name-b $NameB `
  --pairs $Pairs --random-opening-plies $RandomOpeningPlies --seed $Seed `
  --move-timeout-ms 2200 --startup-timeout-ms 5000 `
  --summary "$Base-summary.json" --jsonl "$Base-games.jsonl" --progress auto
