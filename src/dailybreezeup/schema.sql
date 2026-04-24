PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS sales (
    id          TEXT PRIMARY KEY,
    vendor      TEXT NOT NULL,
    name        TEXT NOT NULL,
    country     TEXT NOT NULL CHECK (country IN ('GB', 'IE', 'FR')),
    year        INTEGER NOT NULL,
    start_date  TEXT,
    source_url  TEXT,
    scraped_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalogue_entries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id          TEXT NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    lot              TEXT,
    horse_name       TEXT NOT NULL DEFAULT '',
    normalized_name  TEXT NOT NULL DEFAULT '',
    country_bred     TEXT,
    year_foaled      INTEGER,
    sire             TEXT,
    dam              TEXT,
    damsire          TEXT,
    sex              TEXT,
    consignor        TEXT,
    buyer            TEXT,
    price            INTEGER,
    currency         TEXT,
    withdrawn        INTEGER NOT NULL DEFAULT 0,
    source_url       TEXT,
    scraped_at       TEXT NOT NULL,
    -- User-provided analytics (from the Google Sheet ingestor)
    ot_diff_m        TEXT,
    ot_rank          TEXT,
    sl_1f            TEXT,
    sl_go            TEXT,
    breeze_rating    TEXT,
    precocity_rating TEXT,
    sheet_row_url    TEXT,
    UNIQUE (sale_id, lot)
);

CREATE INDEX IF NOT EXISTS ix_cat_norm        ON catalogue_entries(normalized_name);
CREATE INDEX IF NOT EXISTS ix_cat_norm_year   ON catalogue_entries(normalized_name, year_foaled);
CREATE INDEX IF NOT EXISTS ix_cat_sire_dam_yr ON catalogue_entries(sire, dam, year_foaled);

CREATE TABLE IF NOT EXISTS email_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      TEXT NOT NULL,
    category      TEXT NOT NULL,
    horse_key     TEXT NOT NULL,
    race_id       TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    sent_at       TEXT NOT NULL,
    UNIQUE (run_date, category, horse_key, race_id)
);

CREATE TABLE IF NOT EXISTS run_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date     TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT,
    summary_json TEXT
);
