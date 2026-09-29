"""What the wall shows right now, and the read models behind the API."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from statistics import median

from . import db
from .analytics import load as load_model
from .config import AppConfig
from .pipeline import user_sessions


def _now() -> datetime:
    return datetime.now()


def fresh_verdict(conn: sqlite3.Connection, cfg: AppConfig, now: datetime | None = None) -> dict | None:
    """The newest verdict that should take over the wall, across all users.

    - The activity must have started within `fresh_activity_hours` (backfills never trigger).
    - Once first shown, it stays up for `verdict_minutes`, then never again, even after restarts.
    - The latest activity wins when several people are fresh.
    """
    now = now or _now()
    cutoff = (now - timedelta(hours=cfg.wall.fresh_activity_hours)).isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT v.*, s.start_time FROM verdicts v JOIN sessions s ON s.id = v.session_id
           WHERE s.start_time >= ? ORDER BY s.start_time DESC""", (cutoff,)).fetchall()
    for r in rows:
        shown = r["first_shown_at"]
        if shown is None or datetime.fromisoformat(shown) > now - timedelta(minutes=cfg.wall.verdict_minutes):
            return db.row_to_dict(r)
    return None


def mark_shown(conn: sqlite3.Connection, session_id: str, now: datetime | None = None) -> None:
    conn.execute("UPDATE verdicts SET first_shown_at = ? WHERE session_id = ? AND first_shown_at IS NULL",
                 ((now or _now()).isoformat(timespec="seconds"), session_id))
    conn.commit()


def dismiss(conn: sqlite3.Connection, session_id: str, cfg: AppConfig) -> None:
    """Back to ambient early: pretend it was shown long enough ago."""
    past = (_now() - timedelta(minutes=cfg.wall.verdict_minutes + 1)).isoformat(timespec="seconds")
    conn.execute("UPDATE verdicts SET first_shown_at = ? WHERE session_id = ?", (past, session_id))
    conn.commit()


def session_card(conn: sqlite3.Connection, session_id: str) -> dict | None:
    s = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())
    if not s:
        return None
    s["verdict"] = db.row_to_dict(conn.execute("SELECT * FROM verdicts WHERE session_id = ?", (session_id,)).fetchone())
    return s


def session_detail(conn: sqlite3.Connection, session_id: str) -> dict | None:
    s = session_card(conn, session_id)
    if not s:
        return None
    st = conn.execute("SELECT data FROM session_streams WHERE session_id = ?", (session_id,)).fetchone()
    s["streams"] = db.row_to_dict(st)["data"] if st else None
    s["sets"] = [dict(r) for r in conn.execute(
        "SELECT * FROM exercise_sets WHERE session_id = ? ORDER BY set_index", (session_id,))]
    ids = (s["verdict"] or {}).get("baseline_ids") or []
    base = []
    for bid in ids:
        b = db.row_to_dict(conn.execute("SELECT id, name, start_time, duration_s, distance_m, avg_hr, session_type, "
                                        "features, rpe, feel FROM sessions WHERE id = ?", (bid,)).fetchone())
        if b:
            base.append(b)
    s["baseline_sessions"] = base
    return s


def sync_info(conn: sqlite3.Connection, cfg: AppConfig, user_id: str) -> dict:
    r = db.row_to_dict(conn.execute("SELECT * FROM sync_status WHERE user_id = ?", (user_id,)).fetchone()) or {}
    last = r.get("last_success")
    stale = True
    age_h = None
    if last:
        age_h = (_now() - datetime.fromisoformat(last)).total_seconds() / 3600
        stale = age_h > cfg.wall.stale_sync_hours
    return {"last_success": last, "last_attempt": r.get("last_attempt"), "last_error": r.get("last_error"),
            "age_hours": round(age_h, 1) if age_h is not None else None, "stale": stale}


def _health_series(conn, user_id: str, days: int) -> list[dict]:
    d0 = (date.today() - timedelta(days=days)).isoformat()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM health_days WHERE user_id = ? AND day >= ? ORDER BY day", (user_id, d0))]


PROGRESS_WEEKS = 6
SPORT_NAMES = {"running": "Running", "cycling": "Cycling", "swimming": "Swimming", "strength": "Gym"}


def _change_over(points: list[tuple[str, float]], days: int) -> tuple[float, float] | None:
    """(latest, change) vs the last value at least `days` before the latest one."""
    if not points:
        return None
    last_day, last = points[-1]
    cutoff = (date.fromisoformat(last_day[:10]) - timedelta(days=days)).isoformat()
    before = [v for d, v in points if d[:10] <= cutoff]
    return (last, last - before[-1]) if before else None


def _window_change(values: list[tuple[str, float]], days: int) -> tuple[float, float] | None:
    """Median of the last 7 days vs the 7 days `days` ago (smooths day-to-day noise)."""
    end = date.today()
    now = [v for d, v in values if d >= (end - timedelta(days=7)).isoformat()]
    then = [v for d, v in values
            if (end - timedelta(days=days + 7)).isoformat() <= d < (end - timedelta(days=days)).isoformat()]
    if len(now) < 3 or len(then) < 3:
        return None
    return median(now), median(now) - median(then)


def _item(key, label, value, change, unit, dp, higher_is_better, steady, sport=None, link=None) -> dict:
    good = change > 0 if higher_is_better else change < 0
    tone = "steady" if abs(change) < steady else ("improving" if good else "declining")
    return {"key": key, "label": label, "value": None if value is None else round(value, dp),
            "change": round(change, dp), "unit": unit, "dp": dp, "tone": tone, "score": abs(change) / steady,
            "sport": sport, "link": link}


def progress(conn: sqlite3.Connection, user_id: str, trends: dict, pmc: list[dict]) -> dict:
    """Where you are getting fitter over the last 6 weeks — the wall's headline.

    Only real fitness markers: Garmin VO2max, efficiency trend per sport (pace/power per heartbeat,
    e1RM), resting HR, HRV and chronic training load. Improvements first, then steady, then declining."""
    days = PROGRESS_WEEKS * 7
    health = _health_series(conn, user_id, 400)
    items = []
    for col, label in (("vo2max", "VO₂max running"), ("vo2max_cycling", "VO₂max cycling")):
        c = _change_over([(h["day"], h[col]) for h in health if h.get(col)], days)
        if c:
            items.append(_item(col, label, *c, "", 1, True, 0.05, link="vo2max"))
    active_since = (date.today() - timedelta(days=days)).isoformat()
    for sport, t in trends.items():
        if t.get("pct_per_week") is not None and t.get("last_time", "") >= active_since:
            # the metric's raw value means little on its own; the % change does
            items.append(_item(f"trend_{sport}", f"{SPORT_NAMES.get(sport, sport)} · {t['metric'] or 'e1RM'}",
                               None, t["pct_per_week"] * PROGRESS_WEEKS, "%", 1, True, 1.0, sport=sport))
    rhr = _window_change([(h["day"], h["rhr"]) for h in health if h.get("rhr")], days)
    if rhr:
        items.append(_item("rhr", "Resting HR", *rhr, " bpm", 0, False, 1.0, link="rhr"))
    hrv = _window_change([(h["day"], h["hrv_last_night"]) for h in health if h.get("hrv_last_night")], days)
    if hrv:
        items.append(_item("hrv", "HRV", *hrv, " ms", 0, True, 2.0, link="hrv"))
    if len(pmc) > days:
        items.append(_item("fitness", "Training fitness", pmc[-1]["fitness"],
                           pmc[-1]["fitness"] - pmc[-1 - days]["fitness"], "", 0, True, 2.0))
    order = {"improving": 0, "steady": 1, "declining": 2}
    items.sort(key=lambda i: (order[i["tone"]], -i["score"]))
    return {"weeks": PROGRESS_WEEKS, "items": items,
            "improving": sum(i["tone"] == "improving" for i in items),
            "declining": sum(i["tone"] == "declining" for i in items)}


def ambient(conn: sqlite3.Connection, cfg: AppConfig, user_id: str) -> dict:
    sessions = user_sessions(conn, user_id)
    today = date.today()
    series = load_model.pmc(load_model.daily_loads(sessions), None, today) if sessions else []
    pmc_42 = series[-42:]
    health = _health_series(conn, user_id, 42)
    latest = health[-1] if health else {}
    base = {}
    for key in ("rhr", "hrv_last_night", "sleep_total_min", "stress_avg", "bb_max"):
        vals = [h[key] for h in health[:-1] if h.get(key) is not None][-28:]
        base[key] = round(median(vals), 1) if len(vals) >= 5 else None

    def week_totals(offset: int) -> dict:
        start = today - timedelta(days=today.weekday() + 7 * offset)
        end = start + timedelta(days=7)
        out: dict[str, dict] = {}
        for s in sessions:
            d = date.fromisoformat(s["start_time"][:10])
            if start <= d < end:
                w = out.setdefault(s["sport"], {"count": 0, "duration_s": 0.0, "distance_m": 0.0, "load": 0.0})
                w["count"] += 1
                w["duration_s"] += s.get("duration_s") or 0
                w["distance_m"] += s.get("distance_m") or 0
                w["load"] += s.get("load") or 0
        return out

    # efficiency trend per sport from the latest verdict of that sport
    trends = {}
    for sport in ("running", "cycling", "swimming", "strength"):
        r = conn.execute(
            """SELECT v.trend, v.verdict, s.start_time, s.id FROM verdicts v JOIN sessions s ON s.id = v.session_id
               WHERE s.user_id = ? AND s.sport = ? ORDER BY s.start_time DESC LIMIT 1""", (user_id, sport)).fetchone()
        if r:
            t = db.row_to_dict(r)
            trends[sport] = {"last_session": t["id"], "last_time": t["start_time"], "last_verdict": t["verdict"],
                             "metric": t["trend"].get("trend_metric"), "pct_per_week": t["trend"].get("trend_pct_per_week"),
                             "points": t["trend"].get("trend_points", [])}

    recent = conn.execute(
        """SELECT s.id, s.name, s.sport, s.session_type, s.start_time, s.duration_s, s.distance_m, s.load,
                  v.verdict, v.headline FROM sessions s LEFT JOIN verdicts v ON v.session_id = s.id
           WHERE s.user_id = ? ORDER BY s.start_time DESC LIMIT 8""", (user_id,)).fetchall()
    vo2 = [{"day": h["day"], "value": h["vo2max"]} for h in _health_series(conn, user_id, 365) if h.get("vo2max")]
    return {
        "user_id": user_id,
        "pmc": pmc_42,
        "form": pmc_42[-1] if pmc_42 else None,
        "health_latest": latest,
        "health_baseline": base,
        "health_series": health,
        "week": week_totals(0),
        "last_week": week_totals(1),
        "trends": trends,
        "recent": [dict(r) for r in recent],
        "vo2max": vo2,
        "progress": progress(conn, user_id, trends, series),
        "sync": sync_info(conn, cfg, user_id),
    }


def validation(conn: sqlite3.Connection, user_id: str, days: int = 120) -> dict:
    """How often the verdicts agree with how you said you felt (Garmin self-evaluation)."""
    d0 = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT s.id, s.start_time, s.sport, s.rpe, s.feel, v.verdict FROM sessions s
           JOIN verdicts v ON v.session_id = s.id
           WHERE s.user_id = ? AND s.start_time >= ? AND v.verdict IN ('better','worse','in_line')
             AND s.feel IS NOT NULL""", (user_id, d0)).fetchall()
    agree = disagree = 0
    flagged = []
    for r in rows:
        if r["verdict"] == "in_line":
            continue
        good_feel = r["feel"] >= 75
        bad_feel = r["feel"] <= 25
        if (r["verdict"] == "better" and good_feel) or (r["verdict"] == "worse" and bad_feel):
            agree += 1
        elif (r["verdict"] == "better" and bad_feel) or (r["verdict"] == "worse" and good_feel):
            disagree += 1
            flagged.append(dict(r))
    judged = agree + disagree
    return {"days": days, "rated_sessions": len(rows), "agree": agree, "disagree": disagree,
            "agreement_pct": round(agree / judged * 100) if judged else None, "flagged": flagged[:10]}
