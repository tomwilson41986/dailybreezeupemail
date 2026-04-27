# Wrapper invoked by Windows Task Scheduler at 07:00 UK each day.
# Activates the project venv, runs breezeup-daily, appends stdout+stderr to
# a daily rolling log under .\logs\.
#
# Failure modes are logged but never silently swallowed - the script's exit
# code is propagated so the Task Scheduler "last run result" reflects reality.

$ErrorActionPreference = "Stop"

# scripts\run-daily.ps1 lives one level inside the repo root.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-Not (Test-Path $Python)) {
    Write-Error "Could not find .venv\Scripts\python.exe under $RepoRoot. Create the venv first: py -3.12 -m venv .venv ; .venv\Scripts\pip install -e ."
    exit 1
}

$LogDir = Join-Path $RepoRoot "logs"
if (-Not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$LogFile = Join-Path $LogDir ("breezeup-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

"==== {0} run start ====" -f ([DateTime]::UtcNow.ToString("o")) | Add-Content $LogFile

# 2>&1 merges stderr into stdout; both then stream to the log.
& $Python -m dailybreezeup.daily 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Null
$ExitCode = $LASTEXITCODE

"==== {0} run end (exit={1}) ====" -f ([DateTime]::UtcNow.ToString("o")), $ExitCode | Add-Content $LogFile
exit $ExitCode
