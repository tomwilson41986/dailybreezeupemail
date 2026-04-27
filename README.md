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

## Local setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env        # fill in Gmail app password + recipient
```

Dry-run the job (no email sent; preview in `data/last_preview.html`):

```bash
breezeup-daily --dry-run
# or for a specific date:
breezeup-daily --dry-run --date 2026-04-24
```

Send for real:

```bash
breezeup-daily
```

Run tests:

```bash
pytest
```

## Secrets (GitHub repo → Settings → Secrets → Actions)

| Name | Purpose |
| --- | --- |
| `GMAIL_USER` | Full Gmail address used to authenticate SMTP |
| `GMAIL_APP_PASSWORD` | 16-char [app password](https://myaccount.google.com/apppasswords) (requires 2FA on the account) |
| `EMAIL_FROM` | Optional. Defaults to `GMAIL_USER`. Must be an alias of the Gmail account or Gmail will rewrite it. |
| `EMAIL_TO` | Recipient(s), comma-separated |

Gmail's SMTP limits: ~500 recipients/day on a consumer account, ~2,000/day on Workspace. One send/day to a small recipient list is nowhere near that.

Optional repo **variables**:

| Name | Default | Effect |
| --- | --- | --- |
| `NOTIFY_ON_EMPTY` | `false` | Set `true` to send a "nothing today" email even when there are zero hits. Useful as a heartbeat early in the season. |
| `ENTRIES_WINDOW_DAYS` | `5` | Forward window (in days, inclusive) for the "Entered" section. Set to a large number (e.g. `9999`) to surface every future entry currently flagged in the RP catalogue. |

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
