# Daily Breeze-Up Email

A once-a-day email listing horses that have an **entry**, **declaration**, or **result** in UK / Ireland / France racing **and** were originally sold at a breeze-up sale, with your own per-lot ratings linked through to the source sheet.

Coverage (v1, 2026):

- **UK**: Tattersalls Craven Breeze Up, Tattersalls Guineas Breeze Up, Goffs UK Breeze Up (Doncaster)
- **IRE**: Goffs Breeze Up Sale (Kildare)
- **FR**: Arqana Breeze Up (Deauville)

## How it works

1. **You** maintain a Google Sheet (shared as "anyone with the link can view") with one row per lot. Columns: `Year, Sale, Lot, Sex, Sire, Dam, Vendor, Buyer, Price, OT Diff/M, OT Rank, SL 1F, SL GO, Breeze Rating, Precocity Rating` (and an optional `Horse` column — safe to leave empty for unnamed breeze-up juveniles).
2. **Seed**: `breezeup-seed --sheet <URL>` pulls the sheet via the CSV export endpoint and upserts each row into a local SQLite catalogue (`data/breezeup.sqlite`).
3. **Daily** (GitHub Actions, 07:00 UK):
   - pulls today's + tomorrow's declarations and today+2..today+7 entries from [The Racing API](https://theracingapi.com) (GB/IRE) and scrapes `france-galop.com` (FR);
   - pulls yesterday's results from the same sources;
   - **matches** each runner against the catalogue. Primary key is `(sire, dam, foal year)` because breeze-up horses are generally unnamed at sale. Horse name is used when present;
   - renders an HTML+plaintext email with your custom columns (Breeze Rating, Precocity Rating, OT Rank, SL 1F) embedded, and a deeplink to the specific sheet row;
   - sends via [Resend](https://resend.com) and logs the send to avoid duplicates on re-runs.

## Local setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env        # fill in keys + SHEET_URL
```

Seed the catalogue from your sheet:

```bash
breezeup-seed --sheet "$SHEET_URL" -v
```

Dry-run the daily job (no email sent, preview written to `data/last_preview.html`):

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
| `THE_RACING_API_USER` | HTTP Basic user for theracingapi.com |
| `THE_RACING_API_PASS` | HTTP Basic password |
| `RESEND_API_KEY` | Resend API key |
| `EMAIL_FROM` | Verified sender, e.g. `breezeup@yourdomain.com` |
| `EMAIL_TO` | Recipient(s), comma-separated |
| `SHEET_URL` | Google Sheet share link (must be "anyone with link can view") |

Before the first send, verify the `EMAIL_FROM` domain in Resend (SPF + DKIM). Optional repo **variable** `NOTIFY_ON_EMPTY=true` sends a "no hits" email even on quiet days.

## Sheet schema

Expected columns (case-insensitive, any order; unknown columns are ignored):

| Column | Required | Notes |
| --- | --- | --- |
| `Year` | ✅ | Four-digit sale year, e.g. `2026` |
| `Sale` | ✅ | One of: `Craven`, `Guineas`, `Goffs UK` (or `Doncaster`), `Goffs Ireland` (or `Goffs`), `Arqana` (or `Deauville`). Extend `sheet.SALE_MAPPING` to add more. |
| `Lot` | ✅ | Lot number, possibly with a suffix e.g. `123A` |
| `Sire` | ✅ | Matcher uses this + Dam + foal year |
| `Dam` | ✅ | |
| `Horse` | ➖ | Optional — add once a horse gets named |
| `Sex`, `Vendor`, `Buyer`, `Price` | ➖ | Displayed |
| `OT Diff/M`, `OT Rank`, `SL 1F`, `SL GO` | ➖ | Displayed as ratings block |
| `Breeze Rating`, `Precocity Rating` | ➖ | Displayed as highlighted tags |

Foal year is derived automatically as `Year - 2` (all breeze-up horses are 2yos at sale).

## Project layout

```
src/dailybreezeup/
  daily.py            # main entrypoint (cron target)
  seed.py             # catalogue seeder CLI (--sheet | --all | --sale | --vendor)
  sheet.py            # Google Sheet CSV ingestor
  matching.py         # normalize_name, horse_key, match()
  emailer.py          # Resend + Jinja render
  schema.sql          # SQLite DDL
  db.py               # connection + migrate()
  config.py           # env loader (pydantic-settings)
  models/             # pydantic: Sale, RawLot, RaceCard, Runner
  racing/
    theracingapi.py   # GB/IRE racecards + results via Racing API
    francegalop.py    # FR racecards + results scraped
    common.py         # shared HTTP session with retries
  scrapers/           # fallback: per-vendor catalogue scrapers
    tattersalls.py goffs_uk.py goffs_ie.py arqana.py
  templates/
    email.html.j2 email.txt.j2
.github/workflows/
  daily.yml                    # 07:00 UK cron — re-seeds from sheet, then sends
  weekly-catalogue-refresh.yml # Sundays, vendor-scraper fallback
data/
  breezeup.sqlite     # committed — the source of truth for cron runs
tests/
```

## Open questions / known gaps

- **France Galop selectors unverified** — `src/dailybreezeup/racing/francegalop.py::SELECTORS`. Iterate locally if FR cards don't populate.
- **Racing API tier**: code tries `/v1/racecards/pro` then falls back to `/v1/racecards/standard`.
- **Sale name mapping**: if you use a sale label not in `sheet.SALE_MAPPING`, the seed script logs and skips it. Add new entries there.
- **Vendor scrapers** (`scrapers/`) ship with unverified CSS selectors and are optional — the sheet is the primary source. Keep them if you want a daily cross-check against vendor sites.
- **Matching precision**: `(sire, dam, foal_year)` uniquely identifies a horse except in the rare case of identical sire+dam half-siblings foaled the same year (e.g. twins, or full siblings born in different months of the same calendar year). Add a `Horse` column later to disambiguate.
