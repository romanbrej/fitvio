"""Store activities, evaluate verdicts, import health days."""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import date, datetime, timedelta
from statistics import median

from . import db, heat_response, profile, weather
from .analytics import heat
from .activity import ParsedActivity
from .analytics.features import build_streams, compute_features
from .config import UserConfig
from .models.sports import model_for
from .sync import open_meteo

log = logging.getLogger(__name__)


def session_id(user_id: str, activity_id: str) -> str:
    return f"{user_id}:{activity_id}"


def store_activity(conn: sqlite3.Connection, user: UserConfig, act: ParsedActivity) -> str:
    sid = session_id(user.id, act.activity_id)
    feats = compute_features(act, profile.resolve(conn, user))
    heat.adjust([{"sport": act.sport, "indoor": act.indoor, "features": feats["features"]}],
                heat_response.current(conn, user.id))
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
                                          "reps": s.reps, "weight_kg": s.weight_kg, "duration_s": s.duration_s})
    conn.commit()
    return sid


def user_sessions(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    """All of a person's sessions, oldest first, each with `excluded` (left out of comparisons)."""
    rows = conn.execute("SELECT * FROM sessions WHERE user_id = ? ORDER BY start_time", (user_id,)).fetchall()
    sessions = [db.row_to_dict(r) for r in rows]
    _mark_excluded(sessions, excluded_ids(conn, user_id))
    return sessions


def excluded_ids(conn: sqlite3.Connection, user_id: str) -> set[str]:
    return {r["session_id"] for r in conn.execute(
        "SELECT session_id FROM baseline_exclusions WHERE user_id = ?", (user_id,))}


def _mark_excluded(sessions: list[dict], excluded: set[str]) -> None:
    for s in sessions:
        s["excluded"] = s["id"] in excluded


def performance_sessions(sessions: list[dict]) -> list[dict]:
    """The sessions that count for performance (verdicts, trends, bests). Load and form use them all."""
    return [s for s in sessions if not s.get("excluded")]


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
    # read fresh: a sync running alongside may hold a list loaded before someone excluded a session
    _mark_excluded(sessions, excluded_ids(conn, user_id))
    session = next(s for s in sessions if s["id"] == sid)
    history = [s for s in sessions if s["start_time"] < session["start_time"]]
    model = model_for(session["sport"])
    if session["excluded"]:
        result = model.excluded(session, history)
    else:
        health, base = health_for(conn, user_id, session["start_time"][:10])
        result = model.evaluate(session, history, health, base)
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


def set_excluded(conn: sqlite3.Connection, user_id: str, sid: str, excluded: bool) -> int:
    """Leave a session out of every performance comparison, or bring it back, and recompute the verdicts
    it can reach: its own and every later one of the same sport (baselines, trends and all-time bests
    look back that far). Returns how many verdicts were recomputed."""
    try:
        if excluded:
            conn.execute("INSERT OR IGNORE INTO baseline_exclusions (session_id, user_id, excluded_at) VALUES (?, ?, ?)",
                         (sid, user_id, datetime.now().isoformat(timespec="seconds")))
        else:
            conn.execute("DELETE FROM baseline_exclusions WHERE session_id = ?", (sid,))
        n = reevaluate_from(conn, user_id, [sid])
        conn.commit()
    except Exception:
        conn.rollback()  # all or nothing: never an exclusion with half its verdicts recomputed
        raise
    return n


def reevaluate_from(conn: sqlite3.Connection, user_id: str, sids: list[str]) -> int:
    """Recompute the verdicts these sessions can reach: their own and every later one of the same sport
    (baselines, trends and all-time bests look back that far). No commit. Returns how many."""
    sessions = user_sessions(conn, user_id)
    first: dict[str, str] = {}
    for s in sessions:
        if s["id"] in sids and s["start_time"] < first.get(s["sport"], "~"):
            first[s["sport"]] = s["start_time"]
    affected = [s["id"] for s in sessions if s["sport"] in first and s["start_time"] >= first[s["sport"]]]
    for aid in affected:
        evaluate_session(conn, user_id, aid, sessions)
    return len(affected)


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
# 6: pace at the reference HR measured from steady seconds near it (every run type), smooth heat curve
# 7: strength exercise names from the FIT profile (Garmin writes categories as numbers), set durations
# 8: weather from Open-Meteo's hours over the session (dew point for everyone), start point stored
# 9: heat load over the session's hours; heat response learned per person and sport; rides and drift too
ANALYSIS_VERSION = "9"


def reader_for(user: UserConfig):
    """The reader for this person's downloaded data (GarminDB or Intervals.icu)."""
    if user.source == "intervals":
        from .ingest.intervals_reader import IntervalsReader
        reader = IntervalsReader(user.intervals_path)
    elif user.source == "garmin":
        from .ingest.garmindb_reader import GarminDbReader, base_dir_from_config
        reader = GarminDbReader(base_dir_from_config(user.garmindb_dir))
    else:
        raise RuntimeError(f"user {user.id} has no data source (garmindb_config_dir or intervals_dir)")
    if not reader.available:
        raise RuntimeError(f"no downloaded data for {user.id} yet — run the sync first")
    return reader


def ingest(conn: sqlite3.Connection, user: UserConfig, full: bool = False,
           changed_since: datetime | None = None) -> dict:
    """Pull new activities + recent health days from this user's downloaded data into app.db.

    With `changed_since` (start of the last successful sync), activities that were edited since then
    (name, RPE/feel, …) are re-read too."""
    from .ingest.garmindb_reader import default_since

    reader = reader_for(user)
    # Name, sex, max/resting HR, FTP: straight from the source. If they moved, zones and load of the
    # whole history change, so everything is reprocessed with the new values.
    thresholds_changed = profile.refresh(conn, user, reader)
    known = {r["activity_id"] for r in conn.execute("SELECT activity_id FROM sessions WHERE user_id = ?", (user.id,))}
    version_key = f"analysis_version:{user.id}"
    outdated = db.get_state(conn, version_key) != ANALYSIS_VERSION
    reprocess = full or ((thresholds_changed or outdated) and bool(known))
    new_ids = [aid for aid, _ in reader.activity_ids(None if full else default_since()) if full or aid not in known]
    edited = set()
    if changed_since and not full:
        edited = (reader.changed_activity_ids(changed_since) & known) - set(new_ids)
    # New and edited activities first, committed on their own: the wall shows today's workout right
    # away, even when the whole history has to be reprocessed afterwards (minutes on a small server).
    stored = []
    n_new = n_updated = 0
    use_om = weather.enabled(conn, user.id)
    wx_dir = getattr(reader, "weather_dir", None)
    ids = [*new_ids, *sorted(edited)]
    loaded = ((aid, reader.load_activity(aid)) for aid in ids)  # a full import is the whole history: one at a time
    if use_om and not full:  # today's run gets its weather before its verdict; fill_weather does the rest
        loaded = [(aid, act) for aid, act in loaded if act is not None]
        open_meteo.fetch_missing(wx_dir, weather.needs(wx_dir, [act for _, act in loaded]), max_calls=10)
    for aid, act in loaded:
        if act is None:
            continue
        weather.apply(act, wx_dir, use_om)
        stored.append(store_activity(conn, user, act))
        if aid in edited:
            n_updated += 1
        else:
            n_new += 1
    health_since = default_since(400 if full or not known else 14)
    store_health(conn, user.id, reader.health_days(health_since))
    if not full:
        # Baselines only use earlier sessions, so only the new ones need a verdict.
        sessions = user_sessions(conn, user.id)
        for sid in stored:
            evaluate_session(conn, user.id, sid, sessions)
        conn.commit()
    if reprocess:
        if not full:
            why = "HR or power profile changed" if thresholds_changed else "analysis updated"
            log.info("%s: %s — reprocessing %d activities", user.id, why, len(known))
            started = time.monotonic()
            done = set(new_ids) | edited
            for aid, _ in reader.activity_ids(None):
                if aid in known and aid not in done and (act := reader.load_activity(aid)) is not None:
                    weather.apply(act, wx_dir, use_om)
                    store_activity(conn, user, act)
        evaluate_all(conn, user.id)
        if not full:
            log.info("%s: reprocessed %d activities in %.0fs", user.id, len(known), time.monotonic() - started)
    db.set_state(conn, version_key, ANALYSIS_VERSION)  # only once the history is up to date
    conn.commit()
    weather_result = fill_weather(conn, user, reader) if use_om else None
    changed = stored or reprocess or (weather_result or {}).get("updated")
    relearned = refresh_heat(conn, user.id) if changed or not heat_response.learned_yet(conn, user.id) else []
    return {"activities": n_new, "updated": n_updated, "reprocessed": reprocess, "weather": weather_result,
            "heat_relearned": relearned,
            "profile": {k: v["value"] for k, v in profile.describe(conn, user).items()}}


def fill_weather(conn: sqlite3.Connection, user: UserConfig, reader,
                 max_calls: int = open_meteo.MAX_CALLS_PER_RUN) -> dict:
    """Open-Meteo for the outdoor sessions that don't have it yet (the history after an update, a run
    whose fetch failed while offline): fetch what's missing, newest first, a few requests per sync, then
    re-store those sessions and recompute the verdicts they reach. A shown verdict keeps first_shown_at,
    so the wall never pops up again for an old run."""
    wx_dir = getattr(reader, "weather_dir", None)
    if wx_dir is None:
        return {"requests": 0, "updated": 0}
    todo: dict[str, dict] = {}
    for s in user_sessions(conn, user.id):
        f = s.get("features") or {}
        track = [tuple(p) for p in f.get("track") or []]
        if s["indoor"] or not track or s["sport"] == "strength" or (f.get("weather") or {}).get("source") == "Open-Meteo":
            continue
        todo[s["activity_id"]] = {"track": track, "start": datetime.fromisoformat(s["start_time"]),
                                  "duration": s["duration_s"] or 0}
    needs: dict = {}
    for t in todo.values():
        weather.merge_needs(needs, open_meteo.missing(wx_dir, t["track"], t["start"], t["duration"]))
    fetched = open_meteo.fetch_missing(wx_dir, needs, max_calls=max_calls) if needs \
        else {"requests": 0, "days": 0, "pending": 0, "error": None}
    # only what now has hours (a place/day Open-Meteo has nothing for stays as it is, without re-reading it)
    ready = [aid for aid, t in todo.items()
             if open_meteo.read_session(wx_dir, t["track"], t["start"], t["duration"]) is not None]
    stored = []
    for aid in ready:
        act = reader.load_activity(aid)
        if act is None:
            continue
        weather.apply(act, wx_dir, True)
        if (act.weather or {}).get("source") == "Open-Meteo":
            stored.append(store_activity(conn, user, act))
    n = reevaluate_from(conn, user.id, stored) if stored else 0
    conn.commit()
    if stored:
        log.info("%s: Open-Meteo weather for %d sessions, %d verdicts recomputed", user.id, len(stored), n)
    return {"requests": fetched["requests"], "updated": len(stored), "pending": fetched["pending"],
            "error": fetched["error"]}


def refresh_heat(conn: sqlite3.Connection, user_id: str) -> list[str]:
    """Relearn the person's heat response from their stored sessions; where it moved, rewrite that
    sport's adjusted values and work its verdicts out again (first_shown_at kept). Returns those sports."""
    if not heat_response.enabled(conn, user_id):
        return []
    moved = heat_response.refresh(conn, user_id, user_sessions(conn, user_id))
    if moved:
        _reapply_heat(conn, user_id, moved)
        log.info("%s: heat response relearned for %s", user_id, ", ".join(moved))
    conn.commit()
    return moved


def set_heat_learning(conn: sqlite3.Connection, user_id: str, on: bool) -> int:
    """Switch learning the heat response on or off (off = the standard factors) and redo the verdicts of
    the sports it affects. Returns how many verdicts were recomputed."""
    try:
        heat_response.set_enabled(conn, user_id, on)
        heat_response.refresh(conn, user_id, user_sessions(conn, user_id))
        n = _reapply_heat(conn, user_id, list(heat.SPORTS))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return n


def _reapply_heat(conn: sqlite3.Connection, user_id: str, sports: list[str]) -> int:
    """Rewrite and re-judge under the write lock, from sessions read inside it: the sync runs in its own
    process, and a session it stores meanwhile (new weather, a new run) must not be overwritten with an
    older copy. No commit."""
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    sessions = user_sessions(conn, user_id)
    ids = heat_response.rewrite(conn, user_id, sessions, sports)
    first: dict[str, str] = {}
    for s in sessions:  # oldest first: the first of each sport reaches all the others
        if s["id"] in ids:
            first.setdefault(s["sport"], s["id"])
    return reevaluate_from(conn, user_id, list(first.values())) if first else 0


ingest_from_garmindb = ingest  # the name before Intervals.icu existed
