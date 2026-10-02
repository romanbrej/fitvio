"""Pure physiology / performance functions. No I/O, easy to unit test."""
from __future__ import annotations

import math
from statistics import median

from ..activity import Lap, Record

MAX_GAP_S = 10.0  # longer gaps between records are treated as pauses


def _dt(records: list[Record]) -> list[float]:
    out = [0.0]
    for a, b in zip(records, records[1:]):
        d = b.t - a.t
        out.append(d if 0 < d <= MAX_GAP_S else 0.0)
    return out


# --- Running ---------------------------------------------------------------

def minetti_cost(grade: float) -> float:
    """Energy cost of running (J/kg/m) at a given grade (rise/run), Minetti et al. 2002."""
    i = max(-0.45, min(0.45, grade))
    return 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + 3.6


def grade_adjusted_speeds(records: list[Record], window_m: float = 30.0) -> list[float | None]:
    """Speed on flat ground that would cost the same energy as the actual speed on the actual grade.

    Grade is computed over a trailing distance window to smooth altitude noise.
    """
    out: list[float | None] = []
    j = 0
    for i, r in enumerate(records):
        if r.speed is None:
            out.append(None)
            continue
        grade = 0.0
        if r.distance is not None and r.altitude is not None:
            while j < i and (records[j].distance is None or records[j].altitude is None
                             or r.distance - records[j].distance > window_m):
                j += 1
            ref = records[j]
            dd = r.distance - (ref.distance or 0)
            if ref.altitude is not None and dd >= window_m * 0.5:
                grade = (r.altitude - ref.altitude) / dd
        out.append(r.speed * minetti_cost(grade) / minetti_cost(0.0))
    return out


# Runners' temperature + dew point rule: sum of both in °F → how much harder the same effort is.
HEAT_TABLE = [(100, 0.0), (110, 0.5), (120, 1.0), (130, 2.0), (140, 3.0), (150, 4.5), (160, 6.0), (170, 8.0),
              (180, 10.0)]
HEAT_MAX_PCT = 12.0


def c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def f_to_c(f: float) -> float:
    return (f - 32) * 5 / 9


def heat_adjustment(temp_c: float | None, dew_point_c: float | None, acclimation_pct: float | None = None) -> float:
    """% by which heat and humidity made the same effort harder (0 when unknown or cool).

    Uses temperature + dew point (°F), because humidity matters as much as heat. Heat acclimation
    (Garmin's heatAcclimationPercentage) reduces the effect by up to half — a heuristic.
    """
    if temp_c is None:
        return 0.0
    dew_c = dew_point_c if dew_point_c is not None else temp_c - 10  # rough mid-humidity fallback
    total = c_to_f(temp_c) + c_to_f(dew_c)
    pct = next((p for limit, p in HEAT_TABLE if total <= limit), HEAT_MAX_PCT)
    if acclimation_pct:
        pct *= 1 - 0.5 * max(0.0, min(100.0, acclimation_pct)) / 100
    return round(pct, 2)


def steady_slice(records: list[Record], skip_s: float = 300.0) -> list[Record]:
    """Drop the warm-up (first 5 min, or 10 % for short sessions) where HR lags pace."""
    if not records:
        return records
    total = records[-1].t
    skip = min(skip_s, total * 0.1)
    return [r for r in records if r.t >= skip]


def efficiency_factor(records: list[Record], speeds: list[float | None] | None = None,
                      use_power: bool = False) -> float | None:
    """Output per heartbeat: (speed in m/min or watts) / HR, time-weighted over moving records."""
    speeds = speeds if speeds is not None else [r.speed for r in records]
    num = den = 0.0
    for r, s, dt in zip(records, speeds, _dt(records)):
        out = r.power if use_power else s
        if not dt or not r.hr or r.hr < 60 or out is None or out <= 0:
            continue
        num += (out * (1 if use_power else 60)) * dt
        den += r.hr * dt
    return num / den if den > 0 else None


def decoupling(records: list[Record], speeds: list[float | None] | None = None,
               use_power: bool = False) -> float | None:
    """Aerobic decoupling in % (efficiency loss from the first to the second half). Lower is better."""
    if len(records) < 120:
        return None
    speeds = speeds if speeds is not None else [r.speed for r in records]
    mid = len(records) // 2
    ef1 = efficiency_factor(records[:mid], speeds[:mid], use_power)
    ef2 = efficiency_factor(records[mid:], speeds[mid:], use_power)
    if not ef1 or not ef2:
        return None
    return (ef1 - ef2) / ef1 * 100


def speed_at_hr(records: list[Record], speeds: list[float | None], target_hr: float,
                band: float = 12.0) -> float | None:
    """Linear fit of speed vs HR over steady records, evaluated at target_hr (m/s).

    Only returns a value when the session actually covered HRs around the target,
    so we never extrapolate far outside the data.
    """
    pts = [(r.hr, s) for r, s in zip(records, speeds) if r.hr and s and s > 0.5]
    if len(pts) < 60:
        return None
    near = [p for p in pts if abs(p[0] - target_hr) <= band]
    if len(near) < 30:
        return None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx < 1e-6:
        return median(p[1] for p in near)
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    return my + slope * (target_hr - mx)


# --- Cycling ---------------------------------------------------------------

def rolling_mean(values: list[float], window: int) -> list[float]:
    if len(values) < window:
        return []
    out, acc = [], sum(values[:window])
    out.append(acc / window)
    for i in range(window, len(values)):
        acc += values[i] - values[i - window]
        out.append(acc / window)
    return out


def power_series_1hz(records: list[Record]) -> list[float]:
    """Resample power to 1 Hz (zero-filled over short gaps) for rolling computations."""
    if not records:
        return []
    out: list[float] = []
    for a, b in zip(records, records[1:] + [records[-1]]):
        d = int(round(b.t - a.t)) if b is not a else 1
        d = d if 0 < d <= MAX_GAP_S else 1
        out.extend([a.power or 0.0] * d)
    return out


def normalized_power(power_1hz: list[float]) -> float | None:
    rm = rolling_mean(power_1hz, 30)
    if not rm:
        return None
    return (sum(p**4 for p in rm) / len(rm)) ** 0.25


def power_curve(power_1hz: list[float], durations=(5, 60, 300, 1200)) -> dict[str, float]:
    out = {}
    for d in durations:
        rm = rolling_mean(power_1hz, d)
        if rm:
            out[str(d)] = max(rm)
    return out


# --- Load ------------------------------------------------------------------

def trimp(records: list[Record], rest_hr: float, max_hr: float, sex: str = "male",
          avg_hr: float | None = None, duration_s: float | None = None) -> float:
    """Banister TRIMP. Uses per-record HR when available, otherwise the session average."""
    k = (0.64, 1.92) if sex != "female" else (0.86, 1.67)
    rng = max(max_hr - rest_hr, 1)

    def w(hr):
        x = max(0.0, min(1.0, (hr - rest_hr) / rng))
        return x * k[0] * math.exp(k[1] * x)

    hr_records = [(r, dt) for r, dt in zip(records, _dt(records)) if r.hr]
    if len(hr_records) > 60:
        return sum(w(r.hr) * dt / 60 for r, dt in hr_records)
    if avg_hr and duration_s:
        return w(avg_hr) * duration_s / 60
    return 0.0


def zone_distribution(records: list[Record], max_hr: float, rest_hr: float) -> list[float]:
    """Fraction of time in 5 HR zones by % of heart-rate reserve (Karvonen: <60, 60-70, 70-80, 80-90, >=90)."""
    t = [0.0] * 5
    rng = max(max_hr - rest_hr, 1)
    for r, dt in zip(records, _dt(records)):
        if not r.hr or not dt:
            continue
        pct = (r.hr - rest_hr) / rng
        z = 0 if pct < 0.6 else 1 if pct < 0.7 else 2 if pct < 0.8 else 3 if pct < 0.9 else 4
        t[z] += dt
    tot = sum(t)
    return [x / tot for x in t] if tot else t


# --- Strength ---------------------------------------------------------------

def epley_1rm(weight_kg: float | None, reps: int | None) -> float | None:
    if not weight_kg or not reps or reps <= 0:
        return None
    if reps == 1:
        return weight_kg
    return weight_kg * (1 + min(reps, 15) / 30)


def avg_hr(records: list[Record]) -> float | None:
    """Time-weighted average HR."""
    num = den = 0.0
    for r, dt in zip(records, _dt(records)):
        if r.hr and r.hr >= 60 and dt:
            num += r.hr * dt
            den += dt
    return num / den if den else None


def interval_reps(laps: list[Lap], min_lap_s: float = 20.0) -> dict | None:
    """Split a structured workout's laps into work reps and recoveries.

    Warm-up and cool-down (first and last lap, when there are 5+) are dropped; the rest is split at the
    midpoint between the slowest and fastest lap. Judging reps only keeps the recovery jogs out of pace
    and efficiency, which is what made intervals look "worse" with the steady-run metrics.
    """
    laps = [lap for lap in laps if lap.duration_s >= min_lap_s and _lap_speed(lap)]
    if len(laps) >= 5:
        laps = laps[1:-1]
    if len(laps) < 3:
        return None
    speeds = [_lap_speed(lap) for lap in laps]
    cut = (min(speeds) + max(speeds)) / 2
    work = [lap for lap, v in zip(laps, speeds) if v > cut]
    rest = [lap for lap, v in zip(laps, speeds) if v <= cut]
    if len(work) < 2 or not rest or max(speeds) < min(speeds) * 1.1:
        return None

    def weighted(ls, get):
        pts = [(get(lap), lap.duration_s) for lap in ls if get(lap)]
        return sum(v * d for v, d in pts) / sum(d for _, d in pts) if pts else None

    work_speed = weighted(work, _lap_speed)
    work_hr = weighted(work, lambda lap: lap.avg_hr)
    rest_hr = weighted(rest, lambda lap: lap.avg_hr)
    rep_fade = None
    if len(work) >= 4:  # pace lost from the first to the last third of the reps (+ = slowed down)
        third = max(1, len(work) // 3)
        first, last = weighted(work[:third], _lap_speed), weighted(work[-third:], _lap_speed)
        rep_fade = (first - last) / first * 100 if first and last else None
    return {
        "rep_count": len(work),
        "rep_s": median(lap.duration_s for lap in work),  # rep length: 1:00 and 4:00 reps aren't comparable
        "rep_fade": rep_fade,
        "work_speed": work_speed,
        "work_hr": work_hr,
        "work_ef": work_speed * 60 / work_hr if work_speed and work_hr else None,  # m/min per beat
        "hr_recovery": work_hr - rest_hr if work_hr and rest_hr else None,     # bpm drop in recoveries
    }


def _lap_speed(lap: Lap) -> float | None:
    if lap.avg_speed:
        return lap.avg_speed
    return lap.distance_m / lap.duration_s if lap.distance_m and lap.duration_s else None


# --- Stats helpers ------------------------------------------------------------

def mad(values: list[float]) -> float:
    if not values:
        return 0.0
    m = median(values)
    return median(abs(v - m) for v in values)


def linear_slope(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
