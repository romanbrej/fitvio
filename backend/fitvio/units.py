"""Metric or imperial, for people: everything is stored and computed in SI units (m, s, m/s, kg, °C) and
only turned into text here. One switch per person ("imperial": mi, /mi, mph, °F, lb, ft, /100 yd); the
install's default is FITVIO_UNITS in .env, metric without it."""
from __future__ import annotations

import logging
import sqlite3

from . import db
from .config import env

log = logging.getLogger(__name__)

METRIC, IMPERIAL = "metric", "imperial"
CHOICES = (METRIC, IMPERIAL)
SETTING = "units:{user_id}"  # this person's choice; unset = the install's default

M_PER_MI = 1609.344
M_PER_FT = 0.3048
M_PER_YD = 0.9144
KG_PER_LB = 0.45359237
KM_PER_MI = M_PER_MI / 1000
_warned: set[str] = set()


def default() -> str:
    """FITVIO_UNITS from the environment; anything else than metric/imperial is ignored (metric)."""
    v = (env("UNITS") or METRIC).strip().lower()
    if v not in CHOICES:
        if v not in _warned:  # read on every request: say it once, not per request
            _warned.add(v)
            log.warning("FITVIO_UNITS=%r is not metric or imperial: using metric", v)
        return METRIC
    return v


def for_user(conn: sqlite3.Connection, user_id: str) -> str:
    v = db.get_state(conn, SETTING.format(user_id=user_id))
    return v if v in CHOICES else default()


def set_for_user(conn: sqlite3.Connection, user_id: str, units: str) -> None:
    if units not in CHOICES:
        raise ValueError(f"units must be one of {', '.join(CHOICES)}")
    db.set_state(conn, SETTING.format(user_id=user_id), units)


def _imperial(u: str | None) -> bool:
    return u == IMPERIAL


def _mss(sec: float) -> str:
    """312.4 → "5:12" (rounded to the second first, so 59.6 s is "1:00", not "0:60")."""
    s = round(sec)
    return f"{s // 60}:{s % 60:02d}"


def pace_unit(u: str | None) -> str:
    return "/mi" if _imperial(u) else "/km"


def pace_s(s_per_km: float | None, u: str | None) -> str:
    """Seconds per km as a pace: "5:12 /km" or "8:22 /mi"."""
    if not s_per_km or s_per_km <= 0:
        return "—"
    return f"{_mss(s_per_km * KM_PER_MI if _imperial(u) else s_per_km)} {pace_unit(u)}"


def pace(speed: float | None, u: str | None) -> str:
    """A speed in m/s as a pace."""
    if not speed or speed <= 0:
        return "—"
    return pace_s(1000 / speed, u)


def pace_seconds(diff_s_per_km: float, u: str | None) -> tuple[int, str]:
    """A pace difference in whole seconds of the person's unit: (8, "s/km") or (13, "s/mi")."""
    return (round(diff_s_per_km * KM_PER_MI), "s/mi") if _imperial(u) else (round(diff_s_per_km), "s/km")


def swim_unit(u: str | None) -> str:
    return "/100yd" if _imperial(u) else "/100m"


def swim_pace(s_per_100m: float | None, u: str | None) -> str:
    """Seconds per 100 m as "1:45 /100m", or per 100 yards: "1:36 /100yd"."""
    if not s_per_100m or s_per_100m <= 0:
        return "—"
    return f"{_mss(s_per_100m * M_PER_YD if _imperial(u) else s_per_100m)} {swim_unit(u)}"


def swim_seconds(diff_s_per_100m: float, u: str | None) -> tuple[int, str]:
    return (round(diff_s_per_100m * M_PER_YD), "s/100yd") if _imperial(u) else (round(diff_s_per_100m), "s/100m")


def distance(m: float, u: str | None, dp: int = 1) -> str:
    """A run's or ride's length: "12.3 km" or "7.6 mi"."""
    return f"{m / M_PER_MI:.{dp}f} mi" if _imperial(u) else f"{m / 1000:.{dp}f} km"


def swim_distance(m: float, u: str | None) -> str:
    return f"{m / M_PER_YD:.0f} yd" if _imperial(u) else f"{m:.0f} m"


def elevation(m: float, u: str | None) -> str:
    return f"{m / M_PER_FT:.0f} ft" if _imperial(u) else f"{m:.0f} m"


def temp(c: float, u: str | None) -> str:
    return f"{c * 9 / 5 + 32:.0f} °F" if _imperial(u) else f"{c:.0f} °C"


def wind(kmh: float, u: str | None) -> str:
    return f"{kmh / KM_PER_MI:.0f} mph" if _imperial(u) else f"{kmh:.0f} km/h"


def weight(kg: float, u: str | None, dp: int = 1) -> str:
    return f"{kg / KG_PER_LB:.{dp}f} lb" if _imperial(u) else f"{kg:.{dp}f} kg"


def weight_diff(kg: float, u: str | None) -> str:
    """A signed weight change: "+2.5 kg" or "+5.5 lb"."""
    return f"{kg / KG_PER_LB:+.1f} lb" if _imperial(u) else f"{kg:+.1f} kg"


def per_beat(m: float, u: str | None) -> str:
    """Running efficiency, distance per heartbeat: "1.65 m/beat" or "5.41 ft/beat"."""
    return f"{m / M_PER_FT:.2f} ft/beat" if _imperial(u) else f"{m:.2f} m/beat"
