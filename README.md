# Daily Breeze-Up Email

Two scheduled emails per day listing breeze-up sale graduates, plus a Friday weekly digest:

- **Morning (04:00 UTC / 05:00 BST)** — `--mode morning`: entries & declarations for lots running in the next 3 days. Suppressed when empty unless `NOTIFY_ON_EMPTY=true`.
- **Evening (21:00 UTC)** — `--mode evening`: results for lots that ran today. Always sent — quiet days get a "No Results Today" notice.
- **Weekly (21:30 UTC Friday)** — `--mode weekly`: the week's results + the season-to-date tables, with the racing-results workbook attached (see below). Sent only to `WEEKLY_EMAIL_TO` (default tom.biggs, who gets this **instead of** the dailies — he's deliberately not in the daily recipient list).

Source is Racing Post's bloodstock sale catalogue (the authoritative join between a lot and its race entry), supplemented by the live racecards index for any entries the catalogue's `entry_details` field hasn't been updated to reflect.

## How it works

1. **Discover sales**: fetch `https://www.racingpost.com/bloodstock/sales/catalogues/` and filter to sale records whose name matches `/breeze.?up/i` in the current calendar year, plus the Tattersalls Guineas Horses-in-Training Sale (which runs the day after Craven and re-offers the unsold-at-Craven 2yos under Tatts' internal `breezeup2` catalogue). The Guineas HIT also contains older HIT lots — `fetch_lots` filters those out, keeping only age-2 rows. Typical 2026 set: Tattersalls Craven, Goffs UK 2yo Breeze Up, Tattersalls Guineas Horses-in-Training (2yos only), Arqana May 2yo Breeze Up, Tattersalls Ireland Breeze Up, Osarus Breeze-Up & HIT.
2. **Fetch lots per sale**: paginate `.../catalogues/<venue_uid>/<YYYY-MM-DD>/data.json`. Each row is one catalogued lot with an `entered` flag, a `horse_uid` (once RP has registered the horse), and an `entry_details` pointer to one race.
3. **Classify**:
   - **Morning · Entered**: union of two joins, deduped by `(lot_id, race_uid)`:
     - **Racecards uid-join (primary, next `ENTRIES_WINDOW_DAYS`=3 days)**: collect every `horse_uid` across all catalogues, walk RP's racecards for each day in the window, emit one row per declared (non-)runner whose uid is in our set. This carries the silk URL and live race metadata (off-time, race name) and is what reliably catches a grad **running today** — the catalogue's `entry_details` often points at a future engagement, not the imminent declared run. The window is kept tight because this scrape is expensive (one racecard walk per day) and declarations only publish ~48h out. As a fallback for lots RP hasn't linked a `horse_uid` to yet, runners are also matched **by name** (guarded on age so a name shared with an older horse can't false-match). RP serves racecards as a Next.js app, so runner/race data is read from the page's `__NEXT_DATA__` JSON, not HTML attributes — see `rp_racecards.py`.
     - **Catalogue `entry_details` (fallback, next `CATALOGUE_ENTRIES_WINDOW_DAYS`=7 days)**: covers any entry where the catalogue points at a race RP hasn't yet ingested into the racecards index. The catalogue is fetched for free and knows about entries days before they reach the racecards (UK flat entries close at the 5-6 day stage), so it gets a wider horizon — without it, a grad whose only engagement is 4+ days out is dropped from every morning email until the race falls inside the racecard window. The 7-day cap stops short of the months-out long-range entries the catalogue also carries.
   - **Evening · Ran today**: collect every `horse_uid`, fetch `/results/<today>`, walk each race page, emit one row per `/profile/horse/<uid>` link whose uid is in our set.
4. **Render** HTML + plain-text email with inline silks (rasterised from RP's SVGs to white-backed PNGs via resvg-py) and send via Gmail SMTP. Each `(run_date, category, lot_id, race_uid)` is logged to `email_log` to dedup re-runs within the day.

The catalogue JSON is authoritative for lot metadata (sire/dam, vendor, price, buyer); the racecards/results scrape is authoritative for race metadata (course, off-time, finishing position, silks). The join is by `horse_uid` wherever possible; name matching is only a guarded fallback for lots RP hasn't yet linked a uid to (so a declared runner is never missed just because its catalogue lot lags).

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
| `EMAIL_TO` | secret | Recipient(s), comma-separated. Three Blandford Bloodstock addresses are always included on top of this — see `_ALWAYS_RECIPIENTS` in `config.py`. tom.biggs is weekly-only (see `WEEKLY_EMAIL_TO`). |
| `WEEKLY_EMAIL_TO` | variable (optional) | Recipient(s) of the Friday weekly summary, comma-separated. Defaults to tom.biggs@blandfordbloodstock.com. These addresses get the weekly instead of the dailies. |
| `SHEET_CSV_URL` | variable (optional) | Override the gSheet for ratings enrichment. Empty falls back to the default sheet. |
| `NOTIFY_ON_EMPTY` | variable (optional) | `true` to send a morning "nothing today" email on quiet days. Evening always sends regardless. |
| `ENTRIES_WINDOW_DAYS` | variable (optional) | Default 3. Forward window for the racecards scrape that powers the morning "Entries & declarations" section. |
| `CATALOGUE_ENTRIES_WINDOW_DAYS` | variable (optional) | Default 7. Forward window for the catalogue `entry_details` fallback — wider than the racecard window so entries known in the catalogue days ahead aren't dropped. |

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

## Racing results workbook (`scripts/racing_results_xlsx.py`)

One-shot report of how the gSheet cohort has fared on the track. Joins every
sheet row to RP's sale catalogues on (sale, lot), pulls each named horse's form
from the profile-tab endpoint (`/profile/tab/horse/<uid>/x/form`, where
`rpPostmark` = RPR), and writes an xlsx: the full sheet plus Horse Name / Runs /
First Time Out RPR / Peak RPR, and a per-Breeze-Rating-band summary (lots,
runners, avg FTO RPR, avg peak RPR, highest RPR). The build lives in
`dailybreezeup/results_report.py`; the Friday weekly email attaches the same
workbook.

```bash
.venv/bin/pip install -e ".[xlsx]"
.venv/bin/python scripts/racing_results_xlsx.py --out data/racing_results.xlsx
```

Same RP bot-filter caveats as the daily email. Behind a TLS-intercepting proxy
set `RP_IMPERSONATE=chrome110` (Chrome 124's post-quantum ClientHello upsets
some MITM stacks) and `CURL_CA_BUNDLE=<proxy CA>`.

## Daily Sales Catalogues (`salescatalogues-daily`)

A second, independent digest: one email a day listing every **New** and
**Active** thoroughbred sale catalogue worldwide, grouped by country (with flag
headings and per-sale-type icons), with the full list attached as a CSV.

- **What it pulls**: upcoming/active sales from a dozen auction houses —
  Tattersalls (UK) & Tattersalls Ireland, Tattersalls Online, Goffs (UK & IRE),
  Arqana (FR), BBAG (DE), Keeneland / Fasig-Tipton / OBS (US), Inglis / Magic
  Millions (AUS), and NZB / Gavelhouse (NZ). Online/digital sales are included
  and flagged.
- **Sale type**: each sale is bucketed into Yearling, Foal / Weanling,
  Broodmare, HIT (Horses in Training / Racing Age), Breeze Up (incl. Ready to
  Run) or Mixed.
- **Excluded**: Jumps / National Hunt and store sales, plus non-thoroughbred
  sales (Arabians, point-to-point, etc.). Store sales are the NH pipeline, so
  they're dropped; a small curated name list (`classify._EXCLUDE_NAMES`) catches
  well-known NH/store sales whose source listing carries no description to filter
  on (e.g. the Tattersalls Ireland Derby Sale).
- **New** 🆕: flagged the first day a catalogue appears in the feed. State is
  kept in `data/salescatalogues.sqlite` (`seen_catalogue.first_seen`), persisted
  across CI runs via the actions cache.
- **Active** 🔴: flagged from `ACTIVE_LEAD_DAYS` (default **2**) before the
  sale's first day through its last day.
- **Lot-level CSV**: the attached CSV lists every catalogued lot (one row per
  lot: lot no, horse, sex, colour, sire, dam, damsire, vendor) for sales whose
  catalogue is published. Each source has a `fetch_lots` adapter hitting that
  house's catalogue API/page (Tattersalls' 4D listing, Goffs' sale page,
  Arqana's lot grid, OBS/Keeneland/Fasig-Tipton/Gavelhouse/BBAG JSON APIs,
  Inglis/Magic Millions/NZB tables). Sales without a published catalogue (or
  behind auth, e.g. Inglis Digital) fall back to a single summary row. Damsire
  isn't published by every house. Only sales within `HORIZON_DAYS` are listed.

### How it works

1. `sources/registry.py` lists each house's `fetch()`. The job runs them all,
   isolating failures so one broken site can't sink the digest.
2. Each source returns `RawSale` records (name, date span, url, online flag, plus
   any status/description hint). `sources/base.parse_date_range` copes with the
   dozen published date formats (day-first vs US month-first, single/range/cross-
   month, ordinals, missing years inferred as the nearest upcoming).
3. `classify.py` drops out-of-scope sales, classifies the sale type, and sets the
   New/Active flags. `emailer.py` renders the country-grouped HTML/text and
   attaches `csvout.to_csv`.

### Where it runs

`.github/workflows/salescatalogues.yml` — 06:00 UTC daily plus manual dispatch
(date override, dry-run, notify-on-empty). Reuses the same Gmail secrets; set
`CATALOGUES_EMAIL_TO` to send the digest somewhere other than `EMAIL_TO`.
tom.biggs only receives the Friday edition — see `_FRIDAY_ONLY_RECIPIENTS`
in `salescatalogues/config.py`.

Local preview (writes `data/catalogues_preview.{html,txt,csv}`, no send):

```bash
.venv/bin/salescatalogues-daily --dry-run
```

The parsers are tested offline against captured page snapshots in
`tests/fixtures/salescatalogues/`, so a site redesign that breaks a selector
fails loudly in `tests/salescatalogues/test_sources.py` rather than silently
emptying the digest.

## Caveats

- **Scraping Racing Post is against their ToS.** The scrapers use browser-like headers, a warm-up request, and sleeps between per-race fetches. Monitor logs — if RP tightens, bump the curl_cffi `impersonate` version or adjust `_DOC_HEADERS` / `_XHR_HEADERS`.
- **Unregistered lots can't match.** Only lots with a `horse_uid` in the sale catalogue are joinable against racecards/results. Most breeze-up 2yos stay unnamed (and thus unregistered in RP's horse DB) until their first run, at which point they get a uid. In practice a horse that's running today is, by definition, registered.
- **France-only races**: RP's `/results/<date>` index is GB/IRE only. An Arqana graduate running at e.g. Deauville won't appear in evening results — but the morning racecards uid-join + the catalogue's `entry_details` will still surface the entry beforehand.
