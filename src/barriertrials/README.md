# Barrier-trial tracker

A parallel pipeline to the breeze-up job (`dailybreezeup`), tracking a watchlist
of barrier-trial horses on Racing Post. Same shape — a morning entries email and
an evening results + season-to-date email — but the cohort comes from a Google
Sheet of **horse names + ratings** rather than a sale catalogue, and matching is
**name-first**: a horse's Racing Post `horse_uid` is learned the first time it
shows up on a racecard/result and reused thereafter.

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
