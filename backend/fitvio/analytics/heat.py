"""How much heat cost a session, and how much heat costs this person.

heat_load: the table's % (temperature + dew point, physio.HEAT_TABLE) over the session's hours, i.e. how
much harder the same effort was for a standard runner. A person's heat response k scales it: k = 1 is the
table, 2 is twice as heat-sensitive. k (and d, the extra HR drift per % of load) is learned from the
person's own outdoor sessions, compared with the similar sessions around them, and pulled towards a prior
until there is enough warm-weather data. Pure functions, no I/O.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from statistics import median

from . import physio

SPORTS = ("running", "cycling")
# Priors: runs start at the table; outdoor rides cool better (airflow), so half of it. No drift correction
# until the data shows one.
PRIOR = {"running": {"k": 1.0, "d": 0.0}, "cycling": {"k": 0.5, "d": 0.0}}
PRIOR_SD = {"k": 0.5, "d": 0.5}
LIMITS = {"k": (0.0, 3.0), "d": (0.0, 1.5)}
FIT_TYPES = {"easy", "long", "tempo"}  # steady sessions: intervals and races say little about heat
WINDOW_DAYS = 21                         # neighbours on both sides, so fitness changes cancel out
MIN_NEIGHBOURS = 3
MIN_FIT = 8                              # fewer usable sessions: the prior alone
WARM_PCT = 1.0                           # "warm" session for the counts people see
BINS = [(0.0, 0.0), (0.0, 2.0), (2.0, 4.0), (4.0, 6.0), (6.0, math.inf)]


# --- heat load -----------------------------------------------------------------

def _hour_times(hourly: list[dict], start: datetime) -> list[datetime]:
    """Open-Meteo's hours carry only "HH:MM" (local, the session's clock): give them their dates back."""
    out: list[datetime] = []
    prev = start - timedelta(minutes=30)
    for h in hourly:
        hh, mm = (int(v) for v in h["t"].split(":"))
        t = prev.replace(hour=hh, minute=mm, second=0, microsecond=0)
        while t < prev - timedelta(minutes=1):
            t += timedelta(days=1)
        out.append(t)
        prev = t
    return out


def _interp(points: list[tuple[float, float]], x: float) -> float:
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def heat_load(weather: dict | None, start: datetime, duration_s: float | None,
              acclimation_pct: float | None = None, indoor: bool = False) -> float:
    """% by which the weather made the same effort harder for a standard runner, over the session.

    Each Open-Meteo hour gets the table's %, linear in between, averaged over the session's time (a ride
    from 9 to 12 counts its hot end). One reading (platform weather) counts as it is. Garmin's heat
    acclimation lowers it by up to half. Indoor: 0.
    """
    if indoor or not weather:
        return 0.0
    hourly = [h for h in weather.get("hourly") or [] if h.get("temp_c") is not None and h.get("t")]
    if hourly:
        times = _hour_times(hourly, start)
        pts = [((t - start).total_seconds(), physio.heat_table_pct(h["temp_c"], h.get("dew_point_c")))
               for t, h in zip(times, hourly)]
        dur = max(60.0, float(duration_s or 0))
        n = max(1, int(dur // 60))
        pct = sum(_interp(pts, dur * (i + 0.5) / n) for i in range(n)) / n
    elif weather.get("temp_c") is not None:
        pct = physio.heat_table_pct(weather["temp_c"], weather.get("dew_point_c"))
    else:
        return 0.0
    if acclimation_pct:
        pct *= 1 - 0.5 * max(0.0, min(100.0, acclimation_pct)) / 100
    return round(pct, 2)


def session_load(s: dict) -> float:
    """A stored session's heat load: the stored one, else worked out from its stored weather."""
    f = s.get("features") or {}
    if f.get("heat_load_pct") is not None:
        return f["heat_load_pct"]
    return heat_load(f.get("weather"), datetime.fromisoformat(s["start_time"]), s.get("duration_s"),
                     f.get("heat_acclimation"), bool(s.get("indoor")))


# --- learning the response ---------------------------------------------------------

def _usable(s: dict, sport: str) -> bool:
    f = s.get("features") or {}
    return (s["sport"] == sport and not s.get("indoor") and not s.get("excluded")
            and s.get("session_type") in FIT_TYPES and (f.get("ef") or 0) > 0
            and (f.get("weather") or {}).get("temp_c") is not None  # no weather is unknown, not cool
            and (sport != "cycling" or s.get("has_power")))


def residuals(sessions: list[dict], sport: str) -> list[dict]:
    """Per usable session: how its efficiency (and drift) differed from its similar neighbours within
    ±21 days, next to how much hotter it was than they were."""
    pool = []
    for s in sessions:
        if _usable(s, sport):
            f = s["features"]
            pool.append({"t": datetime.fromisoformat(s["start_time"]), "type": s["session_type"],
                         "dur": s.get("duration_s") or 0, "y": math.log(f["ef"]), "dec": f.get("decoupling"),
                         "load": session_load(s)})
    pool.sort(key=lambda p: p["t"])
    times = [p["t"] for p in pool]
    out = []
    win = timedelta(days=WINDOW_DAYS)
    for i, a in enumerate(pool):
        lo, hi = bisect_left(times, a["t"] - win), bisect_right(times, a["t"] + win)
        nb = [b for j, b in enumerate(pool[lo:hi], lo) if j != i and b["type"] == a["type"]
              and a["dur"] and b["dur"] and 0.5 <= b["dur"] / a["dur"] <= 2.0]
        if len(nb) < MIN_NEIGHBOURS:
            continue
        x = a["load"] - sum(b["load"] for b in nb) / len(nb)
        decs = [b["dec"] for b in nb if b["dec"] is not None]
        out.append({"load": a["load"], "x": x, "r": a["y"] - sum(b["y"] for b in nb) / len(nb),
                    "rd": a["dec"] - sum(decs) / len(decs) if a["dec"] is not None and len(decs) >= MIN_NEIGHBOURS
                    else None})
    return out


def _trimmed(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Without the residuals beyond 3 robust SDs (a GPS glitch, a sick day)."""
    if len(pts) < MIN_FIT:
        return pts
    med = median(p[1] for p in pts)
    spread = 1.4826 * median(abs(p[1] - med) for p in pts)
    return [p for p in pts if abs(p[1] - med) <= 3 * spread] if spread else pts


def _slope(pts: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Least-squares slope of y on x and its standard error."""
    n = len(pts)
    if n < MIN_FIT:
        return None
    mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx <= 1e-9:
        return None
    b = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    rss = sum((p[1] - my - b * (p[0] - mx)) ** 2 for p in pts)
    # residuals share neighbours, so they are not fully independent: √2 wider than plain least squares
    se = math.sqrt(rss / max(1, n - 2) / sxx) * math.sqrt(2)
    return b, se


def _shrink(est: float | None, se: float | None, prior: float, prior_sd: float, lo: float, hi: float) -> float:
    if est is None or not se:
        return prior
    w_data, w_prior = 1 / se**2, 1 / prior_sd**2
    return round(max(lo, min(hi, (est * w_data + prior * w_prior) / (w_data + w_prior))), 2)


def fit_response(sessions: list[dict], sport: str) -> dict:
    """This person's heat response for a sport: k (× the table) and d (extra HR drift points per % of
    load), each the data's estimate pulled towards the prior by how uncertain it is."""
    prior = PRIOR[sport]
    res = residuals(sessions, sport)
    eff = _slope(_trimmed([(p["x"], p["r"]) for p in res]))
    drift = _slope(_trimmed([(p["x"], p["rd"]) for p in res if p["rd"] is not None]))
    k_hat, k_se = (-eff[0] * 100, eff[1] * 100) if eff else (None, None)
    d_hat, d_se = drift if drift else (None, None)
    used = [s for s in sessions if _usable(s, sport)]
    return {
        "sport": sport, "n": len(res), "sessions": len(used),
        "warm": sum(1 for s in used if session_load(s) >= WARM_PCT),
        "k": _shrink(k_hat, k_se, prior["k"], PRIOR_SD["k"], *LIMITS["k"]),
        "k_hat": round(k_hat, 2) if k_hat is not None else None, "k_se": round(k_se, 2) if k_se else None,
        "d": _shrink(d_hat, d_se, prior["d"], PRIOR_SD["d"], *LIMITS["d"]),
        "d_hat": round(d_hat, 2) if d_hat is not None else None, "d_se": round(d_se, 2) if d_se else None,
        "prior": prior,
    }


def binned(sessions: list[dict], sport: str, k: float) -> list[dict]:
    """Mean residual per heat-load bin, as measured and after the k correction: flat after = k fits."""
    res = residuals(sessions, sport)
    out = []
    for lo, hi in BINS:
        pts = [p for p in res if (p["load"] == 0 if hi == 0 else lo < p["load"] <= hi)]
        if pts:
            raw = sum(p["r"] for p in pts) / len(pts) * 100
            adj = sum(p["r"] + k * p["x"] / 100 for p in pts) / len(pts) * 100
            out.append({"bin": "0" if hi == 0 else f"{lo:g}–{hi:g}" if hi != math.inf else f"{lo:g}+",
                        "n": len(pts), "raw_pct": round(raw, 2), "adjusted_pct": round(adj, 2)})
    return out


def coverage(sessions: list[dict], sport: str) -> list[dict]:
    """Per month: where the sessions go on their way into the fit (counts only, for heat-report)."""
    months: dict[str, dict] = {}
    for s in sessions:
        if s["sport"] != sport or s.get("excluded"):
            continue
        f = s.get("features") or {}
        w = f.get("weather") or {}
        m = months.setdefault(s["start_time"][:7], {"month": s["start_time"][:7], "all": 0, "indoor": 0,
                                                    "open_meteo": 0, "platform": 0, "no_weather": 0,
                                                    "steady": 0, "no_ef": 0, "warm": 0, "usable": 0, "loads": []})
        m["all"] += 1
        if s.get("indoor"):
            m["indoor"] += 1
            continue
        src = "open_meteo" if w.get("source") == "Open-Meteo" else "platform" if w.get("temp_c") is not None \
            else "no_weather"
        m[src] += 1
        m["steady"] += s.get("session_type") in FIT_TYPES
        m["no_ef"] += not (f.get("ef") or 0) > 0
        if _usable(s, sport):
            m["usable"] += 1
            load = session_load(s)
            m["loads"].append(load)
            m["warm"] += load >= WARM_PCT
    for m in months.values():
        m["max_load"] = round(max(m["loads"]), 1) if m["loads"] else None
        del m["loads"]
    return sorted(months.values(), key=lambda m: m["month"])


# --- applying it -----------------------------------------------------------------

def priors() -> dict[str, dict]:
    return {sport: dict(PRIOR[sport]) for sport in SPORTS}


def adjust(sessions: list[dict], response: dict[str, dict]) -> None:
    """Heat-adjusted values on the sessions' features, from the raw ones: heat_adj_pct, ef_adj,
    speed_at_ref_hr_adj, power_at_ref_hr_adj, decoupling_adj (the pipeline stores them with the session)."""
    for s in sessions:
        r = response.get(s["sport"])
        f = s.get("features")
        if not r or f is None:
            continue
        # nothing to adjust without an efficiency (a ride without power is judged on load only)
        load = 0.0 if s.get("indoor") or f.get("ef") is None else session_load(s)
        pct = round(r["k"] * load, 2)
        up = 1 + pct / 100
        f["heat_adj_pct"] = pct
        for key in ("ef", "speed_at_ref_hr", "power_at_ref_hr"):
            if f.get(key) is not None:
                f[f"{key}_adj"] = round(f[key] * up, 4)
        if f.get("decoupling") is not None:
            f["decoupling_adj"] = round(f["decoupling"] - r["d"] * load, 4)
        f["heat_response"] = {"k": r["k"], "d": r["d"], "warm": r.get("warm")}
