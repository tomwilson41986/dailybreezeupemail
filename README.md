# Daily Breeze-Up Email

Two scheduled emails per day listing breeze-up sale graduates:

- **Morning (04:00 UTC / 05:00 BST)** — `--mode morning`: entries & declarations for lots running in the next 3 days. Suppressed when empty unless `NOTIFY_ON_EMPTY=true`.
- **Evening (21:00 UTC)** — `--mode evening`: results for lots that ran today. Always sent — quiet days get a "No Results Today" notice.

Source is Racing Post's bloodstock sale catalogue (the authoritative join between a lot and its race entry), supplemented by the live racecards index for any entries the catalogue's `entry_details` field hasn't been updated to reflect.

## How it works

1. **Discover sales**: fetch `https://www.racingpost.com/bloodstock/sales/catalogues/` and filter to sale records whose name matches `/breeze.?up/i` in the current calendar year, plus the Tattersalls Guineas Horses-in-Training Sale (which runs the day after Craven and re-offers the unsold-at-Craven 2yos under Tatts' internal `breezeup2` catalogue). The Guineas HIT also contains older HIT lots — `fetch_lots` filters those out, keeping only age-2 rows. Typical 2026 set: Tattersalls Craven, Goffs UK 2yo Breeze Up, Tattersalls Guineas Horses-in-Training (2yos only), Arqana May 2yo Breeze Up, Tattersalls Ireland Breeze Up, Osarus Breeze-Up & HIT.
2. **Fetch lots per sale**: paginate `.../catalogues/<venue_uid>/<YYYY-MM-DD>/data.json`. Each row is one catalogued lot with an `entered` flag, a `horse_uid` (once RP has registered the horse), and an `entry_details` pointer to one race.
3. **Classify**:
   - **Morning · Entered (next 3 days)**: union of two joins, deduped by `(lot_id, race_uid)`:
     - **Racecards uid-join (primary)**: collect every `horse_uid` across all catalogues, walk RP's racecards for each day in the window, emit one row per runner whose uid is in our set. This carries the silk URL and live race metadata (off-time, race name).
     - **Catalogue `entry_details` (fallback)**: covers any entry where the catalogue points at a race RP hasn't yet ingested into the racecards index.
   - **Evening · Ran today**: collect every `horse_uid`, fetch `/results/<today>`, walk each race page, emit one row per `/profile/horse/<uid>` link whose uid is in our set.
4. **Render** HTML + plain-text email with inline silks (rasterised from RP's SVGs to white-backed PNGs via resvg-py) and send via Gmail SMTP. Each `(run_date, category, lot_id, race_uid)` is logged to `email_log` to dedup re-runs within the day.

The catalogue JSON is authoritative for lot metadata (sire/dam, vendor, price, buyer); the racecards/results scrape is authoritative for race metadata (course, off-time, finishing position, silks). We never match by name — breeze-up lots are usually unnamed at sale time anyway.

## Where it runs

Production cron lives in **GitHub Actions**: `.github/workflows/daily.yml` schedules 04:00 and 21:00 UTC runs on `ubuntu-latest`. The workflow uses `curl_cffi` (Chrome 124 TLS/HTTP-2 fingerprint) to bypass Racing Post's Fastly bot filter from cloud IPs — a plain `requests` UA gets a challenge page back.

To trigger a one-off run: **Actions → daily-breezeup-email → Run workflow**. Inputs cover date override, dry-run, demo mode (skips live RP fetch — handy for layout checks), mode override, entries window, and `notify_on_empty`.

## Secrets

Configured under repo settings → Secrets / Variables → Actions. The workflow reads them as env vars:

| Name | Kind | Purpose |
| --- | --- | --- |
| `GMAIL_USER` | secret | Full Gmail address used to authenticate SMTP. |
| `GMAIL_APP_PASSWORD` | secret | 16-char [app password](https://myaccount.google.com/apppasswords) (requires 2FA on the account). |
| `EMAIL_FROM` | secret (optional) | Defaults to `GMAIL_USER`. Must be an alias of the Gmail account or Gmail will rewrite it. |
| `EMAIL_TO` | secret | Recipient(s), comma-separated. Three Blandford Bloodstock addresses are always included on top of this — see `_ALWAYS_RECIPIENTS` in `config.py`. |
| `SHEET_CSV_URL` | variable (optional) | Override the gSheet for ratings enrichment. Empty falls back to the default sheet. |
| `NOTIFY_ON_EMPTY` | variable (optional) | `true` to send a morning "nothing today" email on quiet days. Evening always sends regardless. |
| `ENTRIES_WINDOW_DAYS` | variable (optional) | Default 3. Forward window for the morning "Entries & declarations" section. |

## Local development

For making changes — not for production sending. Tests run offline against captured fixtures, so you don't need RP access.

```bash
git clone https://github.com/tomwilson41986/dailybreezeupemail.git
cd dailybreezeupemail
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

To exercise the pipeline against live RP from a non-blocked IP, copy `.env.example` to `.env` and:

```bash
.venv/bin/breezeup-daily --mode morning --dry-run
.venv/bin/breezeup-daily --mode evening --dry-run
```

`--dry-run` writes `data/last_preview.html` / `last_preview.txt` instead of sending. `--demo` skips the RP fetch and renders against hardcoded fixture lots — useful for template work.

## Project layout

```
src/dailybreezeup/
  daily.py              # main entrypoint (cron target)
  emailer.py            # Gmail SMTP sender + Jinja render
  silks.py              # silk SVG fetch + resvg-py rasterise + CID attach
  schema.sql            # SQLite DDL (email_log + run_log)
  db.py                 # connection + migrate()
  config.py             # env loader (pydantic-settings)
  sheet.py              # gSheet ratings join (Breeze, Precocity, OT, SL)
  racing/
    rp_sales.py         # sale discovery + lot fetcher (JSON)
    rp_racecards.py     # uid-joined racecards scraper (entries window)
    rp_results.py       # uid-joined results scraper (evening)
  templates/
    email.html.j2       # rendered HTML (inline silks via cid:)
.github/workflows/
  daily.yml             # 04:00 / 21:00 UTC cron + manual dispatch
data/
  breezeup.sqlite       # committed — run_log + email_log for dedup
tests/
  fixtures/racingpost/  # captured live HTML/JSON/SVG for offline tests
```

## Caveats

- **Scraping Racing Post is against their ToS.** The scrapers use browser-like headers, a warm-up request, and sleeps between per-race fetches. Monitor logs — if RP tightens, bump the curl_cffi `impersonate` version or adjust `_DOC_HEADERS` / `_XHR_HEADERS`.
- **Unregistered lots can't match.** Only lots with a `horse_uid` in the sale catalogue are joinable against racecards/results. Most breeze-up 2yos stay unnamed (and thus unregistered in RP's horse DB) until their first run, at which point they get a uid. In practice a horse that's running today is, by definition, registered.
- **France-only races**: RP's `/results/<date>` index is GB/IRE only. An Arqana graduate running at e.g. Deauville won't appear in evening results — but the morning racecards uid-join + the catalogue's `entry_details` will still surface the entry beforehand.
