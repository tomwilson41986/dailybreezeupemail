# Wrapper invoked by Windows Task Scheduler twice a day:
#   07:00 UK - morning email (entries & declarations, next 3 days)
#   21:00 UK - evening email (results that ran today; "No Results Today" if none)
#
# Pass -Mode morning|evening from the scheduled task action. Defaults to
# morning so a one-off manual invoke without args still does something useful.
#
# Failure modes are logged but never silently swallowed - the script's exit
# code is propagated so the Task Scheduler "last run result" reflects reality.

param(
    [ValidateSet("morning", "evening")]
    [string]$Mode = "morning"
)

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
$LogFile = Join-Path $LogDir ("breezeup-{0}-{1}.log" -f (Get-Date -Format "yyyy-MM-dd"), $Mode)

"==== {0} run start ({1}) ====" -f ([DateTime]::UtcNow.ToString("o")), $Mode | Add-Content $LogFile

# 2>&1 merges stderr into stdout; both then stream to the log.
& $Python -m dailybreezeup.daily --mode $Mode 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Null
$ExitCode = $LASTEXITCODE

"==== {0} run end (exit={1}) ====" -f ([DateTime]::UtcNow.ToString("o")), $ExitCode | Add-Content $LogFile
exit $ExitCode
