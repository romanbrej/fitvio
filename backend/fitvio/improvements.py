"""'What improved' after an activity: fitness, performance vs your usual, VO2max and new bests.

Everything in real units ("8 s/km faster than usual", "+0.08 W/kg"), each with a tone:
improving / steady / declining, or best (★) for records.
"""
from __future__ import annotations

import bisect
import sqlite3
from datetime import date, timedelta

from . import profile
from .pipeline import performance_sessions, user_sessions

BEST_WINDOW_DAYS = 90
MIN_PRIOR = 3  # a "best in 90 days" needs at least this many earlier sessions to mean anything
NOUN = {"running": "run", "cycling": "ride", "swimming": "swim"}


def _item(kind, label, value_fmt, change_fmt, tone) -> dict:
    return {"kind": kind, "label": label, "value_fmt": value_fmt, "change_fmt": change_fmt, "tone": tone}


def _tone_z(z: float | None) -> str | None:
    if z is None:
        return None
    return "improving" if z >= 0.6 else "declining" if z <= -0.6 else "steady"


def _pace_km(speed: float) -> str:
    s = 1000 / speed
    return f"{int(s // 60)}:{int(round(s % 60)):02d} /km"


def _pace_100(sec: float) -> str:
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d} /100m"


def _vs_usual(tone: str | None, diff: int, unit: str, up: str, down: str) -> str:
    """"like usual" when steady or unchanged, else e.g. "8 s/km faster than usual" (diff > 0 → `up`)."""
    if tone == "steady" or diff == 0:
        return "like usual"
    return f"{abs(diff)}{f' {unit}' if unit else ''} {up if diff > 0 else down} than usual"


class Weights:
    """Body weight on a day: the last Garmin weigh-in on or before it, else the Garmin profile weight."""

    def __init__(self, health: list[dict], profile_kg: float | None):
        pts = sorted((h["day"], h["weight_kg"]) for h in health if h.get("weight_kg"))
        self.days = [d for d, _ in pts]
        self.kgs = [w for _, w in pts]
        self.profile_kg = profile_kg

    def at(self, day: str) -> float | None:
        i = bisect.bisect_right(self.days, day)
        return self.kgs[i - 1] if i else self.profile_kg


def fitness_item(trend: dict) -> dict | None:
    if not trend or trend.get("fitness_after") is None:
        return None
    gain = trend["fitness_after"] - (trend.get("fitness_before") or trend["fitness_after"])
    ramp = trend.get("ramp_7d")
    # every session adds a little — the weekly direction is the honest "did it go up" signal
    tone = None if ramp is None else "improving" if ramp >= 0.5 else "declining" if ramp <= -0.5 else "steady"
    text = f"{gain:+.1f} from this session"
    if ramp is not None:
        text += f" · {ramp:+.1f} this week"
    return _item("fitness", "Fitness", f"{trend['fitness_after']:.0f}", text, tone)


def delta_items(session: dict, deltas: list[dict], weight_kg: float | None) -> list[dict]:
    f = session.get("features") or {}
    ref = f.get("ref_hr")
    at = f"@{ref:.0f} bpm" if ref else "at fixed HR"
    out = []
    for d in deltas:
        v, base, tone = d.get("value"), d.get("baseline"), _tone_z(d.get("z"))
        if v is None or base is None:
            continue
        key = d["key"]
        if key in ("speed_at_ref_hr", "work_speed"):
            sec = round(1000 / base - 1000 / v)  # + = faster
            label = f"Pace {at}" if key == "speed_at_ref_hr" else "Rep pace"
            out.append(_item(key, label, _pace_km(v), _vs_usual(tone, sec, "s/km", "faster", "slower"), tone))
        elif key == "hr_recovery":
            text = _vs_usual(tone, round(v - base), "bpm", "more", "less")
            out.append(_item(key, "HR drop between reps", f"{v:.0f} bpm", text, tone))
        elif key == "rep_fade":
            diff = v - base  # + = more pace lost over the reps than usual
            text = "like usual" if tone == "steady" else f"{abs(diff):.1f} % {'more' if diff > 0 else 'less'} fade than usual"
            out.append(_item(key, "Pace held across reps", f"−{v:.1f} %" if v > 0 else "held", text, tone))
        elif key == "power_at_ref_hr":
            if weight_kg:
                diff = (v - base) / weight_kg
                text = "like usual" if tone == "steady" else f"{diff:+.2f} W/kg vs usual"
                out.append(_item(key, f"Power {at}", f"{v / weight_kg:.2f} W/kg", text, tone))
            else:
                out.append(_item(key, f"Power {at}", f"{v:.0f} W", f"{v - base:+.0f} W vs usual", tone))
        elif key == "decoupling":
            diff = v - base
            text = "like usual" if tone == "steady" else f"{'less' if diff < 0 else 'more'} than usual ({diff:+.1f} %)"
            out.append(_item(key, d["label"], f"{v:.1f} %", text, tone))
        elif key == "p300":
            out.append(_item(key, "Best 5 min", f"{v:.0f} W",
                             "like usual" if tone == "steady" else f"{v - base:+.0f} W vs usual", tone))
        elif key == "pace_100m_s":
            text = _vs_usual(tone, round(base - v), "s/100m", "faster", "slower")
            out.append(_item(key, "Pace", _pace_100(v), text, tone))
        elif key == "swolf":
            out.append(_item(key, "SWOLF", f"{v:.0f}", _vs_usual(tone, round(base - v), "", "better", "worse"), tone))
    if session["sport"] == "strength":
        lifts = [d for d in deltas if d.get("delta") is not None and d.get("value")]
        for d in sorted(lifts, key=lambda d: -abs(d.get("delta_pct") or 0))[:3]:
            out.append(_item("lift", d["label"], f"{d['value']:.1f} kg",
                             f"{d['delta']:+.1f} kg vs best of last {d['n']}", _tone_z(d.get("z"))))
    return out


def vo2max_item(session: dict, health: list[dict]) -> dict | None:
    col = {"running": "vo2max", "cycling": "vo2max_cycling"}.get(session["sport"])
    if not col:
        return None
    day = session["start_time"][:10]
    pts = sorted((h["day"], h[col]) for h in health if h.get(col))
    before = [v for d, v in pts if d < day]
    after = [v for d, v in pts if d >= day]
    if not before or not after:
        return None
    b, a = before[-1], after[0]
    if round(a - b, 1) == 0:
        return _item("vo2max", "VO₂max", f"{a:.1f}", "unchanged", "steady")
    return _item("vo2max", "VO₂max", f"{b:.1f} → {a:.1f}", f"{a - b:+.1f}", "improving" if a > b else "declining")


def best_items(session: dict, history: list[dict], reasons: list[str]) -> list[dict]:
    out = [_item("best", "New best", r.removeprefix("New "), "", "best")
           for r in reasons if r.startswith(("New all-time", "New personal record"))]
    sport = session["sport"]
    if sport not in NOUN:
        return out
    day = date.fromisoformat(session["start_time"][:10])
    lo = (day - timedelta(days=BEST_WINDOW_DAYS)).isoformat()
    prior = [h for h in history if h["sport"] == sport and lo <= h["start_time"] < session["start_time"]]
    if len(prior) < MIN_PRIOR:
        return out
    dist = session.get("distance_m")
    prev = [h.get("distance_m") or 0 for h in prior]
    if dist and dist > max(prev):
        km = f"{dist:.0f} m" if sport == "swimming" else f"{dist / 1000:.1f} km"
        out.append(_item("best", f"Longest {NOUN[sport]} in 90 days", km, "", "best"))
    f = session.get("features") or {}
    key = {"running": "speed_at_ref_hr", "cycling": "power_at_ref_hr"}.get(sport)
    if key:
        def val(s):
            g = s.get("features") or {}
            return (g.get("speed_at_ref_hr_adj") or g.get(key)) if sport == "running" else g.get(key)
        v, prev = val(session), [x for x in (val(h) for h in prior) if x]
        if v and len(prev) >= MIN_PRIOR and v > max(prev):
            what = "Fastest" if sport == "running" else "Most power"
            ref = f.get("ref_hr")
            out.append(_item("best", f"{what} at {ref:.0f} bpm in 90 days" if ref else f"{what} at fixed HR in 90 days",
                             _pace_km(v) if sport == "running" else f"{v:.0f} W", "", "best"))
    return out


def what_improved(conn: sqlite3.Connection, session: dict, sessions: list[dict] | None = None) -> list[dict]:
    """`sessions`: the person's sessions if the caller already loaded them (saves reading them twice)."""
    v = session.get("verdict") or {}
    if v.get("verdict") == "excluded":  # left out as bad data: it shows no gains, bests or comparisons
        return []
    uid = session["user_id"]
    health = [dict(r) for r in conn.execute(
        "SELECT day, vo2max, vo2max_cycling, weight_kg FROM health_days WHERE user_id = ? ORDER BY day", (uid,))]
    stored = profile.stored(conn, uid).get("weight_kg") or {}
    weight = Weights(health, stored.get("value")).at(session["start_time"][:10])
    items = [fitness_item(v.get("trend") or {})]
    history = [h for h in performance_sessions(sessions if sessions is not None else user_sessions(conn, uid))
               if h["id"] != session["id"]]
    items += delta_items(session, v.get("deltas") or [], weight)
    items.append(vo2max_item(session, health))
    items += best_items(session, history, v.get("reasons") or [])
    # good news first: improvements and bests, then steady, then declining (stable within each group)
    order = {"improving": 0, "best": 0, "steady": 1, None: 1, "declining": 2}
    return sorted((i for i in items if i), key=lambda i: order.get(i["tone"], 1))


def attach(conn: sqlite3.Connection, card: dict | None, sessions: list[dict] | None = None) -> dict | None:
    if card and card.get("verdict"):
        card["improvements"] = what_improved(conn, card, sessions)
    return card

