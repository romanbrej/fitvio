"""The wall's motivation layer: today's planned workout, Garmin's readiness, the week streak and the
weekly load sweet spot. All loads are TRIMP (the app's training load), never Garmin's own load."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from statistics import median

from . import db

STREAK_MIN_SESSIONS = 3        # a week counts for the streak with at least this many workouts
STREAK_MIN_DURATION_S = 600    # … each at least 10 minutes
STREAK_HISTORY_WEEKS = 8

# Weekly load that raises fitness (CTL) by 1–5 points a week. With a 42-day CTL a week of constant
# daily load L moves CTL by (L − CTL)·(1 − e^(−7/42)) ≈ 0.1535·(L − CTL), so the weekly load
# W = 7·L for a change Δ is 7·CTL + Δ·7/0.1535 ≈ 7·CTL + 45.6·Δ.
SWEET_SPOT_RAMP = (1.0, 5.0)
_RAMP_FACTOR = 7 / 0.1535

# Garmin's workout purpose → our session type (for the load estimate from your own history)
PHRASE_TYPES = {"RECOVERY": "easy", "AEROBIC_BASE": "easy", "BASE": "easy", "LONG_RUN": "long", "LONG": "long",
                "TEMPO": "tempo", "LACTATE_THRESHOLD": "tempo", "THRESHOLD": "tempo",
                "VO2MAX": "intervals", "ANAEROBIC_CAPACITY": "intervals", "ANAEROBIC": "intervals",
                "SPRINT": "intervals", "SPEED": "intervals"}
# fallback TRIMP per hour when there's no own history yet
DEFAULT_LOAD_PER_H = {"easy": 70.0, "long": 80.0, "tempo": 120.0, "intervals": 130.0, "other": 80.0}


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


# --- week streak ---------------------------------------------------------------------------

def week_streak(sessions: list[dict], today: date) -> dict:
    """Weeks in a row (Mon–Sun) with ≥3 workouts. The running week counts once it reaches 3; until
    then the streak shows the completed weeks and what's still needed to keep it."""
    counts: dict[date, int] = {}
    for s in sessions:
        if (s.get("duration_s") or 0) < STREAK_MIN_DURATION_S:
            continue
        w = week_start(date.fromisoformat(s["start_time"][:10]))
        counts[w] = counts.get(w, 0) + 1
    this = week_start(today)
    streak, w = 0, this - timedelta(days=7)
    while counts.get(w, 0) >= STREAK_MIN_SESSIONS:
        streak += 1
        w -= timedelta(days=7)
    now = counts.get(this, 0)
    if now >= STREAK_MIN_SESSIONS:
        streak += 1
    history = [{"week": (this - timedelta(days=7 * i)).isoformat(), "count": counts.get(this - timedelta(days=7 * i), 0)}
               for i in range(STREAK_HISTORY_WEEKS - 1, -1, -1)]
    return {"weeks": streak, "this_week": now, "needed": max(0, STREAK_MIN_SESSIONS - now),
            "min_sessions": STREAK_MIN_SESSIONS, "days_left": 6 - today.weekday(), "history": history}


# --- weekly sweet spot ---------------------------------------------------------------------

def sweet_spot(series: list[dict], sessions: list[dict], today: date) -> dict | None:
    """Target TRIMP for this week from fitness at the start of the week, and the load so far."""
    if not series:
        return None
    monday = week_start(today)
    before = [r for r in series if r["day"] < monday.isoformat()]
    ctl = (before[-1] if before else series[0])["fitness"]
    low = 7 * ctl + SWEET_SPOT_RAMP[0] * _RAMP_FACTOR
    high = 7 * ctl + SWEET_SPOT_RAMP[1] * _RAMP_FACTOR
    so_far = sum(s.get("load") or 0 for s in sessions if s["start_time"][:10] >= monday.isoformat())
    return {"low": round(low / 10) * 10, "high": round(high / 10) * 10, "load": round(so_far),
            "fitness_at_start": round(ctl, 1)}


# --- readiness -----------------------------------------------------------------------------

def readiness(conn: sqlite3.Connection, user_id: str, today: date) -> dict | None:
    r = db.row_to_dict(conn.execute("SELECT * FROM readiness_days WHERE user_id = ? AND day = ?",
                                    (user_id, today.isoformat())).fetchone())
    return r["data"] if r else None


# --- today's workout -----------------------------------------------------------------------

def _session_type(workout: dict) -> str:
    t = PHRASE_TYPES.get(str(workout.get("phrase") or "").upper())
    if t:
        return t
    return "long" if (workout.get("est_duration_s") or 0) >= 75 * 60 else "easy"


def estimate_load(workout: dict, sessions: list[dict], today: date) -> float | None:
    """TRIMP estimate: the workout's duration × your own median load per hour for that kind of
    session in the last 4 months (same sport), or a typical value when there's no history."""
    dur = workout.get("est_duration_s")
    if not dur:
        return None
    kind = _session_type(workout)
    lo = (today - timedelta(days=120)).isoformat()
    rates = [s["load"] / (s["duration_s"] / 3600) for s in sessions
             if s["sport"] == workout.get("sport") and s["start_time"][:10] >= lo and s.get("load")
             and (s.get("duration_s") or 0) >= 600 and s.get("session_type") == kind]
    rate = median(rates) if len(rates) >= 3 else DEFAULT_LOAD_PER_H.get(kind, DEFAULT_LOAD_PER_H["other"])
    return round(rate * dur / 3600)


def _targets_hit(workout: dict, streams: dict | None) -> dict | None:
    """Started from the workout, the run follows its steps in time: average the pace inside each
    timed work step's window (laps don't help — auto-lap splits them every km) and count the ones that
    landed in the target range (5 s/km tolerance)."""
    t, speed = (streams or {}).get("t") or [], (streams or {}).get("speed") or []
    steps = workout.get("steps") or []
    if not t or not speed or not steps or any(not s.get("duration_s") for s in steps):
        return None
    work = hit = 0
    start = 0.0
    for step in steps:
        end = start + step["duration_s"]
        tgt = step.get("target") or {}
        if step.get("kind") == "interval" and tgt.get("type") == "pace":
            vals = [v for x, v in zip(t, speed) if start + 15 <= x < end and v]  # skip the first seconds of the step
            if vals:
                work += 1
                pace = 1000 / (sum(vals) / len(vals))
                hit += tgt["low_s_per_km"] - 5 <= pace <= tgt["high_s_per_km"] + 5
        start = end
    return {"hit": hit, "of": work} if work else None


def _done(conn: sqlite3.Connection, workout: dict, sessions: list[dict], today: date) -> dict | None:
    """Garmin names a run started from the workout after it ("City - Schwelle") — that's a sure link.
    Otherwise the first session of the same sport that day counts."""
    todays = [s for s in sessions if s["start_time"][:10] == today.isoformat() and s["sport"] == workout.get("sport")]
    if not todays:
        return None
    title = str(workout.get("title") or "").lower()
    linked = [s for s in todays if title and title in str(s.get("name") or "").lower()]
    s = (linked or todays)[0]
    v = db.row_to_dict(conn.execute("SELECT verdict, headline FROM verdicts WHERE session_id = ?", (s["id"],)).fetchone()) or {}
    hit = None
    if linked:
        st = db.row_to_dict(conn.execute("SELECT data FROM session_streams WHERE session_id = ?", (s["id"],)).fetchone())
        hit = _targets_hit(workout, (st or {}).get("data"))
    return {"session_id": s["id"], "name": s.get("name"), "linked": bool(linked), "verdict": v.get("verdict"),
            "headline": v.get("headline"), "load": s.get("load"), "targets": hit}


def planned(conn: sqlite3.Connection, user_id: str, sessions: list[dict], today: date) -> tuple[dict | None, list[dict]]:
    """(today's workout or None, the next days' workouts)."""
    rows = [db.row_to_dict(r) for r in conn.execute(
        "SELECT * FROM planned_workouts WHERE user_id = ? AND day >= ? ORDER BY day, key",
        (user_id, today.isoformat()))]
    out = []
    for r in rows:
        w = dict(r["data"] or {})
        w.update(day=r["day"], title=w.get("title") or r["title"], sport=w.get("sport") or r["sport"],
                 fetched_at=r["fetched_at"])
        w["est_load"] = estimate_load(w, sessions, today)
        out.append(w)
    todays = [w for w in out if w["day"] == today.isoformat()]
    today_w = todays[0] if todays else None
    if today_w:
        today_w["done"] = _done(conn, today_w, sessions, today)
    upcoming = [{k: w.get(k) for k in ("day", "title", "sport", "phrase", "description", "est_duration_s", "est_load")}
                for w in out if w["day"] > today.isoformat()]
    return today_w, upcoming


# --- running cadence -----------------------------------------------------------------------

def spm(avg_cadence: float | None) -> float | None:
    """FIT running cadence is per leg (≈ 85–95); steps per minute is twice that."""
    if not avg_cadence:
        return None
    return avg_cadence * 2 if avg_cadence < 120 else avg_cadence


def running_cadence(sessions: list[dict], today: date) -> dict | None:
    """Median cadence of the easy and long runs of the last 6 weeks vs the 6 weeks before (like the pace
    number: intervals naturally run at a higher cadence, so they'd blur the trend)."""
    def window(a, b):
        lo, hi = (today - timedelta(days=a)).isoformat(), (today - timedelta(days=b)).isoformat()
        return [spm((s.get("features") or {}).get("avg_cadence")) for s in sessions
                if s["sport"] == "running" and s.get("session_type") in {"easy", "long"} and lo <= s["start_time"][:10] <= hi]
    now = [v for v in window(42, -1) if v]
    before = [v for v in window(84, 43) if v]
    if not now:
        return None
    cur = median(now)
    return {"spm": round(cur), "change": round(cur - median(before)) if len(before) >= 3 else None, "runs": len(now)}
