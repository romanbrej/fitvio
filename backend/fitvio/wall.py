"""What the wall shows right now, and the read models behind the API."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from statistics import median

from . import buddy, coach, db, improvements, profile
from .analytics import load as load_model
from .analytics import physio
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


def session_card(conn: sqlite3.Connection, session_id: str, sessions: list[dict] | None = None) -> dict | None:
    """The session with its verdict and "What improved". `sessions`: the person's sessions, if already loaded."""
    s = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())
    if not s:
        return None
    s["verdict"] = db.row_to_dict(conn.execute("SELECT * FROM verdicts WHERE session_id = ?", (session_id,)).fetchone())
    return improvements.attach(conn, s, sessions)


def session_detail(conn: sqlite3.Connection, session_id: str) -> dict | None:
    s = session_card(conn, session_id)
    if not s:
        return None
    st = conn.execute("SELECT data FROM session_streams WHERE session_id = ?", (session_id,)).fetchone()
    s["streams"] = db.row_to_dict(st)["data"] if st else None
    s["sets"] = [dict(r) for r in conn.execute(
        "SELECT * FROM exercise_sets WHERE session_id = ? ORDER BY set_index", (session_id,))]
    s["baseline_sessions"] = _sessions_by_id(conn, (s["verdict"] or {}).get("baseline_ids") or [])
    return s


def _sessions_by_id(conn: sqlite3.Connection, ids: list[str]) -> list[dict]:
    """The baseline sessions in one query, in the order of `ids` (missing ones are skipped)."""
    if not ids:
        return []
    marks = ", ".join("?" for _ in ids)
    rows = conn.execute(f"SELECT id, name, start_time, duration_s, distance_m, avg_hr, session_type, features, rpe, "
                        f"feel FROM sessions WHERE id IN ({marks})", ids)
    found = {r["id"]: db.row_to_dict(r) for r in rows}
    return [found[i] for i in ids if i in found]


def sync_info(conn: sqlite3.Connection, cfg: AppConfig, user_id: str) -> dict:
    r = db.row_to_dict(conn.execute("SELECT * FROM sync_status WHERE user_id = ?", (user_id,)).fetchone()) or {}
    last = r.get("last_success")
    stale = True
    age_h = None
    if last:
        age_h = (_now() - datetime.fromisoformat(last)).total_seconds() / 3600
        stale = age_h > cfg.wall.stale_sync_hours
    from .sync.activity_watch import paused_for_login

    return {"last_success": last, "last_attempt": r.get("last_attempt"), "last_error": r.get("last_error"),
            "age_hours": round(age_h, 1) if age_h is not None else None, "stale": stale,
            # the auto-sync check found the cached Garmin login expired (it never uses the password itself)
            "login_expired": paused_for_login(conn, user_id)}


def health_series(conn: sqlite3.Connection, user_id: str, days: int) -> list[dict]:
    """Daily health rows (sleep, HRV, resting HR …) of the last `days` days, oldest first."""
    d0 = (date.today() - timedelta(days=days)).isoformat()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM health_days WHERE user_id = ? AND day >= ? ORDER BY day", (user_id, d0))]


def _is_today(start_time: str, now: datetime | None = None) -> bool:
    """The 'Last workout' card is only for the day of the workout; at midnight the wall resets."""
    return start_time[:10] == (now or _now()).date().isoformat()


REF_HR_BAND = 12.0  # bpm around the reference HR, the same band physio.speed_at_hr reads from


def sport_status(sessions: list[dict], sport: str, ftp: float | None, weights: improvements.Weights,
                 today: date) -> dict | None:
    """The sport card's headline in real units, computed live from the sessions.

    running: pace at the fixed reference HR (heat & grade adjusted) of the steady outdoor runs in 6 weeks,
             and how many s/km it changed over that time (+ = faster).
    cycling: power per heartbeat of the rides with power in 3 months, plus W/kg of FTP and of the
             power at the reference HR.
    strength: sessions per 6 weeks vs the 6 before, and the e1RM trend when weights are logged.
    """
    def recent(days, keep):
        lo = (today - timedelta(days=days)).isoformat()
        return sorted((s for s in sessions if s["sport"] == sport and s["start_time"][:10] >= lo and keep(s)),
                      key=lambda s: s["start_time"])

    if sport == "running":
        # easy and long runs only, and only when the run's average HR was near the reference HR: tempo
        # runs barely touch it, so their value would come from warm-up/cool-down and extrapolation
        runs = recent(42, lambda s: s["session_type"] in {"easy", "long"} and not s.get("indoor"))
        pts = []
        for s in runs:
            f = s.get("features") or {}
            v = f.get("speed_at_ref_hr_adj") or f.get("speed_at_ref_hr")
            ref, avg = f.get("ref_hr"), s.get("avg_hr")
            if v and (not ref or not avg or abs(avg - ref) <= REF_HR_BAND):
                pts.append((s["start_time"], 1000 / v, f.get("ref_hr")))
        if not pts:
            return None
        change = None
        if len(pts) >= 4:
            x0 = datetime.fromisoformat(pts[0][0])
            xs = [(datetime.fromisoformat(t) - x0).total_seconds() / 86400 for t, _, _ in pts]
            slope = physio.linear_slope(xs, [p for _, p, _ in pts])
            change = round(-slope * 42, 1) if slope is not None else None  # s/km faster over 6 weeks
        return {"pace_s_per_km": round(median(p for _, p, _ in pts[-3:]), 1), "ref_hr": pts[-1][2],
                "change_s_per_km": change, "points": [{"day": t[:10], "value": round(p, 1)} for t, p, _ in pts]}

    if sport == "cycling":
        rides = [s for s in recent(90, lambda s: s.get("has_power")) if (s.get("features") or {}).get("ef")]
        last = rides[-1] if rides else None
        lf = (last or {}).get("features") or {}
        today_kg = weights.at(today.isoformat())
        ride_kg = weights.at(last["start_time"][:10]) if last else None
        efs = [s["features"]["ef"] for s in rides]
        change = round((efs[-1] - efs[0]) / efs[0] * 100, 1) if len(efs) >= 3 and efs[0] else None
        return {"w_per_beat": round(efs[-1], 2) if efs else None, "w_per_beat_change_pct": change,
                "ftp_wkg": round(ftp / today_kg, 2) if ftp and today_kg else None,
                "hr_wkg": round(lf["power_at_ref_hr"] / ride_kg, 2) if lf.get("power_at_ref_hr") and ride_kg else None,
                "ref_hr": lf.get("ref_hr"),
                "points": [{"day": s["start_time"][:10], "value": round(s["features"]["ef"], 3)} for s in rides]}
    if sport == "strength":
        return strength_status(recent(84, lambda s: True), today)
    return None


def strength_status(gym: list[dict], today: date) -> dict:
    """The gym card: how often (sessions and minutes, the last 6 weeks vs the 6 before), and, when
    weights are logged, how the estimated 1RM moved. Circuits without weights only get the first."""
    split = (today - timedelta(days=42)).isoformat()
    now = [s for s in gym if s["start_time"][:10] >= split]
    before = [s for s in gym if s["start_time"][:10] < split]
    weeks = [0] * 12
    for s in gym:
        weeks[min(11, (today - date.fromisoformat(s["start_time"][:10])).days // 7)] += 1

    # per exercise with 3+ weighted sessions in 6 weeks: e1RM slope over 6 weeks in % of its mean
    by_ex: dict[str, list[tuple[float, float]]] = {}
    for s in now:
        day = (date.fromisoformat(s["start_time"][:10]) - today).days
        for ex, d in ((s.get("features") or {}).get("exercises") or {}).items():
            if d.get("e1rm"):
                by_ex.setdefault(ex, []).append((day, d["e1rm"]))
    changes = []
    for pts in by_ex.values():
        slope = physio.linear_slope([p[0] for p in pts], [p[1] for p in pts]) if len(pts) >= 3 else None
        mean = sum(p[1] for p in pts) / len(pts)
        if slope is not None and mean:
            changes.append(slope * 42 / mean * 100)
    return {"sessions_6w": len(now), "sessions_prev_6w": len(before),
            "minutes_6w": round(sum(s.get("duration_s") or 0 for s in now) / 60),
            "e1rm_change_pct": round(median(changes), 1) if changes else None,
            "points": [{"day": (today - timedelta(weeks=11 - i)).isoformat(), "value": n}
                       for i, n in enumerate(reversed(weeks))]}


def ambient(conn: sqlite3.Connection, cfg: AppConfig, user_id: str) -> dict:
    sessions = user_sessions(conn, user_id)
    today = date.today()
    series = load_model.pmc(load_model.daily_loads(sessions), None, today) if sessions else []
    pmc_42 = series[-42:]
    # the wall's main card on the day of a workout: what it did ("What improved"); otherwise training form
    fitness_change_6w = round(series[-1]["fitness"] - series[-43]["fitness"], 1) if len(series) > 42 else None
    last = conn.execute(
        """SELECT s.id, s.start_time FROM verdicts v JOIN sessions s ON s.id = v.session_id
           WHERE s.user_id = ? ORDER BY s.start_time DESC LIMIT 1""", (user_id,)).fetchone()
    last_workout = None
    card = session_card(conn, last["id"], sessions) if last and _is_today(last["start_time"]) else None
    if card:
        v = card["verdict"]
        last_workout = {k: card[k] for k in ("id", "name", "sport", "session_type", "start_time", "improvements")}
        last_workout.update(verdict=v["verdict"], headline=v["headline"])
    health = health_series(conn, user_id, 42)
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
    if trends:
        prof = profile.stored(conn, user_id)
        weigh_ins = [dict(r) for r in conn.execute(
            "SELECT day, weight_kg FROM health_days WHERE user_id = ? AND weight_kg IS NOT NULL ORDER BY day", (user_id,))]
        weights = improvements.Weights(weigh_ins, (prof.get("weight_kg") or {}).get("value"))
        for sport in ("running", "cycling", "strength"):
            if sport in trends:
                trends[sport]["status"] = sport_status(sessions, sport, (prof.get("ftp") or {}).get("value"),
                                                       weights, today)
        if "running" in trends:
            trends["running"]["cadence"] = coach.running_cadence(sessions, today)

    recent = conn.execute(
        """SELECT s.id, s.name, s.sport, s.session_type, s.start_time, s.duration_s, s.distance_m, s.load,
                  v.verdict, v.headline FROM sessions s LEFT JOIN verdicts v ON v.session_id = s.id
           WHERE s.user_id = ? ORDER BY s.start_time DESC LIMIT 8""", (user_id,)).fetchall()
    vo2 = [{"day": r["day"], "value": r["vo2max"]} for r in conn.execute(
        "SELECT day, vo2max FROM health_days WHERE user_id = ? AND day >= ? AND vo2max > 0 ORDER BY day",
        (user_id, (today - timedelta(days=365)).isoformat()))]
    today_workout, upcoming = coach.planned(conn, user_id, sessions, today)
    readiness = coach.readiness(conn, user_id, today)
    streak = coach.week_streak(sessions, today)
    form_now = pmc_42[-1] if pmc_42 else None
    return {
        "user_id": user_id,
        "pmc": series[-182:],
        "form": form_now,
        # since this morning (all of today's training): today's row minus yesterday's
        "today_change": ({k: round(series[-1][k] - series[-2][k], 1) for k in ("fitness", "fatigue", "form")}
                         if len(series) > 1 else None),
        "fitness_change_6w": fitness_change_6w,
        "last_workout": last_workout,
        "health_latest": latest,
        "health_baseline": base,
        "health_series": health,
        "week": week_totals(0),
        "last_week": week_totals(1),
        "trends": trends,
        "recent": [dict(r) for r in recent],
        "vo2max": vo2,
        "sync": sync_info(conn, cfg, user_id),
        "readiness": readiness,
        "streak": streak,
        "sweet_spot": coach.sweet_spot(series, sessions, today),
        "today_workout": today_workout,
        "upcoming": upcoming,
        "plan_week": coach.plan_week(conn, user_id, sessions, today),
        "buddy": buddy.block(conn, user_id, readiness=readiness, health_latest=latest,
                             form=form_now["form"] if form_now else None, today_workout=today_workout,
                             last_workout=last_workout, streak=streak, sessions=sessions, today=today),
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
