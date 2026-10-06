"""The app's own SQLite database.

GarminDB's databases are only ever read. Everything we derive lives here, so a
GarminDB `--rebuild_db` or schema change can never corrupt our analytics.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,          -- "<user_id>:<activity_id>"
    user_id         TEXT NOT NULL,
    activity_id     TEXT NOT NULL,
    name            TEXT,
    sport           TEXT NOT NULL,             -- running | cycling | swimming | strength | other
    raw_sport       TEXT,
    sub_sport       TEXT,
    session_type    TEXT,                      -- easy | long | tempo | intervals | race | strength | other
    start_time      TEXT NOT NULL,             -- ISO local time
    duration_s      REAL,
    distance_m      REAL,
    avg_hr          REAL,
    max_hr          REAL,
    ascent_m        REAL,
    avg_temp_c      REAL,
    indoor          INTEGER DEFAULT 0,
    has_power       INTEGER DEFAULT 0,
    load            REAL,                      -- TRIMP
    rpe             REAL,                      -- 1..10, from Garmin self-evaluation
    feel            REAL,                      -- 0..100, from Garmin self-evaluation
    features        TEXT                       -- JSON dict of sport-specific metrics
);
CREATE INDEX IF NOT EXISTS ix_sessions_user_time ON sessions(user_id, start_time);

CREATE TABLE IF NOT EXISTS session_streams (
    session_id  TEXT PRIMARY KEY,
    data        TEXT NOT NULL                  -- JSON: downsampled per-5s series + laps
);

CREATE TABLE IF NOT EXISTS exercise_sets (
    session_id  TEXT NOT NULL,
    set_index   INTEGER NOT NULL,
    exercise    TEXT NOT NULL,
    reps        INTEGER,
    weight_kg   REAL,
    PRIMARY KEY (session_id, set_index)
);

CREATE TABLE IF NOT EXISTS verdicts (
    session_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    verdict         TEXT NOT NULL,             -- better | in_line | worse | not_comparable | load_only
    confidence      TEXT NOT NULL,             -- high | medium | low
    score           REAL,
    headline        TEXT,
    reasons         TEXT,                      -- JSON list
    deltas          TEXT,                      -- JSON list of metric comparisons
    context         TEXT,                      -- JSON list of context notes (heat, hills, sleep...)
    trend           TEXT,                      -- JSON: fitness/fatigue/form before/after + efficiency trend
    baseline_ids    TEXT,                      -- JSON list of session ids used as baseline
    first_shown_at  TEXT                       -- set when the wall first displays it; never re-triggers
);

CREATE TABLE IF NOT EXISTS health_days (
    user_id             TEXT NOT NULL,
    day                 TEXT NOT NULL,          -- YYYY-MM-DD
    rhr                 REAL,
    hrv_last_night      REAL,
    hrv_weekly          REAL,
    hrv_baseline_low    REAL,
    hrv_baseline_high   REAL,
    hrv_status          TEXT,
    sleep_total_min     REAL,
    sleep_deep_min      REAL,
    sleep_light_min     REAL,
    sleep_rem_min       REAL,
    sleep_awake_min     REAL,
    sleep_score         REAL,
    stress_avg          REAL,
    bb_max              REAL,
    bb_min              REAL,
    steps               REAL,
    weight_kg           REAL,
    vo2max              REAL,
    vo2max_cycling      REAL,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS sync_status (
    user_id         TEXT PRIMARY KEY,
    last_attempt    TEXT,
    last_success    TEXT,
    last_error      TEXT
);

CREATE TABLE IF NOT EXISTS wall_state (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

-- planned workouts of the next days from the Garmin Connect calendar (Garmin Coach or your own)
CREATE TABLE IF NOT EXISTS planned_workouts (
    user_id     TEXT NOT NULL,
    day         TEXT NOT NULL,
    key         TEXT NOT NULL,      -- Garmin's workout uuid / id
    title       TEXT,
    sport       TEXT,
    data        TEXT,               -- JSON: steps, targets, plan, estimates
    fetched_at  TEXT,
    PRIMARY KEY (user_id, day, key)
);

-- Garmin's Training Readiness (the score the watch shows)
CREATE TABLE IF NOT EXISTS readiness_days (
    user_id     TEXT NOT NULL,
    day         TEXT NOT NULL,
    score       INTEGER,
    level       TEXT,
    data        TEXT,               -- JSON: feedback, factors, time
    fetched_at  TEXT,
    PRIMARY KEY (user_id, day)
);

-- name, sex, max/resting HR, FTP … as detected from Garmin (profile.py)
CREATE TABLE IF NOT EXISTS profiles (
    user_id     TEXT NOT NULL,
    field       TEXT NOT NULL,
    value       TEXT,           -- JSON
    source      TEXT,
    updated_at  TEXT,
    PRIMARY KEY (user_id, field)
);
"""
# Bump when SCHEMA or _migrate change: databases below this version get both applied on the next connect.
SCHEMA_VERSION = 1

JSON_COLUMNS = {"features", "reasons", "deltas", "context", "trend", "baseline_ids", "data"}


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)  # health data: dashboard user only
        path.touch(mode=0o600, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # API reads while the sync writes
    # every API request opens a connection: create/migrate the schema only when the file is behind
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was created."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(health_days)")}
    if "vo2max_cycling" not in cols:
        conn.execute("ALTER TABLE health_days ADD COLUMN vo2max_cycling REAL")
    conn.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for k in JSON_COLUMNS & out.keys():
        if isinstance(out[k], str):
            out[k] = json.loads(out[k])
    return out


def upsert(conn: sqlite3.Connection, table: str, row: dict) -> None:
    row = {k: (json.dumps(v) if k in JSON_COLUMNS and not isinstance(v, str) and v is not None else v)
           for k, v in row.items()}
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})", list(row.values()))


def get_state(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM wall_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO wall_state (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
