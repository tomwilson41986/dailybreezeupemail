# Barrier-trial tracker

A parallel pipeline to the breeze-up job (`dailybreezeup`), tracking a watchlist
of barrier-trial horses on Racing Post. The cohort comes from a Google Sheet of
barrier-trial horses (not a sale catalogue), and matching is **name-first**: a
horse's Racing Post `horse_uid` is learned the first time it shows up on a
racecard/result and reused thereafter.

Two emails:

* **Morning (entries):** each horse entered/declared in the next few days, with
  its full sheet row, **plus that horse's results so far this season** (since
  `SEASON_START_DATE`).
* **Evening (results):** today's results with the full sheet row, then a
  **historic results tracker** — performance per rating band, and every tracked
  horse that has run with its individual results.

Both read from `results_archive`, which the evening run self-heals back to
`SEASON_START_DATE`; the morning run also tops it up (the two share a per-day
scrape log, so only one does the heavy season walk each day). To seed it
immediately on a fresh deployment, run once:
`barriertrials-daily --backfill-from 2026-04-01`.

Match key: the horse name with its country suffix stripped (`GOLDEN NARRATIVE
(IRE)` → `goldennarrative`), since RP's runner names don't carry the suffix (see
`names.horse_key`). **Every column of the matched sheet row is reported** in the
entry/result card; `RATING_COLUMNS` only selects which numeric columns also get a
headline tile and drive the season-to-date band/leaderboard tables.

It reuses the breeze-up code where that code is cohort-agnostic
(`dailybreezeup.racing.rp_racecards`, `dailybreezeup.silks`,
`dailybreezeup.stats.aggregate_by_band`). The results scraper is copied to
`barriertrials/racing/rp_results.py` and extended with a name-matching path, so
nothing under `src/dailybreezeup/` is modified.

## Run

```bash
barriertrials-daily --mode morning --dry-run --demo   # synthetic layout check
barriertrials-daily --mode evening --dry-run          # live fetch, no send
barriertrials-daily --mode evening                    # live, send
barriertrials-daily --backfill-from 2026-04-01        # seed season archive
```

## Configuration (env vars)

| Var | Required | Default | Purpose |
|-----|----------|---------|---------|
| `SHEET_CSV_URL` | yes (live) | — | Watchlist sheet, `/export?format=csv` URL |
| `HORSE_NAME_COLUMN` | no | `Horse` | Header of the horse-name column (falls back to `Horse`/`Horse Name`/`Name`) |
| `RATING_COLUMNS` | yes | `Rating` | **Comma-separated** rating column headers, e.g. `Speed,Precocity`. Each gets a tile + a season-to-date band/leaderboard. |
| `GMAIL_USER`, `GMAIL_APP_PASSWORD` | yes (send) | — | SMTP auth (shareable with the breeze-up job) |
| `EMAIL_FROM` | no | `GMAIL_USER` | From address |
| `EMAIL_TO` | yes (send) | — | Comma-separated recipients (no baked-in list) |
| `ENTRIES_WINDOW_DAYS` | no | `3` | Forward racecard scan horizon |
| `SEASON_START_DATE` | no | `2026-04-01` | First date the season summary/backfill covers |
| `NOTIFY_ON_EMPTY` | no | `false` | Send the morning email even when empty (evening always sends) |
| `DB_PATH` | no | `data/barriertrials.sqlite` | SQLite path (kept separate from breeze-up) |

In GitHub Actions these map to `BT_*` repository variables (see
`.github/workflows/barriertrials.yml`) so the two jobs don't share config.

> **Rating bands:** the per-rating season tables bucket on the breeze-up
> thresholds (`<50 … ≥100`, from `dailybreezeup.stats`). If your ratings use a
> different scale, adjust `band_for`/`BANDS` usage when you confirm the headers.
