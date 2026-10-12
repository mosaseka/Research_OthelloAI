$Root = Split-Path -Parent $PSScriptRoot
& python (Join-Path $Root "tools\dry_run_value_pipeline.py") `
  --config (Join-Path $Root "config\dry_run_value.json")
exit $LASTEXITCODE
