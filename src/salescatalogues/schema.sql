-- Persisted state for the Daily Sales Catalogues digest.

-- One row per catalogue we've ever observed. ``first_seen`` is what drives the
-- "New" flag: a catalogue is New on the first run it appears in. ``last_seen``
-- lets us tell whether a catalogue is still live in the source.
CREATE TABLE IF NOT EXISTS seen_catalogue (
    catalogue_id   TEXT PRIMARY KEY,
    house          TEXT NOT NULL,
    country        TEXT NOT NULL,
    name           TEXT NOT NULL,
    start_date     TEXT,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL
);

-- One row per job run, for diagnostics.
CREATE TABLE IF NOT EXISTS run_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date     TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,
    summary_json TEXT
);
