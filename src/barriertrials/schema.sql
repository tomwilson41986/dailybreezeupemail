PRAGMA journal_mode = WAL;

-- Dedup: each (run_date, category, horse_key, race_uid) we've already emailed
-- gets a row here so re-runs within the day don't duplicate the notification.
CREATE TABLE IF NOT EXISTS email_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      TEXT NOT NULL,
    category      TEXT NOT NULL,     -- 'entered' | 'ran_today'
    horse_key     TEXT NOT NULL,     -- normalised horse name (watchlist key)
    race_uid      TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    sent_at       TEXT NOT NULL,
    UNIQUE (run_date, category, horse_key, race_uid)
);

CREATE TABLE IF NOT EXISTS run_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date     TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT,
    summary_json TEXT
);

-- The watchlist itself, upserted from the sheet on every run. learned_uid is
-- filled in the first time the horse is seen on a racecard/result (its Racing
-- Post profile uid) and preserved across runs so subsequent matching can use
-- the authoritative uid instead of the name.
CREATE TABLE IF NOT EXISTS tracked_horses (
    name_key      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    ratings_json  TEXT,
    learned_uid   INTEGER,
    first_seen    TEXT NOT NULL,
    updated_at    TEXT
);

-- One row per (horse, race) outing. Feeds the season-to-date summary block at
-- the bottom of the evening results email: form by each rating band plus the
-- top-N leaderboards.
--
-- Backfilled on first run from email_log.payload_json so the table is populated
-- immediately, then upserted from each evening run — the (horse_key, race_uid)
-- primary key makes re-runs idempotent. rpr is nullable (non-finishers, and RP
-- posts 2yo maiden ratings late); aggregations skip nulls when averaging.
-- ratings_json carries the horse's watchlist ratings as a {header: value} blob
-- so the schema doesn't need a column per (user-defined) rating.
CREATE TABLE IF NOT EXISTS results_archive (
    horse_key           TEXT NOT NULL,
    race_uid            TEXT NOT NULL,
    horse_uid           INTEGER,
    horse_name          TEXT,
    race_date           TEXT NOT NULL,
    course              TEXT,
    off_time            TEXT,
    race_name           TEXT,
    finishing_position  TEXT,
    total_runners       INTEGER,
    sp                  TEXT,
    rpr                 INTEGER,
    ratings_json        TEXT,
    season_year         INTEGER NOT NULL,
    recorded_at         TEXT NOT NULL,
    PRIMARY KEY (horse_key, race_uid)
);
CREATE INDEX IF NOT EXISTS idx_bt_results_archive_year ON results_archive(season_year);

-- One row per RP results date already walked for the season-to-date archive. A
-- row means "this date has been scraped" regardless of whether any tracked horse
-- ran, so the evening run backfills each historical day exactly once instead of
-- re-scraping the whole season nightly. After a CI cache eviction the table
-- comes back empty and the season self-heals.
CREATE TABLE IF NOT EXISTS results_scrape_log (
    result_date  TEXT PRIMARY KEY,
    scraped_at   TEXT NOT NULL
);
