"""Removing a person and everything Fitvio keeps about them (#34).

`config.remove_user` takes them off the wall at once; their entry waits in `removing` until `purge`
has deleted their rows and folder. A sync that is still running finishes first: `purge` needs the
person's sync lock, which every download, import and reprocess holds. Whoever releases it last calls
`purge_pending` (the job's end in the web app, each round of the `fitvio watch` loop, the app's start).
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

from . import config, db
from .config import AppConfig, UserConfig, load_config
from .sync.garmindb_runner import SyncBusy, sync_lock

log = logging.getLogger(__name__)

# rows keyed by the person
USER_TABLES = ("sessions", "verdicts", "health_days", "sync_status", "planned_workouts", "readiness_days",
               "baseline_exclusions", "profiles")
# rows keyed by session id "<user_id>:<activity_id>"
SESSION_TABLES = ("session_streams", "exercise_sets")
# per-person wall_state keys; {id} is the person's id. Keep in step with the modules that write them.
STATE_KEYS = (
    "units:{id}",                    # units.py
    "open_meteo:{id}",               # weather.py
    "wind_adjust:{id}",              # weather.py
    "heat_learn:{id}",               # heat_response.py
    "trend_period:{id}",             # wall.py
    "reprocessing:{id}",             # pipeline.py
    "analysis_version:{id}",         # pipeline.py
    "buddy.{id}.animal",             # buddy.py
    "buddy.{id}.shown",              # buddy.py
    "morning.{id}",                  # api/main.py
)
STATE_PREFIXES = (
    "heat_response:{id}:",           # heat_response.py, one per sport
    "watch.{id}.",                   # sync/activity_watch.py
)
STATE_SUFFIXES = (
    "_dismissed:{id}",               # profile.py, "<field>_dismissed:<id>"
)


def delete_rows(conn: sqlite3.Connection, user_id: str) -> None:
    """Every database row about the person, in one transaction. Prefixes are compared exactly (substr),
    not with LIKE, which ignores case and treats "_" as a wildcard: "alex" must never touch "Alex" or "alex_2"."""
    with conn:
        for t in USER_TABLES:
            conn.execute(f"DELETE FROM {t} WHERE user_id = ?", (user_id,))
        session_prefix = f"{user_id}:"
        for t in SESSION_TABLES:
            conn.execute(f"DELETE FROM {t} WHERE substr(session_id, 1, ?) = ?", (len(session_prefix), session_prefix))
        conn.executemany("DELETE FROM wall_state WHERE key = ?", [(k.format(id=user_id),) for k in STATE_KEYS])
        for p in (p.format(id=user_id) for p in STATE_PREFIXES):
            conn.execute("DELETE FROM wall_state WHERE substr(key, 1, ?) = ?", (len(p), p))
        for p in (p.format(id=user_id) for p in STATE_SUFFIXES):
            conn.execute("DELETE FROM wall_state WHERE length(key) > ? AND substr(key, -?) = ?", (len(p), len(p), p))
        conn.execute("DELETE FROM wall_state WHERE key = 'selected_user' AND value = ?", (user_id,))


def safe_data_dir(user: UserConfig) -> Path | None:
    """The person's folder, if it is one Fitvio made for them: data/garmindb/<id> or data/intervals/<id>.
    Anything else (a hand-edited path, a symlink) is never deleted."""
    d = user.data_dir
    if d is None:
        return None
    root = config.PROJECT_ROOT / "data"
    parents = {root / "garmindb", root / "intervals"}
    plain_id = user.id not in ("", ".", "..") and Path(user.id).name == user.id  # one path component, no "/"
    if (not plain_id or d.is_symlink() or d.parent not in parents or d.name != user.id
            or d.resolve().parent not in {p.resolve() for p in parents}):
        log.warning("removal %s: not deleting %s, it is not a folder Fitvio made for this person", user.id, d)
        return None
    return d


def purge(cfg: AppConfig, user: UserConfig) -> bool:
    """Delete a removed person's rows and folder. False while a sync still holds their lock."""
    folder = user.data_dir if user.data_dir and user.data_dir.is_dir() else None
    try:
        if folder:
            with sync_lock(user, removing=True):
                _delete(cfg, user)
        else:
            _delete(cfg, user)
    except SyncBusy:
        log.info("removal %s: waiting for the running sync to finish", user.id)
        return False
    config.finish_removal(user.id)
    log.info("removal %s: done", user.id)
    return True


def _delete(cfg: AppConfig, user: UserConfig) -> None:
    conn = db.connect(cfg.db_path)
    try:
        delete_rows(conn, user.id)
    finally:
        conn.close()
    folder = safe_data_dir(user)
    if folder:
        shutil.rmtree(folder)  # the lock file inside goes too; holding its lock meanwhile is fine


def purge_pending(cfg: AppConfig | None = None) -> list[str]:
    """Finish every removal that can be finished now. Returns the ids still waiting. Never raises:
    it runs at the end of jobs and in the watcher loop."""
    cfg = cfg or load_config()
    waiting = []
    for user in cfg.removing:
        try:
            if not purge(cfg, user):
                waiting.append(user.id)
        except Exception:
            log.exception("removal %s failed (will retry)", user.id)
            waiting.append(user.id)
    return waiting
