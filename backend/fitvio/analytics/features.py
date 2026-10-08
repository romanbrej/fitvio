"""Turn a ParsedActivity into a flat feature dict + session row + chart streams."""
from __future__ import annotations

import math
import re
from statistics import median, pstdev

from ..activity import ParsedActivity
from ..config import UserConfig
from . import physio


# Workout-name keywords (German + English), checked in this order: the planned workout says what the
# session was meant to be, which HR alone can't tell (a "Basis" run in warm weather looks like tempo).
NAME_TYPES = [
    ("intervals", re.compile(r"\bvo2|\banaerob|\bintervall?|\bfartlek|\bhügel|\bhill|\bberg(lauf|sprints?)?\b|\bsprint"
                             r"|\b\d+\s*[x×]\s*\d+")),
    ("tempo", re.compile(r"\btempo|\bschwelle|\bthreshold|\bsweet ?spot")),
    ("long", re.compile(r"\blong\b|\blongrun|\blang(e|er)?\b|\blanglauf")),
    ("easy", re.compile(r"\bbasis|\bbase\b|\bgrundlage|\bga ?1\b|\beasy|\blocker|\brecovery|\bregeneration"
                        r"|\breko\b|\berholung|\bendurance|\bdauerlauf")),
]
LONG_THRESHOLD_S = {"running": 75 * 60, "cycling": 150 * 60, "swimming": 60 * 60}


def type_from_name(name: str | None) -> str | None:
    name = (name or "").lower()
    return next((t for t, rx in NAME_TYPES if rx.search(name)), None)


def workout_key(name: str | None) -> str | None:
    """The workout part of a Garmin name ("City - VO2max" → "vo2max"), to compare like with like."""
    if not name:
        return None
    return name.rsplit(" - ", 1)[-1].strip().lower() or None


def classify_session(act: ParsedActivity, zones: list[float], lap_speed_cv: float | None,
                     lthr: float | None = None, steady_hr: float | None = None) -> str:
    if act.sport == "strength":
        return "strength"
    if act.sport not in {"running", "cycling", "swimming"}:
        return "other"
    name = (act.name or "").lower()
    if any(w in name for w in ("race", "wettkampf", "parkrun", "marathon", "10k", "5k", "time trial", "tt ")):
        return "race"
    is_long = act.duration_s >= LONG_THRESHOLD_S[act.sport]
    by_name = type_from_name(name)
    if by_name:
        return "long" if by_name == "easy" and is_long else by_name
    hard = zones[3] + zones[4]
    if lap_speed_cv is not None and lap_speed_cv > 0.15 and hard > 0.12:
        return "intervals"
    if act.sport == "running" and lthr and steady_hr:
        # threshold-based (Friel): below ~90 % of LTHR is aerobic endurance, above it tempo/threshold
        if steady_hr >= 0.90 * lthr:
            return "tempo"
    elif hard > 0.35 or zones[2] + hard > 0.55:
        return "tempo"
    return "long" if is_long else "easy"


def _lap_speed_cv(act: ParsedActivity) -> float | None:
    speeds = [lap.avg_speed for lap in act.laps if lap.avg_speed and lap.duration_s >= 30]
    if len(speeds) < 4:
        return None
    m = sum(speeds) / len(speeds)
    return pstdev(speeds) / m if m else None


def ref_hr(user: UserConfig) -> float:
    """Reference HR for 'pace at fixed HR': ~70 % of HR reserve (upper endurance zone)."""
    return round(user.rest_hr + 0.7 * (user.max_hr - user.rest_hr))


def ref_hr_band(user: UserConfig) -> tuple[float, float]:
    """bpm below / above the reference HR that still count as "at" it: the upper part of zone 2
    (66.5–72 % of HR reserve), so it scales with each person's resting and max HR."""
    reserve = user.max_hr - user.rest_hr
    return round(0.035 * reserve), round(0.02 * reserve)  # whole bpm: HR comes in whole beats


def compute_features(act: ParsedActivity, user: UserConfig) -> dict:
    recs = act.records
    zones = physio.zone_distribution(recs, user.max_hr, user.rest_hr)
    f: dict = {"zones": [round(z, 3) for z in zones]}
    steady = physio.steady_slice(recs)
    lap_cv = _lap_speed_cv(act)
    session_type = classify_session(act, zones, lap_cv, user.lthr, physio.avg_hr(steady))
    f["lap_speed_cv"] = lap_cv
    f["workout_key"] = workout_key(act.name)

    if act.sport == "running":
        gap_all = physio.grade_adjusted_speeds(recs)
        gap = gap_all[len(recs) - len(steady):]
        ef = physio.efficiency_factor(steady, gap)
        w = act.weather or {}
        heat_pct = 0.0 if act.indoor else physio.heat_adjustment(w.get("temp_c"), w.get("dew_point_c"),
                                                                 act.heat_acclimation)
        # pace you actually held at the reference HR (any kind of run), not a fit extrapolated to it
        v_ref, ref_secs = physio.steady_speed_at_hr(recs, gap_all, ref_hr(user), *ref_hr_band(user)) or (None, None)
        f.update({
            "speed_at_ref_hr_adj": v_ref * (1 + heat_pct / 100) if v_ref else None,  # wall progress: pace at same HR
            "ef": ef,                                      # grade-adjusted m/min per beat
            "ef_adj": ef * (1 + heat_pct / 100) if ef else None,  # also heat/humidity-normalised
            "decoupling": physio.decoupling(steady, gap),
            "speed_at_ref_hr": v_ref,
            "ref_hr_secs": round(ref_secs) if ref_secs else None,
            "ref_hr": ref_hr(user),
            "avg_speed": act.distance_m / act.duration_s if act.distance_m and act.duration_s else None,
            "gap_speed": (sum(s for s in gap if s) / max(1, sum(1 for s in gap if s))) if gap else None,
            "avg_cadence": _avg([r.cadence for r in recs]),
            "heat_adj_pct": heat_pct,
        })
        if session_type == "intervals":
            f.update(physio.interval_reps(act.laps) or {})
    elif act.sport == "cycling":
        if act.has_power:
            p1 = physio.power_series_1hz(recs)
            np_ = physio.normalized_power(p1)
            curve = physio.power_curve(p1)
            ftp = user.ftp or (curve["1200"] * 0.95 if "1200" in curve else None)
            f.update({
                "avg_power": _avg([r.power for r in recs]),
                "np": np_,
                "ef": physio.efficiency_factor(steady, use_power=True),   # W per beat
                "power_at_ref_hr": physio.speed_at_hr(steady, [r.power for r in steady], ref_hr(user)),
                "ref_hr": ref_hr(user),
                "decoupling": physio.decoupling(steady, use_power=True),
                "power_curve": curve,
                "eftp": curve["1200"] * 0.95 if "1200" in curve else None,
                "intensity_factor": np_ / ftp if np_ and ftp else None,
            })
        else:
            f.update({"avg_speed": act.distance_m / act.duration_s if act.distance_m and act.duration_s else None})
    elif act.sport == "swimming":
        active = [ln for ln in act.lengths if ln.active and ln.duration_s > 0]
        pool = act.pool_length_m or 25.0
        if active:
            moving_s = sum(ln.duration_s for ln in active)
            f["pace_100m_s"] = moving_s / (len(active) * pool) * 100
            swolf = [ln.duration_s + ln.strokes for ln in active if ln.strokes]
            f["swolf"] = median(swolf) if swolf else None
            strokes: dict[str, int] = {}
            for ln in active:
                strokes[ln.stroke_type or "unknown"] = strokes.get(ln.stroke_type or "unknown", 0) + 1
            f["main_stroke"] = max(strokes, key=strokes.get)
            f["lengths"] = len(active)
        elif act.distance_m and act.duration_s:
            f["pace_100m_s"] = act.duration_s / act.distance_m * 100
    elif act.sport == "strength":
        per_ex: dict[str, dict] = {}
        for s in act.sets:
            e1 = physio.epley_1rm(s.weight_kg, s.reps)
            d = per_ex.setdefault(s.exercise, {"label": act.exercise_labels.get(s.exercise, s.exercise.replace("_", " ").title()), "sets": 0, "reps": 0, "volume": 0.0, "e1rm": None, "top_kg": None})
            d["sets"] += 1
            d["reps"] += s.reps or 0
            d["volume"] += (s.reps or 0) * (s.weight_kg or 0)
            if e1 and (d["e1rm"] is None or e1 > d["e1rm"]):
                d["e1rm"] = round(e1, 1)
            if s.weight_kg and (d["top_kg"] is None or s.weight_kg > d["top_kg"]):
                d["top_kg"] = s.weight_kg
        f["exercises"] = per_ex
        f["total_volume"] = round(sum(d["volume"] for d in per_ex.values()), 1)
        f["total_sets"] = sum(d["sets"] for d in per_ex.values())

    if act.weather:
        f["weather"] = act.weather
    if act.heat_acclimation is not None:
        f["heat_acclimation"] = act.heat_acclimation
    load = physio.trimp(recs, user.rest_hr, user.max_hr, user.sex, act.avg_hr, act.duration_s)
    return {"features": _round(f), "session_type": session_type, "load": round(load, 1)}


def build_streams(act: ParsedActivity, step_s: float = 5.0) -> dict:
    """Downsample to one point per step for the detail charts."""
    out = {"t": [], "hr": [], "speed": [], "power": [], "altitude": []}
    next_t = 0.0
    for r in act.records:
        if r.t < next_t:
            continue
        next_t = r.t + step_s
        out["t"].append(round(r.t))
        out["hr"].append(r.hr)
        out["speed"].append(round(r.speed, 2) if r.speed is not None else None)
        out["power"].append(r.power)
        out["altitude"].append(round(r.altitude, 1) if r.altitude is not None else None)
    for k in ("power", "altitude", "speed", "hr"):
        if all(v is None for v in out[k]):
            out[k] = None
    out["laps"] = [
        {"start_s": lap.start_s, "duration_s": lap.duration_s, "distance_m": lap.distance_m,
         "avg_hr": lap.avg_hr, "avg_speed": lap.avg_speed, "avg_power": lap.avg_power}
        for lap in act.laps
    ]
    return out


def _avg(values) -> float | None:
    vals = [v for v in values if v]
    return sum(vals) / len(vals) if vals else None


def _round(obj):
    if isinstance(obj, float):
        return round(obj, 4) if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj
