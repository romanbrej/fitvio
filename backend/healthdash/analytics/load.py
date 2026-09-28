"""Fitness / fatigue / form (CTL / ATL / TSB) from daily TRIMP totals."""
from __future__ import annotations

import math
from datetime import date, timedelta

CTL_DAYS = 42
ATL_DAYS = 7


def daily_loads(sessions: list[dict]) -> dict[date, float]:
    out: dict[date, float] = {}
    for s in sessions:
        d = date.fromisoformat(s["start_time"][:10])
        out[d] = out.get(d, 0.0) + (s.get("load") or 0.0)
    return out


def pmc(loads: dict[date, float], start: date | None = None, end: date | None = None) -> list[dict]:
    """Performance-management series: one row per day with fitness, fatigue, form.

    Form for a day is yesterday's fitness minus yesterday's fatigue, i.e. how fresh you
    were going *into* that day.
    """
    if not loads:
        return []
    start = start or min(loads)
    end = end or max(max(loads), date.today())
    kc, ka = 1 - math.exp(-1 / CTL_DAYS), 1 - math.exp(-1 / ATL_DAYS)
    ctl = atl = 0.0
    out = []
    d = start
    while d <= end:
        form = ctl - atl
        load = loads.get(d, 0.0)
        ctl += (load - ctl) * kc
        atl += (load - atl) * ka
        out.append({"day": d.isoformat(), "load": round(load, 1), "fitness": round(ctl, 1),
                    "fatigue": round(atl, 1), "form": round(form, 1)})
        d += timedelta(days=1)
    return out


def impact_of(session: dict, all_sessions: list[dict]) -> dict:
    """Fitness/fatigue/form on the session's day, with and without this session."""
    day = date.fromisoformat(session["start_time"][:10])
    with_s = daily_loads(all_sessions)
    without = dict(with_s)
    without[day] = without.get(day, 0.0) - (session.get("load") or 0.0)
    start = min(with_s) if with_s else day
    a = pmc(with_s, start, day)[-1]
    b = pmc(without, start, day)[-1]
    ramp = None
    series = pmc(with_s, start, day)
    if len(series) > 7:
        ramp = round(series[-1]["fitness"] - series[-8]["fitness"], 1)
    return {
        "fitness_before": b["fitness"], "fitness_after": a["fitness"],
        "fatigue_before": b["fatigue"], "fatigue_after": a["fatigue"],
        "form_today": a["form"],  # form going into the day (unchanged by today's session)
        "form_tomorrow": round(a["fitness"] - a["fatigue"], 1),
        "ramp_7d": ramp,
        "load": session.get("load"),
    }
