# PowerShell launchers

All launchers resolve paths relative to `original_11_training`; they do not
depend on the current directory. `run_timing.ps1`, `run_11a_resume.ps1`,
`run_11a_fresh.ps1`, `run_11b.ps1`, and `continue_value.ps1` are plan-only
unless `-Execute` is supplied. `stage_candidate.ps1` is plan-only unless
`-Commit` is supplied. `validate_candidate.ps1` performs only its dry-run
preflight unless `-Execute` is supplied.

`run_dry_run.ps1` is intentionally executable because it is the bounded
temporary-directory smoke test. `parse_opponent_log.ps1` performs only
read/validation and exclusive diagnostic output writes.

Examples and the required ordering are in the repository-level `README.md`.
