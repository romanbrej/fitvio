"""How much head- and tailwind changed a run's pace, record by record. Pure functions, no I/O.

Air resistance is part of what running costs (Pugh 1971; di Prampero): per kg and metre C + k·v_air², with
k ≈ 0.40 J·s²·m⁻³ for a 70 kg adult, so ~1.5 % of the cost at 3 m/s in still air. A headwind raises the air
speed, a tailwind lowers it — and costs more than the same tailwind gives back. Each record's speed is
turned into the speed that would have cost the same in still air, like grade-adjusted pace for hills, so
efficiency and pace at the reference HR follow from it. HR drift is not corrected: it comes from heat and
fluid loss, and wind fakes it only when the two halves met different wind — a difference hourly 11 km
weather can't resolve (on real runs, correcting it made drift less comparable, even on out-and-backs;
`fitvio wind-report` keeps checking). Only outdoor runs: rides are judged on power, and watts don't
depend on wind.

The wind is Open-Meteo's (or the platform's) at 10 m, for an ~11 km cell. A runner feels it at about 1 m,
often sheltered: the log wind profile gives ×0.55–0.67 over grass, ×0.4–0.5 over fields and less in
town or woods. EXPOSURE = 0.5 errs towards too little rather than too much (`fitvio wind-report`).
"""
from __future__ import annotations

import math
from datetime import datetime

from ..activity import Record
from . import heat, physio

EXPOSURE = 0.5               # wind at body height ÷ the 10 m forecast
C_RUN = 3.8                  # J/kg/m, cost of running on the flat in still air
K_AIR = 0.40 / 70            # J·s²·m⁻³ per kg, air resistance
MAX_FACTOR = 0.10            # never more than ±10 % per record (a bad heading, a gust in the data)
DRIFT_HALVES_KMH = 5.0       # wind-report: "out-and-back" when the halves' headwind differs this much
COMPASS = {d: i * 22.5 for i, d in enumerate(("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW",
                                              "SW", "WSW", "W", "WNW", "NW", "NNW"))}

Vector = tuple[float, float]  # (east, north) m/s of where the wind comes *from*


def _vector(kmh, deg) -> Vector | None:
    if not isinstance(kmh, (int, float)) or deg is None:
        return None
    s, d = kmh / 3.6, math.radians(deg)
    return s * math.sin(d), s * math.cos(d)


class WindAt:
    """The 10 m wind over a session: Open-Meteo's hours, linear in between (as vectors, so N→NNW never
    swings through S), else one platform reading for the whole session."""

    def __init__(self, weather: dict | None, start: datetime):
        self.points: list[tuple[float, Vector]] = []
        w = weather or {}
        hourly = [h for h in w.get("hourly") or [] if h.get("t") and _vector(h.get("wind_kmh"), h.get("wind_deg"))]
        if hourly:
            for t, h in zip(heat._hour_times(hourly, start), hourly):
                self.points.append(((t - start).total_seconds(), _vector(h["wind_kmh"], h["wind_deg"])))
            return
        deg = w.get("wind_deg")
        if deg is None and isinstance(w.get("wind_dir"), str):
            deg = COMPASS.get(w["wind_dir"].upper())
        if (v := _vector(w.get("wind_kmh"), deg)) is not None:
            self.points.append((0.0, v))

    def __bool__(self) -> bool:
        return bool(self.points)

    def __call__(self, t: float) -> Vector:
        pts = self.points
        if t <= pts[0][0]:
            return pts[0][1]
        for (t0, a), (t1, b) in zip(pts, pts[1:]):
            if t <= t1:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        return pts[-1][1]


def still_air_factor(speed: float, heading: float, wind: Vector, exposure: float = EXPOSURE) -> float:
    """Still-air speed ÷ actual speed for the same metabolic power, running at `heading` (°) in `wind`.

    Power per kg = v·(C + k·|v_air|·v_head), v_air the air relative to the runner: v_head = v + headwind,
    plus the crosswind. Still air: v·(C + k·v²). Solved for the still-air v with Newton's method."""
    h = math.radians(heading)
    ex, ny = math.sin(h), math.cos(h)
    we, wn = wind[0] * exposure, wind[1] * exposure
    head = we * ex + wn * ny                     # the wind's component against the direction of travel
    cross = abs(we * ny - wn * ex)
    v_head = speed + head
    power = speed * (C_RUN + K_AIR * math.hypot(v_head, cross) * v_head)
    v = speed
    for _ in range(4):
        v -= (v * (C_RUN + K_AIR * v * v) - power) / (C_RUN + 3 * K_AIR * v * v)
    return max(1 - MAX_FACTOR, min(1 + MAX_FACTOR, v / speed))


def adjusted_speeds(records: list[Record], speeds: list[float | None], weather: dict | None, start: datetime,
                    exposure: float = EXPOSURE) -> list[float | None] | None:
    """`speeds` (grade-adjusted) times each record's still-air factor; None when there's nothing to correct
    (no wind data, no headings — a treadmill, a file without GPS)."""
    wind = WindAt(weather, start)
    if not wind or not any(r.heading is not None for r in records):
        return None
    out: list[float | None] = []
    for r, s in zip(records, speeds):
        if s is None or r.heading is None or not r.speed or r.speed <= 0.5:
            out.append(s)
        else:
            out.append(s * still_air_factor(r.speed, r.heading, wind(r.t), exposure))
    return out



def halves_headwind_kmh(steady: list[Record], weather: dict | None, start: datetime) -> float | None:
    """How much more headwind (10 m, km/h) the second half of the steady part had than the first — the
    halves HR drift compares. A loop: both halves see every direction, ~0. Out with the wind behind, home
    into it: large. None without wind or headings."""
    wind = WindAt(weather, start)
    if not wind:
        return None
    mid = len(steady) // 2
    means = []
    for half in (steady[:mid], steady[mid:]):
        num = den = 0.0
        for r, dt in zip(half, physio._dt(half)):
            if not dt or r.heading is None or not r.speed or r.speed <= 0.5:
                continue
            we, wn = wind(r.t)
            h = math.radians(r.heading)
            num += (we * math.sin(h) + wn * math.cos(h)) * dt
            den += dt
        if not den:
            return None
        means.append(num / den * 3.6)
    return means[1] - means[0]
