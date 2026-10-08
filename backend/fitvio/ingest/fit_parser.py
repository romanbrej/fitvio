"""Parse a Garmin activity .FIT file with fitdecode.

GarminDB's activity_records table has no power, swim lengths or strength sets,
so we read those straight from the cached FIT file.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import fitdecode
from fitdecode.profile import FIELD_TYPES

from ..activity import ExerciseSet, Lap, Record, SwimLength, plausible_temp


def _get(frame, *names):
    for n in names:
        if frame.has_field(n):
            v = frame.get_value(n)
            if v is not None:
                return v
    return None


def _num(v):
    """A finite number or None. A FIT file declares its own field types, so a float32 field can hold inf."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        f = float(v)
        return f if math.isfinite(f) else None
    return None


def _readable(name: str) -> str:
    """'single_leg_hip_raise' -> 'Single leg hip raise'."""
    return name.replace("_", " ").capitalize()


def exercise_key(category, subtype) -> tuple[str, str]:
    """(stable key, display label) for a strength set, e.g. ('plank.43', 'Plank').

    Garmin writes the category as an array, which fitdecode leaves as raw numbers, so numbers and
    names both go through the FIT profile and give the same key. Categories are broad ('squat'
    covers goblet and back squat), so the numeric variant is part of the key and names the label."""
    if isinstance(category, (list, tuple)):
        category = category[0] if category else None
    if isinstance(subtype, (list, tuple)):
        subtype = subtype[0] if subtype else None
    if isinstance(category, int):
        category = FIELD_TYPES["exercise_category"].enum.get(category)
    cat = str(category) if category is not None else "unknown"
    if cat == "unknown" or cat.isdigit():
        # custom exercises arrive as 'unknown': the subtype keeps two of them apart
        return (f"unknown.{subtype}", "Exercise") if isinstance(subtype, int) else ("unknown", "Exercise")
    names = FIELD_TYPES.get(f"{cat}_exercise_name")
    name = names.enum.get(subtype) if names is not None and isinstance(subtype, int) else None
    label = _readable(name if name else cat)
    if isinstance(subtype, int):
        return f"{cat}.{subtype}", label
    return cat, label


def parse_fit(path: str | Path) -> dict:
    records: list[Record] = []
    laps: list[Lap] = []
    lengths: list[SwimLength] = []
    sets: list[ExerciseSet] = []
    labels: dict[str, str] = {}
    session: dict = {}
    t0: datetime | None = None

    with fitdecode.FitReader(str(path)) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            name = frame.name
            if name == "record":
                ts = _get(frame, "timestamp")
                if ts is None:
                    continue
                t0 = t0 or ts
                records.append(Record(
                    t=(ts - t0).total_seconds(),
                    hr=_num(_get(frame, "heart_rate")),
                    speed=_num(_get(frame, "enhanced_speed", "speed")),
                    distance=_num(_get(frame, "distance")),
                    altitude=_num(_get(frame, "enhanced_altitude", "altitude")),
                    power=_num(_get(frame, "power")),
                    cadence=_num(_get(frame, "cadence")),
                    temperature=plausible_temp(_num(_get(frame, "temperature"))),
                ))
            elif name == "lap":
                start = _get(frame, "start_time")
                laps.append(Lap(
                    start_s=(start - t0).total_seconds() if start and t0 else 0.0,
                    duration_s=_num(_get(frame, "total_timer_time", "total_elapsed_time")) or 0.0,
                    distance_m=_num(_get(frame, "total_distance")),
                    avg_hr=_num(_get(frame, "avg_heart_rate")),
                    avg_speed=_num(_get(frame, "enhanced_avg_speed", "avg_speed")),
                    avg_power=_num(_get(frame, "avg_power")),
                ))
            elif name == "length":
                lt = _get(frame, "length_type")
                lengths.append(SwimLength(
                    duration_s=_num(_get(frame, "total_timer_time", "total_elapsed_time")) or 0.0,
                    strokes=_get(frame, "total_strokes"),
                    stroke_type=str(_get(frame, "swim_stroke")) if _get(frame, "swim_stroke") is not None else None,
                    active=(lt is None or str(lt) == "active"),
                ))
            elif name == "set":
                if str(_get(frame, "set_type")) != "active":
                    continue
                key, label = exercise_key(_get(frame, "category"), _get(frame, "category_subtype"))
                labels[key] = label
                reps = _get(frame, "repetitions")
                sets.append(ExerciseSet(exercise=key, reps=int(reps) if reps is not None else None,
                                        weight_kg=_num(_get(frame, "weight")),
                                        duration_s=_num(_get(frame, "duration"))))
            elif name == "session":
                session = {
                    "sport": str(_get(frame, "sport") or ""),
                    "sub_sport": str(_get(frame, "sub_sport") or ""),
                    "pool_length": _num(_get(frame, "pool_length")),
                    "rpe": _num(_get(frame, "workout_rpe")),
                    "feel": _num(_get(frame, "workout_feel")),
                    "avg_temp": plausible_temp(_num(_get(frame, "avg_temperature"))),
                    "ascent": _num(_get(frame, "total_ascent")),
                }
    # FIT stores RPE as 10..100
    if session.get("rpe") and session["rpe"] > 10:
        session["rpe"] = session["rpe"] / 10
    return {"records": records, "laps": laps, "lengths": lengths, "sets": sets,
            "exercise_labels": labels, "session": session}


def parse_fit_profile(path: str | Path) -> dict[str, dict]:
    """Only the watch's settings: zones_target (max/threshold HR, FTP), user_profile and sport.
    These messages sit at the start of the file, so stop at the first data record.
    zones_target is sport-specific: in a run, "functional_threshold_power" is the running power threshold."""
    out: dict[str, dict] = {}
    wanted = {"zones_target", "user_profile", "sport"}
    with fitdecode.FitReader(str(path)) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "record":
                break
            if frame.name in wanted:
                d = out.setdefault(frame.name, {})
                for f in frame.fields:
                    if f.value is not None and f.name not in d:
                        d[f.name] = f.value if isinstance(f.value, (int, float, str)) else str(f.value)
    return out
