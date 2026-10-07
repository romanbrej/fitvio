"""Sync for people whose data comes from Intervals.icu: download (intervals_reader.download) + ingest.

Same contract as garmindb_runner: one sync per person at a time (sync_lock), the outcome goes to
`sync_status`, and `sync_user` returns (download ok, ingest result or None)."""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from typing import Callable

from .. import db
from ..config import UserConfig
from ..ingest import intervals_reader as icu
from .garmindb_runner import changed_since, sync_lock, timed_ingest

log = logging.getLogger(__name__)

CHECK_INTERVAL_S = 600  # the auto-sync asks Intervals.icu for new activities every 10 min (daytime)


def client_for(user: UserConfig) -> icu.Client:
    return icu.Client(*icu.load_credentials(user.intervals_path))


def run_sync(conn: sqlite3.Connection, user: UserConfig, full: bool = False,
             on_line: Callable[[str], None] | None = None, client: icu.Client | None = None) -> bool:
    now = datetime.now().isoformat(timespec="seconds")
    started = time.monotonic()
    row = db.row_to_dict(conn.execute("SELECT * FROM sync_status WHERE user_id = ?", (user.id,)).fetchone()) or {}
    last_ok = changed_since(conn, user.id)  # before this sync moves it
    error = None
    with sync_lock(user):
        try:
            stats = icu.download(user.intervals_path, client or client_for(user), full=full,
                                 since=last_ok.date() if last_ok else None, on_line=on_line or (lambda s: None))
            log.info("sync %s (intervals.icu)%s: %.0fs — %s", user.id, " full" if full else "",
                     time.monotonic() - started, stats)
            if stats["strava_only"]:
                log.info("sync %s: %d activities came from Strava — Intervals.icu can't pass those on",
                         user.id, stats["strava_only"])
        except icu.IntervalsError as e:
            error = str(e)
        except (OSError, ValueError, KeyError) as e:  # missing/garbled credentials file
            error = f"Intervals.icu connection is not set up correctly: {e}"
    db.upsert(conn, "sync_status", {
        "user_id": user.id, "last_attempt": now,
        "last_success": now if error is None else row.get("last_success"),
        "last_error": error,
    })
    conn.commit()
    if error:
        log.error("sync %s failed: %s", user.id, error)
    return error is None


def sync_user(conn: sqlite3.Connection, user: UserConfig, full: bool = False) -> tuple[bool, dict | None]:
    since = None if full else changed_since(conn, user.id)  # before the sync moves it
    ok = run_sync(conn, user, full=full)
    try:
        return ok, timed_ingest(conn, user, full=full, changed_since=since)
    except RuntimeError as e:  # nothing downloaded yet
        log.warning("%s: ingest skipped — %s", user.id, e)
        return ok, None


def due(conn: sqlite3.Connection, user: UserConfig, now: datetime) -> bool:
    """Time for the daytime check? (A sync is a few small requests, so it is the check itself.)"""
    row = conn.execute("SELECT last_attempt FROM sync_status WHERE user_id = ?", (user.id,)).fetchone()
    return not row or not row[0] or (now - datetime.fromisoformat(row[0])).total_seconds() >= CHECK_INTERVAL_S
