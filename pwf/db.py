"""SQLite schema and connection helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;

-- Raw HTML cache. The crawl happens once; every later stage re-reads from here
-- so that changing a parser or a rule never costs another HTTP request.
CREATE TABLE IF NOT EXISTS raw_pages (
    url          TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,          -- report | index | lake
    ref          TEXT,                   -- report id, index offset, or lake slug
    http_status  INTEGER,
    is_missing   INTEGER NOT NULL DEFAULT 0,
    fetched_at   TEXT NOT NULL,
    body         BLOB                    -- gzipped utf-8 html
);
CREATE INDEX IF NOT EXISTS ix_raw_kind ON raw_pages(kind, is_missing);

-- One row per report card seen on a listing page. This is where lake
-- attribution comes from: listing cards carry "Property : <Lake>, <Town>"
-- back to ~mid-2012, while detail pages only carry it from ~2019.
CREATE TABLE IF NOT EXISTS report_index (
    report_id    INTEGER PRIMARY KEY,
    title        TEXT,
    lake_name    TEXT,
    lake_town    TEXT,
    author       TEXT,
    posted_date  TEXT,                   -- ISO yyyy-mm-dd
    replies      INTEGER,
    views        INTEGER
);
CREATE INDEX IF NOT EXISTS ix_idx_lake ON report_index(lake_name);

-- One row per report detail page.
CREATE TABLE IF NOT EXISTS reports (
    report_id          INTEGER PRIMARY KEY,
    title              TEXT,
    posted_date        TEXT,
    author             TEXT,
    author_rank        TEXT,
    member_since       INTEGER,
    post_count         INTEGER,
    reservation_number TEXT,
    property_name      TEXT,             -- detail-page field, 2019+ only
    trip_date          TEXT,             -- ISO, from "Reservation Date"
    time_slot          TEXT,             -- AM | PM | ALL_DAY
    total_fish_raw     TEXT,
    lures_raw          TEXT,
    body               TEXT,
    photo_count        INTEGER NOT NULL DEFAULT 0,
    era                TEXT,             -- structured | legacy
    parsed_at          TEXT
);

CREATE TABLE IF NOT EXISTS lakes (
    lake_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    town            TEXT,
    slug            TEXT,
    region          TEXT,
    acres           REAL,
    max_depth_ft    REAL,
    membership_tier TEXT,
    bank_fishing    INTEGER,
    boat_type       TEXT,
    day_rate        REAL,
    half_day_rate   REAL,
    harvest_rules   TEXT,
    description     TEXT,
    lat             REAL,
    lon             REAL,
    cohort          TEXT
);

-- The analysis unit: a report resolved to a lake, a date and an effort window.
CREATE TABLE IF NOT EXISTS trips (
    report_id      INTEGER PRIMARY KEY,
    lake_id        INTEGER REFERENCES lakes(lake_id),
    lake_known     INTEGER NOT NULL DEFAULT 0,
    trip_date      TEXT,
    year           INTEGER,
    month          INTEGER,
    season         TEXT,
    time_slot      TEXT,
    trip_date_source TEXT,           -- reservation | posted
    hours          REAL,
    fish_total     INTEGER,
    fish_per_hour  REAL,
    max_weight_lb  REAL
);
CREATE INDEX IF NOT EXISTS ix_trips_lake ON trips(lake_id, trip_date);
CREATE INDEX IF NOT EXISTS ix_trips_month ON trips(month);

CREATE TABLE IF NOT EXISTS catches (
    report_id     INTEGER,
    species       TEXT,
    n             INTEGER,
    max_weight_lb REAL,
    size_note     TEXT
);
CREATE INDEX IF NOT EXISTS ix_catches_report ON catches(report_id);

CREATE TABLE IF NOT EXISTS report_lures (
    report_id INTEGER,
    raw       TEXT,
    category  TEXT,
    subtype   TEXT,
    color     TEXT,
    source    TEXT          -- field | narrative
);
CREATE INDEX IF NOT EXISTS ix_lures_report ON report_lures(report_id);
CREATE INDEX IF NOT EXISTS ix_lures_cat ON report_lures(category);

CREATE TABLE IF NOT EXISTS report_features (
    report_id     INTEGER PRIMARY KEY,
    clarity_ft    REAL,
    clarity_label TEXT,
    water_temp_f  REAL,
    depth_min_ft  REAL,
    depth_max_ft  REAL,
    bite_window   TEXT,
    skunked       INTEGER
);

CREATE TABLE IF NOT EXISTS report_tags (
    report_id INTEGER,
    kind      TEXT,          -- vegetation | structure | technique
    value     TEXT,
    detail    TEXT           -- e.g. vegetation density
);
CREATE INDEX IF NOT EXISTS ix_tags ON report_tags(kind, value);
CREATE INDEX IF NOT EXISTS ix_tags_report ON report_tags(report_id);

-- Weather/astro for every lake-date, from Open-Meteo. 100% coverage of
-- attributed trips, which is what makes the sparse narrative fields tolerable.
CREATE TABLE IF NOT EXISTS conditions (
    lake_id            INTEGER,
    date               TEXT,
    temp_max_f         REAL,
    temp_min_f         REAL,
    temp_mean_f        REAL,
    temp_7d_mean_f     REAL,          -- water-temperature proxy
    precip_in          REAL,
    wind_max_mph       REAL,
    wind_dir_deg       REAL,
    cloud_pct          REAL,
    pressure_hpa       REAL,          -- early-morning surface pressure
    pressure_delta_24h REAL,
    pressure_delta_48h REAL,
    pressure_trend     TEXT,          -- rising | steady | falling
    moon_phase         REAL,          -- 0..1
    moon_illum         REAL,
    sunrise            TEXT,
    sunset             TEXT,
    day_length_h       REAL,
    PRIMARY KEY (lake_id, date)
);

-- Every rule-based extractor records what fraction of reports it fired on, so
-- the CLI can always state the sample behind a number.
CREATE TABLE IF NOT EXISTS coverage_stats (
    dimension   TEXT PRIMARY KEY,
    n_with      INTEGER,
    n_total     INTEGER,
    pct         REAL,
    tier        TEXT,          -- full | partial
    computed_at TEXT
);

-- Lure strings the taxonomy did not recognise. This queue is how the taxonomy
-- improves; nothing is ever silently dropped.
CREATE TABLE IF NOT EXISTS lure_review (
    raw TEXT PRIMARY KEY,
    n   INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created."""
    wanted = {
        "trips": [("trip_date_source", "TEXT")],
        "lakes": [("report_count", "INTEGER")],
    }
    for table, cols in wanted.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init(path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn
