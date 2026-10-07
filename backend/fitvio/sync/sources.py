"""One entry point for "sync this person", whatever their data source is."""
from __future__ import annotations

import sqlite3

from ..config import UserConfig


def sync_user(conn: sqlite3.Connection, user: UserConfig, full: bool = False) -> tuple[bool, dict | None]:
    """Download + ingest + verdicts. Raises SyncBusy when another sync for this person holds the lock."""
    if user.source == "intervals":
        from .intervals_runner import sync_user as run
    else:
        from .garmindb_runner import sync_user as run
    return run(conn, user, full=full)
