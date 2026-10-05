"""Auto-sync on a new Garmin activity — a webhook-like check, because Garmin offers no push for private use.

Every 2 minutes (05:00–24:00) ask Garmin for the newest activity id only (one tiny request per person).
If it is new, run the normal differential sync for that person. A full sync (health data) runs hourly.

Safety rules (protect the Garmin account on the unofficial API):
- Only the cached login tokens are used — never the password, never MFA. If the tokens stop working
  the check pauses for that person until a regular sync succeeds again, and the wall says so.
- HTTP 429 (rate limit) pauses the check for everyone for 6 hours.
- An activity that doesn't show up after a sync is retried at most 3 times, then left alone.
- It can be switched off in the UI (Accounts → "Auto-sync on new activity").
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta

from .. import db
from ..config import AppConfig, UserConfig
from .garmindb_runner import SyncBusy, sync_lock, sync_user

log = logging.getLogger(__name__)

ACTIVITY_LIST_URL = "/activitylist-service/activities/search/activities"
CHECK_INTERVAL_S = 120
FULL_SYNC_INTERVAL_S = 3600
ACTIVE_FROM_HOUR = 5          # checks run 05:00–24:00; at night only the hourly sync
RATE_LIMIT_PAUSE = timedelta(hours=6)
MAX_ATTEMPTS = 3

K_ENABLED = "watch.enabled"
K_BACKOFF = "watch.backoff_until"
K_ERROR = "watch.last_error"


def _k(uid: str, name: str) -> str:
    return f"watch.{uid}.{name}"


class AuthExpired(Exception):
    """The cached Garmin login no longer works (a password login would be needed)."""


class RateLimited(Exception):
    """Garmin answered 429 Too Many Requests."""


class CheckFailed(Exception):
    """Network or server error — try again next time."""


def cached_client(user: UserConfig):
    """A Garmin Connect client that only uses the cached login tokens — never the password or MFA."""
    from garminconnect import Garmin
    from garmindb.garmin_connect_config_manager import GarminConnectConfigManager

    token_file = user.garmindb_dir / "garmin_tokens.json"
    if not token_file.is_file():
        raise AuthExpired("no cached Garmin login")
    is_cn = GarminConnectConfigManager(str(user.garmindb_dir)).get_garmin_base_domain() == "garmin.cn"
    garmin = Garmin(is_cn=is_cn, retry_attempts=0)  # no email/password: can never fall back to a login
    try:
        garmin.client.load(str(token_file))  # refreshed tokens are written back to the same file (0600)
    except Exception as e:
        raise AuthExpired(f"cached Garmin login unreadable: {type(e).__name__}") from None
    return garmin


def newest_activity_id(user: UserConfig) -> str | None:
    """Newest activity id on Garmin Connect, using the cached tokens only (one request)."""
    from garminconnect import (GarminConnectAuthenticationError, GarminConnectConnectionError,
                               GarminConnectTooManyRequestsError)

    garmin = cached_client(user)
    try:
        rows = garmin.connectapi(ACTIVITY_LIST_URL, params={"start": "0", "limit": "1"})
    except GarminConnectAuthenticationError:
        raise AuthExpired("Garmin rejected the cached login") from None
    except GarminConnectTooManyRequestsError:
        raise RateLimited("Garmin rate limit (429)") from None
    except GarminConnectConnectionError as e:
        raise CheckFailed(str(e)[:200]) from None
    if not rows:
        return None
    aid = str(rows[0].get("activityId", ""))
    return aid if aid.isdigit() else None


def is_enabled(conn: sqlite3.Connection) -> bool:
    return db.get_state(conn, K_ENABLED, "1") == "1"


def set_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
    db.set_state(conn, K_ENABLED, "1" if enabled else "0")


def in_active_hours(now: datetime) -> bool:
    return now.hour >= ACTIVE_FROM_HOUR


def _known(conn: sqlite3.Connection, uid: str, aid: str) -> bool:
    # multisport activities are stored per leg ("123_1", "123_2"); Garmin's list reports the parent "123"
    return conn.execute("SELECT 1 FROM sessions WHERE user_id = ? AND (activity_id = ? OR activity_id LIKE ? ESCAPE '\\')",
                        (uid, aid, f"{aid}\\_%")).fetchone() is not None


def _last_success(conn: sqlite3.Connection, uid: str) -> str | None:
    row = conn.execute("SELECT last_success FROM sync_status WHERE user_id = ?", (uid,)).fetchone()
    return row[0] if row else None


def paused_for_login(conn: sqlite3.Connection, uid: str) -> bool:
    """Paused because the cached login expired — until a regular sync succeeds after the pause."""
    paused = db.get_state(conn, _k(uid, "paused_at"))
    if not paused:
        return False
    ok = _last_success(conn, uid)
    if ok and ok > paused:
        db.set_state(conn, _k(uid, "paused_at"), "")
        return False
    return True


def check_user(conn: sqlite3.Connection, user: UserConfig, now: datetime, newest=newest_activity_id,
               sync=sync_user) -> str:
    """One check for one person. Returns what happened (for the log and the tests)."""
    uid = user.id
    if paused_for_login(conn, uid):
        return "paused"
    try:
        with sync_lock(user):  # never read/refresh the token file while GarminDB is using it
            aid = newest(user)
    except SyncBusy:
        return "busy"
    except AuthExpired as e:
        db.set_state(conn, _k(uid, "paused_at"), now.isoformat(timespec="seconds"))
        db.set_state(conn, K_ERROR, f"{uid}: {e}")
        log.warning("activity check %s paused: %s (re-connect in Accounts)", uid, e)
        return "auth"
    db.set_state(conn, _k(uid, "last_check"), now.isoformat(timespec="seconds"))
    if not aid or _known(conn, uid, aid) or db.get_state(conn, _k(uid, "last_seen_id")) == aid:
        return "none"
    attempts = int(db.get_state(conn, _k(uid, "attempts"), "0") or 0)
    if db.get_state(conn, _k(uid, "pending_id")) != aid:
        attempts = 0
    log.info("activity check %s: new activity %s — syncing", uid, aid)
    try:
        sync(conn, user)
    except SyncBusy:
        return "busy"
    if _known(conn, uid, aid):
        db.set_state(conn, _k(uid, "last_seen_id"), aid)
        db.set_state(conn, _k(uid, "attempts"), "0")
        return "synced"
    attempts += 1  # Garmin may still be processing the file — retry on the next checks, but not forever
    db.set_state(conn, _k(uid, "pending_id"), aid)
    db.set_state(conn, _k(uid, "attempts"), str(attempts))
    if attempts >= MAX_ATTEMPTS:
        db.set_state(conn, _k(uid, "last_seen_id"), aid)
        log.warning("activity check %s: %s still missing after %d syncs — giving up on it", uid, aid, attempts)
    return "retry"


def check_once(conn: sqlite3.Connection, cfg: AppConfig, now: datetime | None = None, **kw) -> dict[str, str]:
    """One round for everyone. Returns {user_id: outcome}."""
    now = now or datetime.now()
    if not is_enabled(conn):
        return {u.id: "disabled" for u in cfg.users}
    if not in_active_hours(now):
        return {u.id: "night" for u in cfg.users}
    backoff = db.get_state(conn, K_BACKOFF)
    if backoff and now.isoformat() < backoff:
        return {u.id: "backoff" for u in cfg.users}
    out = {}
    for user in cfg.users:
        if not user.garmindb_config_dir:
            continue
        try:
            out[user.id] = check_user(conn, user, now, **kw)
        except RateLimited as e:
            until = (now + RATE_LIMIT_PAUSE).isoformat(timespec="seconds")
            db.set_state(conn, K_BACKOFF, until)
            db.set_state(conn, K_ERROR, f"{e} — paused until {until[11:16]}")
            log.warning("activity check paused for 6 h: %s", e)
            out[user.id] = "rate_limited"
            break
        except CheckFailed as e:
            log.info("activity check %s failed (will retry): %s", user.id, e)
            out[user.id] = "failed"
        except Exception:  # never let one person's problem stop the loop
            log.exception("activity check %s crashed", user.id)
            out[user.id] = "failed"
    return out


def full_sync_all(conn: sqlite3.Connection, cfg: AppConfig, sync=sync_user) -> None:
    for user in cfg.users:
        if not user.garmindb_config_dir:
            continue
        try:
            sync(conn, user)
        except SyncBusy:
            log.info("hourly sync %s skipped: another sync is running", user.id)
        except Exception:
            log.exception("hourly sync %s failed", user.id)


def status(conn: sqlite3.Connection, cfg: AppConfig) -> dict:
    """For the Accounts screen."""
    return {
        "enabled": is_enabled(conn),
        "interval_s": CHECK_INTERVAL_S,
        "active_hours": f"{ACTIVE_FROM_HOUR:02d}:00–24:00",
        "backoff_until": db.get_state(conn, K_BACKOFF) or None,
        "last_error": db.get_state(conn, K_ERROR) or None,
        "users": {u.id: {"last_check": db.get_state(conn, _k(u.id, "last_check")),
                         "login_expired": paused_for_login(conn, u.id)} for u in cfg.users},
    }


def watch_loop(cfg: AppConfig | None, conn: sqlite3.Connection) -> None:
    """`healthdash watch`: runs forever in the sync container (restart: unless-stopped)."""
    log.info("auto-sync: activity check every %d s (%02d:00–24:00), full sync every %d min",
             CHECK_INTERVAL_S, ACTIVE_FROM_HOUR, FULL_SYNC_INTERVAL_S // 60)
    from ..config import load_config

    next_full = 0.0  # a full sync right at start, like the old loop
    while True:
        cfg = load_config()  # people connected in the UI meanwhile are included
        if time.monotonic() >= next_full:
            full_sync_all(conn, cfg)
            next_full = time.monotonic() + FULL_SYNC_INTERVAL_S
        else:
            result = check_once(conn, cfg)
            if any(v not in ("none", "night", "disabled", "backoff", "paused") for v in result.values()):
                log.info("activity check: %s", result)
        time.sleep(CHECK_INTERVAL_S)
