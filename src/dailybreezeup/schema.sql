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
