"""Today's training and Training Readiness from Garmin Connect — things GarminDB doesn't download.

After every successful sync we ask Garmin (with the person's cached login, like the activity check) for:
- the calendar of this month (and next month near the month's end): the planned workouts of the
  next 7 days — Garmin Coach's adaptive workouts (`fbtAdaptiveWorkout`) and workouts you scheduled
  yourself (`workout`), each with its steps and targets,
- the training plan's name and length (for "week 4 of 12"),
- today's Training Readiness (Garmin's score, the one the watch shows).

A fetch that fails leaves the stored rows alone: the wall keeps showing the last good copy of
today's workout instead of pretending it's a rest day.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Callable

import json

from .. import db

log = logging.getLogger(__name__)

CALENDAR_URL = "/calendar-service/year/{year}/month/{month0}"   # month is 0-based (January = 0)
ADAPTIVE_WORKOUT_URL = "/workout-service/fbt-adaptive/{uuid}"
WORKOUT_URL = "/workout-service/workout/{workout_id}"
PLAN_URL = "/trainingplan-service/trainingplan/fbt-adaptive/{plan_id}"
READINESS_URL = "/metrics-service/metrics/trainingreadiness/{day}"

DAYS_AHEAD = 7
FRESH_DAYS = 2        # today and tomorrow are fetched on every sync (Garmin Coach adapts them daily)
KEEP_DAYS = 14        # planned workouts older than this are deleted
# ids from Garmin's answers go into request paths: accept only these shapes
_UUID = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")


def _id(v) -> int | None:
    s = str(v or "")
    return int(s) if s.isdigit() and len(s) <= 20 else None
PLANNED_TYPES = {"fbtAdaptiveWorkout", "workout"}
# Garmin's sport keys → ours
SPORTS = {"running": "running", "trail_running": "running", "treadmill_running": "running",
          "cycling": "cycling", "indoor_cycling": "cycling", "virtual_ride": "cycling",
          "swimming": "swimming", "lap_swimming": "swimming", "open_water_swimming": "swimming",
          "strength_training": "strength", "fitness_equipment": "strength"}


# --- parsing (pure, tested against real anonymized answers in tests/fixtures/garmin) ---------

def _pace_target(lo, hi) -> dict | None:
    """Garmin gives pace targets as speeds in m/s; the faster one is the larger number."""
    speeds = [v for v in (lo, hi) if isinstance(v, (int, float)) and v > 0]
    if not speeds:
        return None
    return {"type": "pace", "low_s_per_km": round(1000 / max(speeds)), "high_s_per_km": round(1000 / min(speeds))}


def _target(step: dict) -> dict | None:
    key = (step.get("targetType") or {}).get("workoutTargetTypeKey")
    lo, hi = step.get("targetValueOne"), step.get("targetValueTwo")
    if key in ("pace.zone", "speed.zone"):
        return _pace_target(lo, hi)
    if key == "heart.rate.zone":
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            return {"type": "hr", "low": round(min(lo, hi)), "high": round(max(lo, hi))}
        if step.get("zoneNumber"):
            return {"type": "hr_zone", "zone": step["zoneNumber"]}
    if key == "power.zone" and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        return {"type": "power", "low": round(min(lo, hi)), "high": round(max(lo, hi))}
    if key == "cadence" and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        return {"type": "cadence", "low": round(min(lo, hi)), "high": round(max(lo, hi))}
    return None


def _steps(raw: list[dict]) -> list[dict]:
    """Garmin's nested steps → flat list; repeat groups are expanded (6 × 800 m becomes 6 intervals
    with recoveries) so the wall can draw the workout's shape and count the blocks."""
    out: list[dict] = []
    for s in sorted(raw or [], key=lambda s: s.get("stepOrder") or 0):
        if s.get("type") == "RepeatGroupDTO" or s.get("workoutSteps"):
            inner = _steps(s.get("workoutSteps") or [])
            for _ in range(int(s.get("numberOfIterations") or 1)):
                out.extend(dict(x) for x in inner)
            continue
        cond = (s.get("endCondition") or {}).get("conditionTypeKey")
        value = s.get("endConditionValue")
        out.append({
            "kind": (s.get("stepType") or {}).get("stepTypeKey") or "other",  # warmup/interval/recovery/rest/cooldown
            "duration_s": round(value) if cond == "time" and isinstance(value, (int, float)) else None,
            "distance_m": round(value) if cond == "distance" and isinstance(value, (int, float)) else None,
            "target": _target(s),
            "description": s.get("description"),
        })
    return out


def parse_workout(raw: dict) -> dict:
    """A Garmin workout (adaptive or your own) → what the wall shows."""
    steps = []
    for seg in raw.get("workoutSegments") or []:
        steps.extend(_steps(seg.get("workoutSteps") or []))
    sport_key = (raw.get("sportType") or {}).get("sportTypeKey")
    est = raw.get("estimatedDurationInSecs")
    timed = sum(s["duration_s"] or 0 for s in steps)
    return {
        "title": raw.get("workoutName"),
        "sport": SPORTS.get(sport_key, "other"),
        "description": raw.get("description"),
        "phrase": raw.get("workoutPhrase") or raw.get("trainingEffectLabel"),   # e.g. LACTATE_THRESHOLD
        "est_duration_s": round(est) if isinstance(est, (int, float)) else (timed or None),
        "est_distance_m": raw.get("estimatedDistanceInMeters"),
        "est_training_effect": raw.get("estimatedTrainingEffect"),
        "steps": steps,
    }


def planned_items(calendar: dict, start: date, days: int = DAYS_AHEAD) -> list[dict]:
    """Planned workouts from a calendar answer, from `start` for `days` days."""
    end = start + timedelta(days=days)
    out = []
    for item in (calendar or {}).get("calendarItems") or []:
        if item.get("itemType") not in PLANNED_TYPES:
            continue
        try:
            day = date.fromisoformat(str(item.get("date"))[:10])
        except ValueError:
            continue
        if start <= day < end:
            out.append(item)
    return out


def parse_readiness(rows, day: date | None = None) -> dict | None:
    """Garmin sends one entry per reset (after waking, after a workout, …); the newest is what the watch shows."""
    rows = [r for r in (rows if isinstance(rows, list) else []) if isinstance(r, dict) and isinstance(r.get("score"), (int, float))]
    if not rows:
        return None
    r = max(rows, key=lambda r: str(r.get("timestampLocal") or r.get("timestamp") or ""))
    factors = {k: r.get(f"{k}FactorPercent") for k in ("sleepScore", "recoveryTime", "acwr", "hrv", "stressHistory", "sleepHistory")}
    when = str(r.get("calendarDate") or "")[:10] or (day or date.today()).isoformat()
    return {"day": when, "score": round(r["score"]), "level": r.get("level"),
            "feedback": r.get("feedbackShort"), "time": r.get("timestampLocal"),
            "recovery_min": r.get("recoveryTime"), "factors": factors}


def plan_info(raw: dict, day: date) -> dict | None:
    if not raw or not raw.get("name"):
        return None
    weeks, week = raw.get("durationInWeeks"), None
    try:
        start = date.fromisoformat(str(raw.get("startDate"))[:10])
        week = (day - start).days // 7 + 1
    except ValueError:
        pass
    return {"name": raw["name"], "weeks": weeks, "week": week,
            "end": str(raw.get("endDate") or "")[:10] or None}


# --- fetching + storing -----------------------------------------------------------------------

def update(conn: sqlite3.Connection, user_id: str, connectapi: Callable, today: date | None = None) -> dict:
    """Fetch the next 7 days of planned workouts and today's readiness; store them. Errors raise
    before anything is replaced, so the last good copy stays."""
    today = today or date.today()
    months = {(today.year, today.month)}
    last = today + timedelta(days=DAYS_AHEAD - 1)
    months.add((last.year, last.month))
    items = []
    for year, month in sorted(months):
        items += planned_items(connectapi(CALENDAR_URL.format(year=year, month0=month - 1)), today)

    # details already stored (for the days after tomorrow they're reused once fetched today)
    stored = {(r["day"], r["key"]): (json.loads(r["data"]) if r["data"] else None, r["fetched_at"]) for r in conn.execute(
        "SELECT day, key, data, fetched_at FROM planned_workouts WHERE user_id = ? AND day >= ?", (user_id, today.isoformat()))}
    plans: dict = {}
    workouts = []
    for item in items:
        day = date.fromisoformat(str(item["date"])[:10])
        uuid = item.get("workoutUuid") if _UUID.match(str(item.get("workoutUuid") or "")) else None
        wid = _id(item.get("workoutId"))
        key = uuid or (str(wid) if wid else None)
        if key is None:
            log.warning("coach %s: skipping a planned item without a valid workout id", user_id)
            continue
        cached, fetched = stored.get((day.isoformat(), key), (None, None))
        if cached and (day - today).days >= FRESH_DAYS and str(fetched or "")[:10] == today.isoformat():
            workouts.append((day, key, cached))
            continue
        if item["itemType"] == "fbtAdaptiveWorkout" and uuid:
            raw = connectapi(ADAPTIVE_WORKOUT_URL.format(uuid=uuid))
        elif wid:
            raw = connectapi(WORKOUT_URL.format(workout_id=wid))
        else:
            continue
        w = parse_workout(raw if isinstance(raw, dict) else {})
        w["title"] = w["title"] or item.get("title")
        if w["sport"] == "other":
            w["sport"] = SPORTS.get(item.get("sportTypeKey"), "other")
        pid = _id(item.get("trainingPlanId"))
        if pid and item["itemType"] == "fbtAdaptiveWorkout":
            if pid not in plans:
                try:
                    plans[pid] = connectapi(PLAN_URL.format(plan_id=pid))
                except Exception as e:  # nice-to-have: the plan's name and week
                    log.warning("training plan %s: %s", pid, str(e)[:120])
                    plans[pid] = None
            w["plan"] = plan_info(plans[pid] if isinstance(plans[pid], dict) else {}, day)
        w["source"] = "garmin_coach" if item["itemType"] == "fbtAdaptiveWorkout" else "garmin_calendar"
        workouts.append((day, key, w))

    readiness = parse_readiness(connectapi(READINESS_URL.format(day=today)), today)

    now = datetime.now().isoformat(timespec="seconds")
    with conn:
        conn.execute("DELETE FROM planned_workouts WHERE user_id = ? AND (day >= ? OR day < ?)",
                     (user_id, today.isoformat(), (today - timedelta(days=KEEP_DAYS)).isoformat()))
        for day, key, w in workouts:
            db.upsert(conn, "planned_workouts", {"user_id": user_id, "day": day.isoformat(), "key": key,
                                                 "title": w["title"], "sport": w["sport"], "data": w,
                                                 "fetched_at": now})
        if readiness:
            db.upsert(conn, "readiness_days", {"user_id": user_id, "day": readiness["day"], "score": readiness["score"],
                                               "level": readiness["level"], "data": readiness, "fetched_at": now})
    return {"workouts": len(workouts), "readiness": readiness["score"] if readiness else None}


def update_user(conn: sqlite3.Connection, user) -> None:
    """After a sync: refresh with the cached login. Never fails the sync, and stays quiet while the
    activity check is paused for Garmin's rate limit."""
    from .activity_watch import K_BACKOFF, cached_client
    backoff = db.get_state(conn, K_BACKOFF)
    if backoff and datetime.now().isoformat() < backoff:
        log.info("coach %s: skipped, Garmin rate-limit pause until %s", user.id, backoff[11:16])
        return
    try:
        result = update(conn, user.id, cached_client(user).connectapi)
        log.info("coach %s: %d planned workouts, readiness %s", user.id, result["workouts"], result["readiness"])
    except Exception as e:
        log.warning("coach %s: kept the last good copy (%s)", user.id, str(e)[:200])
