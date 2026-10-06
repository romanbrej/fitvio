"""Everything about a person comes from Garmin — nothing has to be configured by hand.

Sources, in order of preference per value:
  name     Garmin profile (social-profile.json, saved by GarminDB at login)
  sex      Garmin user settings (user-settings.json) → watch user profile in the FIT files
  max_hr   the max HR your watch uses for its zones (FIT zones_target) → watch user profile
           → highest HR actually seen in your activities (if that is higher, it wins: the setting is stale)
  rest_hr  median of Garmin's daily resting HR over the last 30 days → watch user profile
  lthr     lactate threshold HR from the watch (FIT zones_target) / user settings
  ftp      FTP from the watch (FIT zones_target) — otherwise estimated from your power data per ride

A value set explicitly in config/users.json still wins (as an override), and there are safe
defaults for a brand-new account with no data yet.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

from .config import UserConfig

log = logging.getLogger(__name__)

FIELDS = ("name", "sex", "max_hr", "rest_hr", "lthr", "ftp", "weight_kg")
DEFAULTS = {"max_hr": 190.0, "rest_hr": 55.0, "sex": "male"}
# Changing these changes zones, session types and training load → reprocess history.
THRESHOLD_TOLERANCE = {"max_hr": 2.0, "rest_hr": 3.0, "ftp": 5.0}


def stored(conn: sqlite3.Connection, user_id: str) -> dict[str, dict]:
    """The stored profile (table `profiles`, created with the app database in db.py)."""
    return {r["field"]: {"value": json.loads(r["value"]), "source": r["source"], "updated_at": r["updated_at"]}
            for r in conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,))}


def resolve(conn: sqlite3.Connection, user: UserConfig) -> UserConfig:
    """The user with every physiological value filled in: override > Garmin > default."""
    p = stored(conn, user.id)
    vals = {}
    for f in FIELDS:
        if getattr(user, f) is not None:
            continue
        if f in p and p[f]["value"] is not None:
            vals[f] = p[f]["value"]
        elif f in DEFAULTS:
            vals[f] = DEFAULTS[f]
    return replace(user, **vals)


def describe(conn: sqlite3.Connection, user: UserConfig) -> dict[str, dict]:
    """Value + where it came from, for the CLI and the UI."""
    p = stored(conn, user.id)
    out = {}
    for f in FIELDS:
        if getattr(user, f) is not None:
            out[f] = {"value": getattr(user, f), "source": "set in config/users.json"}
        elif f in p and p[f]["value"] is not None:
            out[f] = {"value": p[f]["value"], "source": p[f]["source"]}
        elif f in DEFAULTS:
            out[f] = {"value": DEFAULTS[f], "source": "default (no Garmin data yet)"}
        else:
            out[f] = {"value": None, "source": "not available"}
    return out


# --- deriving from Garmin data -------------------------------------------------

def _find(obj, keys: tuple[str, ...]):
    """First non-empty value for any of `keys`, searching nested dicts/lists (Garmin JSON shapes vary)."""
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if v not in (None, "", 0):
                return v
        for v in obj.values():
            hit = _find(v, keys)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find(v, keys)
            if hit is not None:
                return hit
    return None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _sex(v) -> str | None:
    s = str(v or "").lower()
    return "female" if s.startswith("f") else "male" if s.startswith("m") else None


def derive(base_dir: Path, fit_limit: int = 20) -> dict[str, tuple[object, str]]:
    """Read one person's GarminDB data dir and return {field: (value, source)}."""
    from .ingest.fit_parser import parse_fit_profile

    found: dict[str, tuple[object, str]] = {}

    def put(field, value, source):
        if value not in (None, "", 0) and field not in found:
            found[field] = (value, source)

    fit_root = base_dir / "FitFiles"
    social = _load_json(fit_root / "social-profile.json")
    settings = _load_json(fit_root / "user-settings.json")
    personal = _load_json(fit_root / "personal-information.json")

    put("name", _find(social, ("fullName", "displayName")) or _find(personal, ("fullName",)), "Garmin profile")
    put("sex", _sex(_find(settings, ("gender",)) or _find(personal, ("gender",))), "Garmin user settings")
    w = _find(settings, ("weight",)) or _find(personal, ("weight",))
    put("weight_kg", round(float(w) / 1000, 1) if isinstance(w, (int, float)) and w > 1000 else None,
        "Garmin user settings")  # stored in grams
    lt = _find(settings, ("lactateThresholdHeartRate",))
    put("lthr", float(lt) if isinstance(lt, (int, float)) else None, "Garmin user settings")

    # Watch settings travel inside every activity file; newest first.
    # Garmin activity ids grow over time; file times don't help (a first download writes all at once).
    def newest_first(p: Path):
        aid = p.name.split("_")[0].split(".")[0]
        return (int(aid) if aid.isdigit() else -1, p.stat().st_mtime)
    fits = sorted((fit_root / "Activities").glob("*.fit"), key=newest_first, reverse=True) \
        if (fit_root / "Activities").exists() else []
    for i, path in enumerate(fits):
        # rides can be rare, so keep looking (cheap: only the file header is read) until the FTP is found
        if i >= fit_limit and ("ftp" in found or i >= fit_limit * 10):
            break
        try:
            prof = parse_fit_profile(path)
        except Exception as e:  # a corrupt file must not break profile detection
            log.debug("profile parse failed for %s: %s", path, e)
            continue
        z, u = prof.get("zones_target", {}), prof.get("user_profile", {})
        if i < fit_limit:
            put("max_hr", z.get("max_heart_rate"), "HR zones on your watch")
            put("lthr", z.get("threshold_heart_rate"), "lactate threshold on your watch")
        # FTP only from rides: in a run the same field holds the running power threshold
        if str(prof.get("sport", {}).get("sport", "")).lower() == "cycling":
            put("ftp", z.get("functional_threshold_power"), "FTP on your watch (latest ride)")
        put("sex", _sex(u.get("gender")), "user profile on your watch")
        put("max_hr", u.get("default_max_heart_rate"), "user profile on your watch")
        put("rest_hr_watch", u.get("resting_heart_rate"), "user profile on your watch")
        if all(k in found for k in ("max_hr", "lthr", "ftp", "sex")):
            break

    db_dir = base_dir / "DBs"
    since = (datetime.now() - timedelta(days=30)).date().isoformat()
    if (db_dir / "garmin.db").exists():
        with sqlite3.connect(f"file:{db_dir / 'garmin.db'}?mode=ro", uri=True) as c:
            try:
                rows = [r[0] for r in c.execute(
                    "SELECT resting_heart_rate FROM resting_hr WHERE day >= ? AND resting_heart_rate > 0", (since,))]
            except sqlite3.OperationalError:
                rows = []
        if len(rows) >= 5:
            found["rest_hr"] = (round(median(rows)), "median daily resting HR, last 30 days")
    if "rest_hr" not in found and "rest_hr_watch" in found:
        found["rest_hr"] = (found["rest_hr_watch"][0], found["rest_hr_watch"][1])
    found.pop("rest_hr_watch", None)

    # Highest HR you actually reached (3rd-highest activity max, to ignore optical spikes).
    if (db_dir / "garmin_activities.db").exists():
        year = (datetime.now() - timedelta(days=365)).isoformat(sep=" ")
        with sqlite3.connect(f"file:{db_dir / 'garmin_activities.db'}?mode=ro", uri=True) as c:
            try:
                maxes = [r[0] for r in c.execute(
                    "SELECT max_hr FROM activities WHERE max_hr BETWEEN 120 AND 230 AND start_time >= ? "
                    "ORDER BY max_hr DESC LIMIT 3", (year,))]
            except sqlite3.OperationalError:
                maxes = []
        if len(maxes) == 3:
            observed = maxes[2]
            if "max_hr" not in found:
                found["max_hr"] = (observed, "highest HR in your activities (last 12 months)")
            elif observed > float(found["max_hr"][0]) + 2:
                found["max_hr"] = (observed, f"highest HR in your activities — above the watch setting "
                                             f"({found['max_hr'][0]:.0f}), which looks outdated")
    return found


def refresh(conn: sqlite3.Connection, user: UserConfig, base_dir: Path) -> bool:
    """Re-derive the profile. Returns True when zone-relevant values changed (→ reprocess history)."""
    before = resolve(conn, user)
    had_profile = bool(stored(conn, user.id))
    now = datetime.now().isoformat(timespec="seconds")
    for field, (value, source) in derive(base_dir).items():
        if isinstance(value, (int, float)):
            value = float(value)
        conn.execute("INSERT OR REPLACE INTO profiles (user_id, field, value, source, updated_at) VALUES (?,?,?,?,?)",
                     (user.id, field, json.dumps(value), source, now))
    conn.commit()
    after = resolve(conn, user)
    if not had_profile:
        return True
    if before.sex != after.sex:
        return True
    return any(abs((getattr(after, f) or 0) - (getattr(before, f) or 0)) >= tol
               for f, tol in THRESHOLD_TOLERANCE.items())
