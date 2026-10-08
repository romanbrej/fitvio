"""Hourly weather for outdoor sessions from Open-Meteo (free, no API key, worldwide).

Every session with GPS gets the same kind of weather, whatever the watch or platform: temperature,
dew point, humidity, wind and "feels like" for each hour it ran, where it was at that hour. The route
is kept only as a coarse track — a point every 30 min, rounded to 0.1° (~11 km, about the weather
model's grid) — so the exact home or route never leaves the server.

Cache, one file per place and local day (sessions from home on the same day share it):
    <dir>/om_<lat>_<lon>_<YYYY-MM-DD>.json   {"time": ["2026-07-01T00:00", …], "temperature_2m": […], …,
                                              "fetched_at": "…"}   or {} when Open-Meteo has no data
A day is only complete once it is over: until then hours after `fetched_at` count as missing, so an
evening run never gets the forecast that was cached after the morning run. Network errors, rate
limits and server errors are never cached — the next sync simply tries again.
"""
from __future__ import annotations

import json
import logging
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger(__name__)

FORECAST_API = "https://historical-forecast-api.open-meteo.com/v1/forecast"  # model runs as they were, up to now
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"                 # reanalysis, back to 1940
FORECAST_FROM = date(2022, 1, 1)  # the historical-forecast API has the high-resolution models from here on
VARIABLES = ("temperature_2m", "dew_point_2m", "relative_humidity_2m", "apparent_temperature",
             "wind_speed_10m", "wind_direction_10m")
TIMEOUT_S = 10
MAX_BYTES = 2 * 2**20
MAX_RANGE_DAYS = 31     # one request covers up to a month for one place
PAUSE_S = 0.5           # between requests (free tier: 10,000 calls a day)
MAX_CALLS_PER_RUN = 100  # a backfill continues on the next sync
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")

Position = tuple[float, float]
Track = list  # [(seconds since start, lat, lon), …], rounded; the first point is the start
TRACK_STEP_S = 30 * 60
Fetch = Callable[[str], bytes]


class WeatherUnavailable(Exception):
    """Open-Meteo not reachable, rate limited or failing — try again on a later sync. Never cached."""


def rounded(lat, lon) -> Position | None:
    """The start point as stored and sent: 0.1° (about 11 km). None for anything that isn't a place."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0 and lon == 0:  # "no fix" on some devices
        return None
    return round(lat, 1) + 0.0, round(lon, 1) + 0.0  # + 0.0: never "-0.0" in a file name


def _path(directory: Path, pos: Position, day: date) -> Path:
    return Path(directory) / f"om_{pos[0]:.1f}_{pos[1]:.1f}_{day.isoformat()}.json"


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def track_point(t_s: float, lat, lon) -> tuple[float, float, float] | None:
    pos = rounded(lat, lon)
    return (round(float(t_s)), *pos) if pos else None


def add_to_track(track: Track, t_s: float, pos: Position | None) -> None:
    """Sample a route: the first position, then one at least TRACK_STEP_S after the last sample, and only
    when it is in another cell (a run around the block stays one point)."""
    if pos is None:
        return
    if not track:
        track.append((round(t_s), *pos))
    elif t_s - track[-1][0] >= TRACK_STEP_S and tuple(track[-1][1:]) != tuple(pos):
        track.append((round(t_s), *pos))


def cell_at(track: Track, offset_s: float) -> Position:
    """The cell the session was in `offset_s` after the start (before the start: the start)."""
    here = track[0]
    for p in track:
        if p[0] <= offset_s:
            here = p
        else:
            break
    return here[1], here[2]


def _hours(start: datetime, duration_s: float) -> list[datetime]:
    """The full hours from half an hour before the start to half an hour after the end."""
    lo = start - timedelta(minutes=30)
    hi = start + timedelta(seconds=max(0.0, duration_s or 0.0)) + timedelta(minutes=30)
    h = lo.replace(minute=0, second=0, microsecond=0)
    if h < lo:
        h += timedelta(hours=1)
    out = []
    while h <= hi:
        out.append(h)
        h += timedelta(hours=1)
    return out


def _session_cells(track: Track, start: datetime, duration_s: float) -> list[tuple[datetime, Position]]:
    return [(h, cell_at(track, (h - start).total_seconds())) for h in _hours(start, duration_s)]


def _covers(raw: dict | None, until: datetime) -> bool:
    """True when the cached day can answer for hours up to `until` ({} = Open-Meteo has none: settled)."""
    if raw is None:
        return False
    if not raw:
        return True
    fetched = raw.get("fetched_at")
    complete = raw.get("complete", True)
    return complete or (fetched is not None and datetime.fromisoformat(fetched) >= until)


def missing(directory: Path, track: Track | None, start: datetime, duration_s: float) -> dict[Position, set[date]]:
    """{cell: {local day}} still to download for a session (empty when it can be read)."""
    out: dict[Position, set[date]] = {}
    if not track:
        return out
    for h, cell in _session_cells(track, start, duration_s):
        if not _covers(_read(_path(directory, cell, h.date())), h):
            out.setdefault(cell, set()).add(h.date())
    return out


# --- fetching ------------------------------------------------------------------------------

def _urlopen(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "fitvio", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        if e.code == 400:  # e.g. a date outside the data: a real "no data", worth remembering
            return b"{}"
        raise WeatherUnavailable(f"Open-Meteo answered {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise WeatherUnavailable(f"Open-Meteo not reachable: {e}") from None
    if len(data) > MAX_BYTES:
        raise WeatherUnavailable("Open-Meteo answer too large")
    return data


def url_for(pos: Position, first: date, last: date) -> str:
    params = {"latitude": f"{pos[0]:.1f}", "longitude": f"{pos[1]:.1f}", "start_date": first.isoformat(),
              "end_date": last.isoformat(), "hourly": ",".join(VARIABLES), "timezone": "auto",
              "wind_speed_unit": "kmh"}
    return (FORECAST_API if first >= FORECAST_FROM else ARCHIVE_API) + "?" + urllib.parse.urlencode(params)


def fetch_range(directory: Path, pos: Position, first: date, last: date, fetch: Fetch | None = None,
                now: datetime | None = None) -> int:
    """Download one place's hours for first..last (one API, at most MAX_RANGE_DAYS) and store them per day.
    Returns the number of days stored. Raises WeatherUnavailable (nothing is stored then)."""
    now = now or datetime.now()
    try:
        raw = json.loads((fetch or _urlopen)(url_for(pos, first, last)))
    except ValueError:
        raise WeatherUnavailable("Open-Meteo sent something that isn't JSON") from None
    hourly = raw.get("hourly") if isinstance(raw, dict) else None
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stored = 0
    for i in range((last - first).days + 1):
        day = first + timedelta(days=i)
        if day > now.date():
            continue  # a future day is only a forecast: never cached
        prefix = day.isoformat()
        idx = [j for j, t in enumerate((hourly or {}).get("time") or []) if str(t).startswith(prefix)]
        values = {v: [(hourly.get(v) or [None] * (max(idx) + 1))[j] for j in idx] for v in VARIABLES} if idx else {}
        has_data = any(x is not None for x in values.get("temperature_2m", []))
        record = {"time": [hourly["time"][j] for j in idx], **values} if has_data else {}
        if record:
            record["fetched_at"] = now.isoformat(timespec="seconds")
            record["complete"] = day < now.date()
        elif day >= now.date() - timedelta(days=1):
            continue  # "nothing yet" for today/yesterday is not "nothing ever"
        _path(directory, pos, day).write_text(json.dumps(record))
        stored += 1
    return stored


def _ranges(days: Iterable[date]) -> list[tuple[date, date]]:
    """Missing days → consecutive ranges, each within one API and at most MAX_RANGE_DAYS long."""
    out: list[tuple[date, date]] = []
    for d in sorted(set(days)):
        if out:
            first, last = out[-1]
            same_api = (first >= FORECAST_FROM) == (d >= FORECAST_FROM)
            if same_api and d - last <= timedelta(days=7) and (d - first).days < MAX_RANGE_DAYS:
                out[-1] = (first, d)  # small gaps are cheaper filled in than asked for separately
                continue
        out.append((d, d))
    return out


def fetch_missing(directory: Path, needs: dict[Position, set[date]], fetch: Fetch | None = None,
                  max_calls: int = MAX_CALLS_PER_RUN, pause_s: float = PAUSE_S,
                  sleep: Callable[[float], None] | None = None, now: datetime | None = None) -> dict:
    """Fetch every missing (place, day), newest first, a few requests at a time.

    Stops at the first failure (offline, rate limited): the rest waits for the next sync."""
    sleep = sleep or time.sleep
    jobs = [(pos, a, b) for pos, days in needs.items() for a, b in _ranges(days)]
    jobs.sort(key=lambda j: j[2], reverse=True)  # recent sessions first: their verdicts are the ones being looked at
    calls = days = 0
    error = None
    for pos, a, b in jobs[:max_calls]:
        if calls:
            sleep(pause_s)
        calls += 1
        try:
            days += fetch_range(directory, pos, a, b, fetch, now)
        except WeatherUnavailable as e:
            error = str(e)
            log.warning("weather: %s — trying again on the next sync", error)
            break
    return {"requests": calls, "days": days, "pending": max(0, len(jobs) - calls) + (1 if error else 0),
            "error": error}


# --- reading -------------------------------------------------------------------------------

def _mean(values: list) -> float | None:
    v = [x for x in values if isinstance(x, (int, float))]
    return sum(v) / len(v) if v else None


def compass(deg: float | None) -> str | None:
    return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16] if deg is not None else None


def read_session(directory: Path, track: Track | None, start: datetime, duration_s: float) -> dict | None:
    """The weather over a session: each hour from half an hour before the start to half an hour after the
    end, taken in the cell the session was in at that hour, and their averages (wind direction as a vector
    mean). None while anything is missing."""
    if not track or missing(directory, track, start, duration_s):
        return None
    files: dict = {}
    hours = []
    for h, cell in _session_cells(track, start, duration_s):
        key = (cell, h.date())
        if key not in files:
            raw = _read(_path(directory, cell, h.date())) or {}
            files[key] = (raw, {t: j for j, t in enumerate(raw.get("time") or [])})
        raw, index = files[key]
        j = index.get(h.strftime("%Y-%m-%dT%H:%M"))
        if j is None or raw["temperature_2m"][j] is None:
            continue
        hours.append({"t": h.strftime("%H:%M"), "lat": cell[0], "lon": cell[1], "temp_c": raw["temperature_2m"][j],
                      "dew_point_c": raw["dew_point_2m"][j], "humidity": raw["relative_humidity_2m"][j],
                      "feels_like_c": raw["apparent_temperature"][j],
                      "wind_kmh": raw["wind_speed_10m"][j], "wind_deg": raw["wind_direction_10m"][j]})
    if not hours:
        return None
    winds = [(h["wind_kmh"], h["wind_deg"]) for h in hours if h["wind_kmh"] is not None and h["wind_deg"] is not None]
    wind_deg = None
    if winds:
        x = sum(s * math.sin(math.radians(d)) for s, d in winds)
        y = sum(s * math.cos(math.radians(d)) for s, d in winds)
        wind_deg = round(math.degrees(math.atan2(x, y)) % 360) if (x or y) else None
    one = lambda v: round(v, 1) if v is not None else None  # noqa: E731
    humidity = _mean([h["humidity"] for h in hours])
    return {
        "temp_c": one(_mean([h["temp_c"] for h in hours])),
        "dew_point_c": one(_mean([h["dew_point_c"] for h in hours])),
        "humidity": round(humidity) if humidity is not None else None,
        "feels_like_c": one(_mean([h["feels_like_c"] for h in hours])),
        "wind_kmh": one(_mean([h["wind_kmh"] for h in hours])),
        "wind_deg": wind_deg,
        "wind_dir": compass(wind_deg),
        "source": "Open-Meteo",
        "hourly": hours,
    }
