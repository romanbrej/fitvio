"""What the wall shows right now, and the read models behind the API."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from statistics import median

from . import buddy, coach, db, improvements, profile, units
from .analytics import load as load_model
from .analytics import physio
from .config import AppConfig
from .models.sports import model_for
from .pipeline import performance_sessions, user_sessions


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
           WHERE s.start_time >= ? AND v.verdict != 'excluded'
           ORDER BY s.start_time DESC""", (cutoff,)).fetchall()
    people = {u.id for u in cfg.users}  # not someone removed whose data is still being deleted
    for r in rows:
        if r["user_id"] not in people:
            continue
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


def session_card(conn: sqlite3.Connection, session_id: str, sessions: list[dict] | None = None,
                 u: str | None = None) -> dict | None:
    """The session with its verdict and "What improved", their text in `u` (metric or imperial; default: the
    person's choice). `sessions`: the person's sessions, if already loaded."""
    s = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())
    if not s:
        return None
    u = u or units.for_user(conn, s["user_id"])
    v = db.row_to_dict(conn.execute("SELECT * FROM verdicts WHERE session_id = ?", (session_id,)).fetchone())
    s["verdict"] = model_for(s["sport"]).render(v, s, u) if v else None
    return improvements.attach(conn, s, sessions, u)


def session_detail(conn: sqlite3.Connection, session_id: str, u: str | None = None) -> dict | None:
    s = session_card(conn, session_id, u=u)
    if not s:
        return None
    st = conn.execute("SELECT data FROM session_streams WHERE session_id = ?", (session_id,)).fetchone()
    s["streams"] = db.row_to_dict(st)["data"] if st else None
    s["sets"] = [dict(r) for r in conn.execute(
        "SELECT * FROM exercise_sets WHERE session_id = ? ORDER BY set_index", (session_id,))]
    s["baseline_sessions"] = _sessions_by_id(conn, (s["verdict"] or {}).get("baseline_ids") or [])
    s["excluded_from_baseline"] = conn.execute(
        "SELECT 1 FROM baseline_exclusions WHERE session_id = ?", (session_id,)).fetchone() is not None
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
    from .pipeline import reprocess_key
    from .sync.activity_watch import paused_for_login

    progress = db.get_state(conn, reprocess_key(user_id))
    done, _, total = (progress or "").partition("/")
    return {"last_success": last, "last_attempt": r.get("last_attempt"), "last_error": r.get("last_error"),
            "age_hours": round(age_h, 1) if age_h is not None else None, "stale": stale,
            # the auto-sync check found the cached Garmin login expired (it never uses the password itself)
            "login_expired": paused_for_login(conn, user_id),
            # history being reprocessed after an update: {done, total} activities, newest first
            "reprocessing": {"done": int(done), "total": int(total)} if done.isdigit() and total.isdigit() else None}


def health_series(conn: sqlite3.Connection, user_id: str, days: int) -> list[dict]:
    """Daily health rows (sleep, HRV, resting HR …) of the last `days` days, oldest first."""
    d0 = (date.today() - timedelta(days=days)).isoformat()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM health_days WHERE user_id = ? AND day >= ? ORDER BY day", (user_id, d0))]


def _is_today(start_time: str, now: datetime | None = None) -> bool:
    """The 'Last workout' card is only for the day of the workout; at midnight the wall resets."""
    return start_time[:10] == (now or _now()).date().isoformat()


HEADLINE_RUNS = 6        # the pace headline: the newest runs, so it moves only when a run comes in
HEADLINE_MIN_S = 600.0   # under 10 min at the reference HR in those runs → older runs are added
HEADLINE_RIDES = 3       # the power-per-beat headline: the newest rides with power (rarer than runs)
RUN_WEIGHT_CAP_S = 1200.0  # one long run counts at most 20 min, so it can't outvote the rest


PERIOD_DAYS = (14, 28, 42, 56, 91, 182, 365)  # the periods a person can pick ("Am I improving?" over …)
DEFAULT_DAYS = {"running": 42, "cycling": 91, "strength": 42}
MIN_RUNS, MIN_RIDES = 4, 3
TREND_PERIOD = "trend_period:{user_id}"  # the period this person last picked (days), for every device


def trend_period(conn: sqlite3.Connection, user_id: str) -> int | None:
    v = db.get_state(conn, TREND_PERIOD.format(user_id=user_id))
    return int(v) if v and v.isdigit() and int(v) in PERIOD_DAYS else None


def set_trend_period(conn: sqlite3.Connection, user_id: str, days: int) -> None:
    db.set_state(conn, TREND_PERIOD.format(user_id=user_id), str(days))


def sport_status(sessions: list[dict], sport: str, ftp: float | None, weights: improvements.Weights,
                 today: date) -> dict | None:
    """The sport card's headline in real units, computed live from the sessions.

    running: pace held at the reference HR (grade and weather adjusted, like every comparison) over the
             newest outdoor runs, older ones fading out, and how many s/km it changed over the 6 weeks up
             to the newest run (+ = faster). Both are counted from the newest run, not from today, so
             the numbers change when a run comes in and never just because a day passed. The pace is the
             "now" of every period too.
    cycling: power per heartbeat (heat adjusted) over the newest rides with power, older ones fading
             out, and how it moved over 3 months; it's the "now" of every period too. Plus W/kg of FTP
             and of the newest ride's power at the reference HR.
    strength: sessions per 6 weeks vs the 6 before, and the e1RM trend when weights are logged.
    Sessions someone excluded (bad data) count for how often they trained, never for a performance number.
    The same change over other lengths is in `period_trend`.
    """
    perf = performance_sessions(sessions)
    if sport == "running":
        pts = _run_points(perf, DEFAULT_DAYS["running"])
        if not pts:
            return None
        pace, n_head = _faded_mean(_newest_first(_run_items(pts)), HEADLINE_RUNS, HEADLINE_MIN_S)
        trend = period_trend(sessions, "running", DEFAULT_DAYS["running"], today, perf)
        lo = (_newest_day(perf, _measured_run) - timedelta(days=DEFAULT_DAYS["running"])).isoformat()
        runs_total = sum(1 for s in perf if s["sport"] == "running" and not s.get("indoor")
                         and s["start_time"][:10] >= lo)
        return {"pace_s_per_km": round(pace, 1),
                "ref_hr": pts[-1][4], "headline_runs": n_head,
                "change_s_per_km": trend["change"],         # weather adjusted, like every comparison
                "runs": len(pts), "runs_total": runs_total,
                "points": [{"day": p[0][:10], "value": round(p[2], 1)} for p in pts]}
    if sport == "cycling":
        rides = _ride_points(perf, DEFAULT_DAYS["cycling"])
        last = rides[-1] if rides else None
        lf = (last or {}).get("features") or {}
        today_kg = weights.at(today.isoformat())
        ride_kg = weights.at(last["start_time"][:10]) if last else None
        trend = period_trend(sessions, "cycling", DEFAULT_DAYS["cycling"], today, perf)
        card = _faded_mean(_newest_first(_ride_items(rides)), HEADLINE_RIDES) if rides else (None, 0)
        return {"w_per_beat": round(card[0], 2) if rides else None, "headline_rides": card[1],
                "w_per_beat_change_pct": trend["change"],
                "ftp_wkg": round(ftp / today_kg, 2) if ftp and today_kg else None,
                "hr_wkg": round(lf["power_at_ref_hr"] / ride_kg, 2) if lf.get("power_at_ref_hr") and ride_kg else None,
                "ref_hr": lf.get("ref_hr"),
                "points": [{"day": s["start_time"][:10], "value": round(_ride_value(s), 3)} for s in rides]}
    if sport == "strength":
        return strength_status(sessions, today)
    return None


def period_trend(sessions: list[dict], sport: str, days: int, today: date,
                 perf: list[dict] | None = None) -> dict:
    """How a sport moved over the last `days`: {change, n, points} (change None with too few
    sessions). running: s/km faster at the reference HR (+ = faster); cycling: % more power per beat;
    strength: % e1RM, plus how many sessions vs the same length before. Runs and rides count back from
    the newest one, so a period never empties just because days passed; strength counts from today.
    running and cycling: now is the card's number in every period, then the card as it was on the period's
    first day (the period's oldest sessions when nothing came before), so both are values you reached; a
    straight line through every session would land off both ends of a dip."""
    perf = performance_sessions(sessions) if perf is None else perf
    if sport == "running":
        card = DEFAULT_DAYS["running"]
        pts = _run_items(_run_points(perf, days))
        then, now = _ends(pts, _run_items(_run_points(perf, card)), _run_items(_run_points(perf, days + card)),
                          days, HEADLINE_RUNS, HEADLINE_MIN_S, MIN_RUNS)
        then, now = _round(then, 1), _round(now, 1)
        return {"change": round(then - now, 1) if then is not None else None, "n": len(pts),
                "now": now, "then": then,
                # weather-adjusted like then and now, so a hot or windy run sits where it is judged
                "points": [{"day": t[:10], "value": round(v, 1), "trend": _round(x, 1)}
                           for (t, v, _), x in zip(pts, _line(pts, then, now, days))]}
    if sport == "cycling":
        card = DEFAULT_DAYS["cycling"]
        rides = _ride_items(_ride_points(perf, days))
        then, now = _ends(rides, _ride_items(_ride_points(perf, card)), _ride_items(_ride_points(perf, days + card)),
                          days, HEADLINE_RIDES, 0.0, MIN_RIDES)
        then, now = _round(then, 3), _round(now, 3)
        return {"change": round((now - then) / then * 100, 1) if then else None, "n": len(rides),
                "now": now, "then": then,
                "points": [{"day": t[:10], "value": round(v, 3),  # heat adjusted, like then and now
                            "trend": _round(x, 3)} for (t, v, _), x in zip(rides, _line(rides, then, now, days))]}
    if sport == "strength":
        st = strength_status(sessions, today, days)
        return {"change": st["e1rm_change_pct"], "n": st["sessions"],
                "n_prev": st["sessions_prev"], "minutes": st["minutes"], "now": None, "then": None,
                "points": st["points"]}
    return {"change": None, "n": 0, "now": None, "then": None, "points": []}


def _faded_mean(items: list[tuple], n: int, min_weight: float = 0.0) -> tuple[float, int]:
    """(mean, items counted) of the first `n` (start, value, weight) items, each counting by its weight and
    fading by position, adding more while their weight holds under `min_weight`. Newest first, it's a card's
    number: the session that leaves when a new one comes in barely counts."""
    head = []
    for rank, (_, v, w) in enumerate(items):
        if rank >= n and sum(h[1] for h in head) >= min_weight:
            break
        head.append((v, w, (n - min(rank, n - 1)) / n))
    return sum(v * w * f for v, w, f in head) / sum(w * f for _, w, f in head), len(head)


def _ends(period: list[tuple], card: list[tuple], wide: list[tuple], days: int, n: int, min_weight: float,
          min_count: int) -> tuple[float | None, float | None]:
    """(then, now) of a period of (start, value, weight) items, oldest first. now: the card (its newest `n`
    items of `card`); then: the card on the period's first day, from `wide` (the card's window further
    back), or the period's oldest items when nothing came before. then is None with under `min_count`."""
    now = _faded_mean(_newest_first(card), n, min_weight)[0] if period and card else None
    if len(period) < min_count or now is None:
        return None, now
    first = (date.fromisoformat(period[-1][0][:10]) - timedelta(days=days)).isoformat()
    before = [x for x in wide if x[0][:10] <= first]
    if before:
        return _faded_mean(_newest_first(before), n, min_weight)[0], now
    # nothing that early (a break, or not a year of data yet): the period's oldest, at most half of them
    return _faded_mean(period, max(1, min(n, len(period) // 2)), min_weight)[0], now


def _line(period: list[tuple], then: float | None, now: float | None, days: int) -> list[float | None]:
    """The straight line from then (a period before the newest item) to now at each item, like the wall chart."""
    if then is None or now is None:
        return [None] * len(period)
    end = datetime.fromisoformat(period[-1][0])
    return [now + (then - now) * (end - datetime.fromisoformat(t)).total_seconds() / 86400 / days
            for t, _, _ in period]


def _newest_first(items: list[tuple]) -> list[tuple]:
    return list(reversed(items))


def _round(v: float | None, digits: int) -> float | None:
    return None if v is None else round(v, digits)


def _run_items(pts: list[tuple]) -> list[tuple]:
    """(start, weather-adjusted pace, seconds at the reference HR) of `_run_points`."""
    return [(p[0], p[2], p[3]) for p in pts]


def _ride_value(s: dict) -> float:
    return s["features"].get("ef_adj") or s["features"]["ef"]  # heat adjusted


def _ride_items(rides: list[dict]) -> list[tuple]:
    """(start, heat-adjusted power per beat, 1) of `_ride_points`: every ride counts the same."""
    return [(s["start_time"], _ride_value(s), 1.0) for s in rides]


def _measured_run(s: dict) -> bool:
    """An outdoor run with steady time at the reference HR (features.py): every one counts."""
    f = s.get("features") or {}
    return s["sport"] == "running" and not s.get("indoor") and bool(f.get("speed_at_ref_hr")) \
        and bool(f.get("ref_hr_secs"))


def _ride_with_power(s: dict) -> bool:
    return s["sport"] == "cycling" and bool(s.get("has_power")) and bool((s.get("features") or {}).get("ef"))


def _newest_day(perf: list[dict], keep) -> date | None:
    days = [date.fromisoformat(s["start_time"][:10]) for s in perf if keep(s)]
    return max(days) if days else None


def _within(perf: list[dict], keep, days: int) -> list[dict]:
    """The sessions `keep` takes from the `days` up to the newest of them, oldest first."""
    newest = _newest_day(perf, keep)
    if newest is None:
        return []
    lo = (newest - timedelta(days=days)).isoformat()
    return sorted((s for s in perf if keep(s) and s["start_time"][:10] >= lo), key=lambda s: s["start_time"])


def _run_points(perf: list[dict], days: int) -> list[tuple]:
    """(start, pace s/km as run, weather-adjusted pace, seconds counted, ref HR) of the measured runs."""
    out = []
    for s in _within(perf, _measured_run, days):
        f = s["features"]
        v = f["speed_at_ref_hr"]
        out.append((s["start_time"], 1000 / v, 1000 / (f.get("speed_at_ref_hr_adj") or v),
                    min(f["ref_hr_secs"], RUN_WEIGHT_CAP_S), f.get("ref_hr")))
    return out


def _ride_points(perf: list[dict], days: int) -> list[dict]:
    return _within(perf, _ride_with_power, days)


def strength_status(sessions: list[dict], today: date, days: int = 42) -> dict:
    """The gym card: how often (sessions and minutes, the last `days` vs the same length before), and,
    when weights are logged, how the estimated 1RM moved. Circuits without weights only get the first.
    Excluded sessions count for how often, never for the e1RM."""
    split = today - timedelta(days=days)
    gym = [s for s in sessions if s["sport"] == "strength"
           and (split - timedelta(days=days)).isoformat() <= s["start_time"][:10]]
    now = [s for s in gym if s["start_time"][:10] >= split.isoformat()]
    before = [s for s in gym if s["start_time"][:10] < split.isoformat()]
    n_weeks = max(4, -(-days // 7)) * 2  # bars over both halves
    weeks = [0] * n_weeks
    for s in gym:
        age = (today - date.fromisoformat(s["start_time"][:10])).days // 7
        if age < n_weeks:
            weeks[age] += 1

    # per exercise with 3+ weighted sessions in the period: e1RM slope over the period in % of its mean
    by_ex: dict[str, list[tuple[float, float]]] = {}
    for s in performance_sessions(now):
        day = (date.fromisoformat(s["start_time"][:10]) - today).days
        for ex, d in ((s.get("features") or {}).get("exercises") or {}).items():
            if d.get("e1rm"):
                by_ex.setdefault(ex, []).append((day, d["e1rm"]))
    changes = []
    for pts in by_ex.values():
        slope = physio.linear_slope([p[0] for p in pts], [p[1] for p in pts]) if len(pts) >= 3 else None
        mean = sum(p[1] for p in pts) / len(pts)
        if slope is not None and mean:
            changes.append(slope * days / mean * 100)
    minutes = round(sum(s.get("duration_s") or 0 for s in now) / 60)
    return {"sessions": len(now), "sessions_prev": len(before), "minutes": minutes,
            "sessions_6w": len(now), "sessions_prev_6w": len(before), "minutes_6w": minutes,  # the wall card (days=42)
            "e1rm_change_pct": round(median(changes), 1) if changes else None,
            "points": [{"day": (today - timedelta(weeks=n_weeks - 1 - i)).isoformat(), "value": n}
                       for i, n in enumerate(reversed(weeks))]}


def ambient(conn: sqlite3.Connection, cfg: AppConfig, user_id: str, u: str | None = None) -> dict:
    """`u`: metric or imperial for the text in it (default: the person's choice)."""
    u = u or units.for_user(conn, user_id)
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
    card = session_card(conn, last["id"], sessions, u) if last and _is_today(last["start_time"]) else None
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
               WHERE s.user_id = ? AND s.sport = ? AND v.verdict != 'excluded'
               ORDER BY s.start_time DESC LIMIT 1""", (user_id, sport)).fetchone()
        if r:
            t = db.row_to_dict(r)
            trends[sport] = {"last_session": t["id"], "last_time": t["start_time"], "last_verdict": t["verdict"],
                             "metric": model_for(sport).primary_label() or t["trend"].get("trend_metric"), "pct_per_week": t["trend"].get("trend_pct_per_week"),
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
                perf = performance_sessions(sessions)
                trends[sport]["periods"] = {str(n): period_trend(sessions, sport, n, today, perf) for n in PERIOD_DAYS}
        if "running" in trends:
            trends["running"]["cadence"] = coach.running_cadence(performance_sessions(sessions), today)

    recent = conn.execute(
        """SELECT s.id, s.name, s.sport, s.session_type, s.start_time, s.duration_s, s.distance_m, s.load,
                  v.verdict, v.headline FROM sessions s LEFT JOIN verdicts v ON v.session_id = s.id
           WHERE s.user_id = ? ORDER BY s.start_time DESC LIMIT 8""", (user_id,)).fetchall()
    vo2 = [{"day": r["day"], "value": r["vo2max"]} for r in conn.execute(
        "SELECT day, vo2max FROM health_days WHERE user_id = ? AND day >= ? AND vo2max > 0 ORDER BY day",
        (user_id, (today - timedelta(days=365)).isoformat()))]
    today_workout, upcoming = coach.planned(conn, user_id, sessions, today)
    form_now = pmc_42[-1] if pmc_42 else None
    try:
        source = cfg.user(user_id).source
    except KeyError:
        source = None
    readiness = coach.readiness(conn, user_id, today)
    if readiness is None and source == "intervals":  # no Garmin readiness from Intervals.icu: Fitvio's estimate
        readiness = coach.estimate_readiness(latest, base, form_now["form"] if form_now else None, today)
    streak = coach.week_streak(sessions, today)
    return {
        "user_id": user_id,
        "units": u,
        "source": source,
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
        "trend_period": trend_period(conn, user_id),  # null: each sport's own default
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
