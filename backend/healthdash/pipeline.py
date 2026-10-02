"""Store activities, evaluate verdicts, import health days."""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from statistics import median

from . import db, profile
from .activity import ParsedActivity
from .analytics.features import build_streams, compute_features
from .config import UserConfig
from .models.sports import model_for

log = logging.getLogger(__name__)


def session_id(user_id: str, activity_id: str) -> str:
    return f"{user_id}:{activity_id}"


def store_activity(conn: sqlite3.Connection, user: UserConfig, act: ParsedActivity) -> str:
    sid = session_id(user.id, act.activity_id)
    feats = compute_features(act, profile.resolve(conn, user))
    db.upsert(conn, "sessions", {
        "id": sid, "user_id": user.id, "activity_id": act.activity_id, "name": act.name,
        "sport": act.sport, "raw_sport": act.raw_sport, "sub_sport": act.sub_sport,
        "session_type": feats["session_type"], "start_time": act.start_time.isoformat(timespec="seconds"),
        "duration_s": act.duration_s, "distance_m": act.distance_m, "avg_hr": act.avg_hr, "max_hr": act.max_hr,
        "ascent_m": act.ascent_m, "avg_temp_c": act.avg_temp_c, "indoor": int(act.indoor),
        "has_power": int(act.has_power), "load": feats["load"], "rpe": act.rpe, "feel": act.feel,
        "features": feats["features"],
    })
    db.upsert(conn, "session_streams", {"session_id": sid, "data": build_streams(act)})
    conn.execute("DELETE FROM exercise_sets WHERE session_id = ?", (sid,))
    for i, s in enumerate(act.sets):
        db.upsert(conn, "exercise_sets", {"session_id": sid, "set_index": i, "exercise": s.exercise,
                                          "reps": s.reps, "weight_kg": s.weight_kg})
    conn.commit()
    return sid


def user_sessions(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY start_time", (user_id,)).fetchall()
    return [db.row_to_dict(r) for r in rows]


def health_for(conn: sqlite3.Connection, user_id: str, day: str) -> tuple[dict | None, dict | None]:
    """Health on the given day (sleep/HRV are keyed to the morning) + a 28-day baseline."""
    h = db.row_to_dict(conn.execute("SELECT * FROM health_days WHERE user_id = ? AND day = ?",
                                    (user_id, day)).fetchone())
    d0 = (date.fromisoformat(day) - timedelta(days=28)).isoformat()
    rows = conn.execute("SELECT rhr FROM health_days WHERE user_id = ? AND day >= ? AND day < ? AND rhr IS NOT NULL",
                        (user_id, d0, day)).fetchall()
    base = {"rhr": median(r["rhr"] for r in rows)} if len(rows) >= 7 else None
    return h, base


def evaluate_session(conn: sqlite3.Connection, user_id: str, sid: str, sessions: list[dict] | None = None) -> dict:
    sessions = sessions if sessions is not None else user_sessions(conn, user_id)
    session = next(s for s in sessions if s["id"] == sid)
    history = [s for s in sessions if s["start_time"] < session["start_time"]]
    health, base = health_for(conn, user_id, session["start_time"][:10])
    result = model_for(session["sport"]).evaluate(session, history, health, base)
    prev = conn.execute("SELECT first_shown_at FROM verdicts WHERE session_id = ?", (sid,)).fetchone()
    result["first_shown_at"] = prev["first_shown_at"] if prev else None  # re-evaluation must not re-trigger the wall
    result["created_at"] = datetime.now().isoformat(timespec="seconds")
    db.upsert(conn, "verdicts", result)
    return result


def evaluate_all(conn: sqlite3.Connection, user_id: str, only_missing: bool = False) -> int:
    sessions = user_sessions(conn, user_id)
    done = {r["session_id"] for r in conn.execute("SELECT session_id FROM verdicts WHERE user_id = ?", (user_id,))}
    n = 0
    for s in sessions:
        if only_missing and s["id"] in done:
            continue
        evaluate_session(conn, user_id, s["id"], sessions)
        n += 1
    conn.commit()
    return n


def store_health(conn: sqlite3.Connection, user_id: str, days: list[dict]) -> None:
    for d in days:
        db.upsert(conn, "health_days", {"user_id": user_id, **d})
    conn.commit()


# Bump when features, session types or verdict logic change: the next sync then reprocesses every
# activity, so a deploy alone brings the whole history up to date.
# 2: run type from the workout name / LTHR, intervals judged on work reps
# 3: "Erholung" (easy) and "Anaerob" (intervals) workout names
# 4: form includes the day's own training (stored verdict trends carry form_before/form_after)
# 5: intervals only compared with the same rep length (±30 %) from the last 6 months
ANALYSIS_VERSION = "5"


def ingest_from_garmindb(conn: sqlite3.Connection, user: UserConfig, full: bool = False,
                         changed_since: datetime | None = None) -> dict:
    """Pull new activities + recent health days from this user's GarminDB into app.db.

    With `changed_since` (start of the last successful sync), activities that were edited in
    Garmin Connect since then (name, RPE/feel, …) are re-read too."""
    from .ingest.garmindb_reader import GarminDbReader, base_dir_from_config, default_since

    if not user.garmindb_dir:
        raise RuntimeError(f"user {user.id} has no garmindb_config_dir")
    reader = GarminDbReader(base_dir_from_config(user.garmindb_dir))
    if not reader.available:
        raise RuntimeError(f"no GarminDB databases in {reader.db_dir} — run the sync first")

    # Name, sex, max/resting HR, FTP: straight from Garmin. If they moved, zones and load of the
    # whole history change, so everything is reprocessed with the new values.
    thresholds_changed = profile.refresh(conn, user, reader.base)
    known = {r["activity_id"] for r in conn.execute("SELECT activity_id FROM sessions WHERE user_id = ?", (user.id,))}
    version_key = f"analysis_version:{user.id}"
    outdated = db.get_state(conn, version_key) != ANALYSIS_VERSION
    reprocess = full or ((thresholds_changed or outdated) and bool(known))
    if reprocess and known and not full:
        why = "HR or power profile changed" if thresholds_changed else "analysis updated"
        log.info("%s: %s — reprocessing %d activities", user.id, why, len(known))
    new_ids = [aid for aid, _ in reader.activity_ids(None if reprocess else default_since())
               if reprocess or aid not in known]
    edited = set()
    if changed_since and not reprocess:
        edited = (reader.changed_activity_ids(changed_since) & known) - set(new_ids)
    stored = []
    n_new = n_updated = 0
    for aid in [*new_ids, *sorted(edited)]:
        act = reader.load_activity(aid)
        if act is None:
            continue
        stored.append(store_activity(conn, user, act))
        if aid in edited:
            n_updated += 1
        else:
            n_new += 1
    health_since = default_since(400 if full or not known else 14)
    store_health(conn, user.id, reader.health_days(health_since))
    if reprocess:
        evaluate_all(conn, user.id)
    else:
        # Baselines only use earlier sessions, so only the new ones need a verdict.
        sessions = user_sessions(conn, user.id)
        for sid in stored:
            evaluate_session(conn, user.id, sid, sessions)
    db.set_state(conn, version_key, ANALYSIS_VERSION)
    conn.commit()
    return {"activities": n_new, "updated": n_updated, "reprocessed": reprocess,
            "profile": {k: v["value"] for k, v in profile.describe(conn, user).items()}}
