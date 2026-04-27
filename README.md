# Daily Breeze-Up Email

A once-a-day email listing breeze-up sale graduates that either **ran today** or are **entered to run in the next 5 days**. Source is Racing Post's bloodstock sale catalogue (the authoritative join between a lot and its race entry).

## How it works

1. **Discover sales**: fetch `https://www.racingpost.com/bloodstock/sales/catalogues/` and filter to sale records whose name matches /breeze.?up/i in the current calendar year. Typical 2026 set: Tattersalls Craven, Goffs UK 2yo Breeze Up, Arqana May 2yo Breeze Up, Tattersalls Ireland Breeze Up.
2. **Fetch lots per sale**: paginate `.../catalogues/<venue_uid>/<YYYY-MM-DD>/data.json`. Each row is one catalogued lot with an `entered` flag and, if entered, an `entry_details` pointer to the race (course + date + race_uid).
3. **Classify**:
   - **Entered (next 5 days)**: rows where `entered=true` AND `entry_details.race_date` is between today and today+5 inclusive.
   - **Ran today**: collect every `horse_uid` across all catalogues, fetch `/results/<today>`, walk each race page, and emit one row per `/profile/horse/<uid>` link whose uid is in our set.
4. **Render** HTML + plain-text email, send via Gmail SMTP, log to `email_log` to dedup re-runs within the day.

The catalogue JSON is authoritative: Racing Post does the lot → horse → race join for us. We don't match by name (breeze-up lots are usually unnamed at sale time anyway).

## Where it runs

GitHub Actions runners get challenged by Racing Post's bot filter (Fastly), so the cron lives on a personal machine instead. The repo ships a Windows PowerShell wrapper + Task Scheduler instructions; on macOS or Linux the moving parts are the same (just substitute launchd or cron).

The GitHub Actions workflow is kept for **manual dispatches only** (Actions → daily-breezeup-email → Run workflow). The `--demo` flag bypasses the live RP fetch and renders the email with the four real entered Craven 2026 lots — handy for verifying the email layout regardless of where the runner sits.

## Local setup (Windows, the production path)

### 1. Prerequisites

```powershell
# In an admin PowerShell, if not already installed:
winget install Python.Python.3.12
winget install Git.Git
```

Open a fresh PowerShell so the new tools are on `$env:PATH`.

### 2. Clone and install

```powershell
cd $env:USERPROFILE
git clone https://github.com/tomwilson41986/dailybreezeupemail.git
cd dailybreezeupemail
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -e .
```

### 3. Configure secrets

Copy `.env.example` to `.env` and fill in:

```
GMAIL_USER=your.address@gmail.com
GMAIL_APP_PASSWORD=your16charapppassword
EMAIL_TO=racingsquared@gmail.com
NOTIFY_ON_EMPTY=true
ENTRIES_WINDOW_DAYS=5
```

`.env` is gitignored — the values stay on your machine.

### 4. Manual smoke test

```powershell
.\.venv\Scripts\breezeup-daily --dry-run
```

Expected log output (verbatim shape):

```
INFO  Discovering breeze-up sales for 2026
INFO  Sales found: 4
INFO    Tattersalls Craven Breeze Up Sale 2026: 182 lots (entered=4)
INFO    Goffs UK 2yo Breeze Up Sale 2026: NN lots (entered=K)
...
INFO  summary: {'demo': False, 'lots': 600+, 'entered_in_window': 4+, 'ran_today': 0}
```

If you see `Sales found: 0` and `RP catalogues index fetch failed`, your home IP is also being blocked and we'd need to switch to theracingapi.com.

For the full real send (no `--dry-run`):

```powershell
.\.venv\Scripts\breezeup-daily
```

The email should arrive at `EMAIL_TO` within a minute.

### 5. Schedule it daily at 07:00 UK

Run this **once** in an elevated PowerShell, replacing the path if you cloned elsewhere:

```powershell
$RepoRoot = "$env:USERPROFILE\dailybreezeupemail"
$Wrapper  = Join-Path $RepoRoot "scripts\run-daily.ps1"

$Action    = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`""

$Trigger   = New-ScheduledTaskTrigger -Daily -At 7:00am

$Settings  = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask `
    -TaskName "BreezeupDaily" `
    -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal `
    -Description "Daily breeze-up email - 07:00 UK"
```

`-StartWhenAvailable` means if the laptop is asleep at 07:00 the task runs as soon as it wakes; you don't lose a day.

To verify it's installed: open `taskschd.msc`, scroll to "Task Scheduler Library", look for `BreezeupDaily`.

To trigger it manually for testing without waiting for 07:00:

```powershell
Start-ScheduledTask -TaskName "BreezeupDaily"
```

To remove it:

```powershell
Unregister-ScheduledTask -TaskName "BreezeupDaily" -Confirm:$false
```

### 6. Where to look when something goes wrong

- **`logs\breezeup-YYYY-MM-DD.log`** in the repo — captures every run's full stdout/stderr.
- **Task Scheduler GUI** → BreezeupDaily → History tab — shows last-run result and any system-level errors.
- **Run tests** to make sure your environment is sane after a code update:
  ```powershell
  .\.venv\Scripts\pip install -e ".[dev]"
  .\.venv\Scripts\pytest
  ```

## Secrets reference

| Name | Where it lives | Purpose |
| --- | --- | --- |
| `GMAIL_USER` | `.env` (laptop) and/or GitHub repo secrets (manual dispatches) | Full Gmail address used to authenticate SMTP |
| `GMAIL_APP_PASSWORD` | same | 16-char [app password](https://myaccount.google.com/apppasswords) (requires 2FA on the account) |
| `EMAIL_FROM` | optional, same | Defaults to `GMAIL_USER`. Must be an alias of the Gmail account or Gmail will rewrite it. |
| `EMAIL_TO` | same | Recipient(s), comma-separated |
| `NOTIFY_ON_EMPTY` | same (or repo **variable** for GitHub) | `true` to send a "nothing today" email on quiet days. Recommended early season. |
| `ENTRIES_WINDOW_DAYS` | same | Default 5. Forward window for the "Entered" section. |

## Project layout

```
src/dailybreezeup/
  daily.py              # main entrypoint (cron target)
  emailer.py            # Gmail SMTP sender + Jinja render
  schema.sql            # SQLite DDL (email_log + run_log)
  db.py                 # connection + migrate()
  config.py             # env loader (pydantic-settings)
  racing/
    rp_sales.py         # sale discovery + lot fetcher (JSON)
    rp_results.py       # uid-joined today's results scraper
  templates/
    email.html.j2 email.txt.j2
.github/workflows/
  daily.yml             # 07:00 UK cron
data/
  breezeup.sqlite       # committed — run_log + email_log for dedup
tests/
  fixtures/racingpost/  # captured live HTML/JSON for offline parser tests
```

## Caveats

- **Scraping Racing Post is against their ToS.** The scraper uses browser-like headers, a warm-up request, and sleeps between per-race fetches. Monitor logs; if RP tightens their bot rules, adjust `_DOC_HEADERS` / `_XHR_HEADERS` in `racing/rp_sales.py` and `racing/rp_results.py`.
- **Unregistered lots can't match results.** Only lots with a `horse_uid` in the sale catalogue are joinable against today's results. Most breeze-up 2yos stay unnamed (and thus unregistered in RP's horse DB) until their first run, at which point they get a uid. So this is a minor issue in practice: a horse that has run is, by definition, registered.
- **Entries come from the catalogue itself**, not from a racecard scrape. This means the pipeline sees only entries RP has linked to a sale lot. If an entry exists on the BHA system but RP hasn't ingested it yet, we miss it — usually a lag of a few hours.
- **France-only races**: RP's `/results/<date>` index is GB/IRE only. An Arqana graduate running at e.g. Deauville won't appear in our results. Their **entries** will still be picked up via the catalogue (the `entry_details.course_name` field covers French courses).
