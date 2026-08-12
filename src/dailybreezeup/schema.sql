PRAGMA journal_mode = WAL;

-- Dedup: each (run_date, category, race_uid, lot_id) we've already emailed
-- gets a row here so re-runs within the day don't duplicate the notification.
CREATE TABLE IF NOT EXISTS email_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      TEXT NOT NULL,
    category      TEXT NOT NULL,     -- 'entered' | 'ran_today'
    lot_id        TEXT NOT NULL,     -- Sale.sale_id + lot_no + lot_letter
    race_uid      TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    sent_at       TEXT NOT NULL,
    UNIQUE (run_date, category, lot_id, race_uid)
);

CREATE TABLE IF NOT EXISTS run_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date     TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT,
    summary_json TEXT
);

-- One row per (lot, race) outing. Feeds the season-to-date summary block
-- at the bottom of the evening results email: form by breeze band, by
-- precocity band, by sale, plus the top-10 leaderboards.
--
-- Backfilled on first run from email_log.payload_json so the table is
-- populated immediately. Upserted from each evening run thereafter — the
-- (lot_id, race_uid) primary key makes re-runs idempotent.
--
-- rpr is nullable: backfilled rows predate RPR scraping, and some runners
-- (non-finishers) have no RPR even in fresh scrapes. Aggregations skip
-- nulls when averaging. trainer/jockey are nullable for the same reason —
-- rows archived before connections were scraped carry neither, and the
-- weekly email simply omits the line for them.
CREATE TABLE IF NOT EXISTS results_archive (
    lot_id                  TEXT NOT NULL,
    race_uid                TEXT NOT NULL,
    horse_uid               INTEGER,
    horse_name              TEXT,
    sale_year               INTEGER NOT NULL,
    sale_short              TEXT,
    sale_name               TEXT,
    lot_no                  INTEGER,
    race_date               TEXT NOT NULL,
    course                  TEXT,
    off_time                TEXT,
    race_name               TEXT,
    finishing_position      TEXT,
    total_runners           INTEGER,
    sp                      TEXT,
    rpr                     INTEGER,
    trainer                 TEXT,
    jockey                  TEXT,
    sheet_breeze_rating     REAL,
    sheet_precocity_rating  REAL,
    recorded_at             TEXT NOT NULL,
    PRIMARY KEY (lot_id, race_uid)
);
CREATE INDEX IF NOT EXISTS idx_results_archive_year ON results_archive(sale_year);

-- One row per RP results date we've already walked for the season-to-date
-- archive. A row means "this date has been scraped" regardless of whether any
-- breeze-up graduate ran that day, so the evening run backfills each historical
-- day exactly once instead of re-scraping the whole season every night. After a
-- CI cache eviction the table comes back empty and the season self-heals.
CREATE TABLE IF NOT EXISTS results_scrape_log (
    result_date  TEXT PRIMARY KEY,
    scraped_at   TEXT NOT NULL
);
