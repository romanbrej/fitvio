"""Garmin data that GarminDB doesn't download: activity weather and heat acclimation.

This is exactly what Garmin Connect shows — the weather box of an activity (from a weather station
near the start, at start time) and the heat-acclimation value from training status — loaded from the
same Garmin endpoints. Files live in `<HealthData>/Extras/`:
    weather_<activity_id>.json      Garmin's raw answer ({} when Garmin has no weather, e.g. indoor)
    acclimation_<YYYY-MM-DD>.json   Garmin's raw answer for that day
Existing files are never requested again.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

WEATHER_URL = "/activity-service/activity/{activity_id}/weather"
ACCLIMATION_URL = "/metrics-service/metrics/heataltitudeacclimation/latest/{day}"


def extras_dir(health_data_dir: Path) -> Path:
    return Path(health_data_dir) / "Extras"


_ID = re.compile(r"^(\d+)(?:_\d+)?$")


def weather_id(activity_id) -> str | None:
    """Garmin activity id for the weather lookup. Multisport legs ("23160165938_2", as GarminDB
    stores them) share the parent activity's weather. None for anything that isn't an id."""
    m = _ID.match(str(activity_id))
    return m.group(1) if m else None


def _save(path: Path, data) -> None:
    path.write_text(json.dumps(data if data is not None else {}, default=str))


def missing(directory: Path, activity_id: str, day: date | str) -> tuple[bool, bool]:
    """(weather missing, acclimation missing) for one activity."""
    wid = weather_id(activity_id)
    return (wid is not None and not (directory / f"weather_{wid}.json").exists(),
            not (directory / f"acclimation_{day}.json").exists())


def fetch_extras(connectapi: Callable, directory: Path, activity_id: str, day: date | str) -> int:
    """Download what is missing for one activity. Returns the number of requests made.

    `connectapi(path)` is Garmin's authenticated GET (GarminDB's `self.garmin.connectapi` or the
    garminconnect client). A "no weather" answer is stored as {} so it's never asked again;
    network errors raise, so the caller's retry/back-off applies.
    """
    activity_id = weather_id(activity_id)
    if activity_id is None:
        return 0
    directory.mkdir(parents=True, exist_ok=True)
    need_weather, need_accl = missing(directory, activity_id, day)
    requests = 0
    if need_weather:
        requests += 1
        try:
            data = connectapi(WEATHER_URL.format(activity_id=activity_id))
        except Exception as e:
            if "404" in str(e) or "204" in str(e):  # no weather for this activity (indoor, no GPS)
                data = {}
            else:
                raise
        _save(directory / f"weather_{activity_id}.json", data)
    if need_accl:
        requests += 1
        try:
            data = connectapi(ACCLIMATION_URL.format(day=day))
        except Exception as e:
            if "404" in str(e) or "204" in str(e):
                data = {}
            else:
                raise
        _save(directory / f"acclimation_{day}.json", data)
    return requests


# --- reading (metric, only what the dashboard needs) ---------------------------------

def _f_to_c(v):
    return round((v - 32) * 5 / 9, 1) if isinstance(v, (int, float)) else None


def read_weather(directory: Path, activity_id: str) -> dict | None:
    wid = weather_id(activity_id)
    if wid is None:
        return None
    try:
        raw = json.loads((directory / f"weather_{wid}.json").read_text())
    except (OSError, ValueError):
        return None
    if not raw or raw.get("temp") is None:
        return None
    # Garmin's weather API answers in °F and mph regardless of the account's unit setting.
    wind = raw.get("windSpeed")
    return {
        "temp_c": _f_to_c(raw.get("temp")),
        "feels_like_c": _f_to_c(raw.get("apparentTemp")),
        "dew_point_c": _f_to_c(raw.get("dewPoint")),
        "humidity": raw.get("relativeHumidity"),
        "wind_kmh": round(wind * 1.609, 1) if isinstance(wind, (int, float)) else None,
        "wind_dir": (raw.get("windDirectionCompassPoint") or "").upper() or None,
        "station": (raw.get("weatherStationDTO") or {}).get("name"),
        "desc": (raw.get("weatherTypeDTO") or {}).get("desc"),
    }


def read_acclimation(directory: Path, day: date | str) -> float | None:
    try:
        raw = json.loads((directory / f"acclimation_{day}.json").read_text())
    except (OSError, ValueError):
        return None
    v = (raw or {}).get("heatAcclimationPercentage")
    return float(v) if isinstance(v, (int, float)) else None


def backfill(connectapi: Callable, directory: Path, items: list[tuple[str, str]], pause_s: float = 0.25,
             on_progress: Callable[[int, int], None] | None = None, sleep: Callable[[float], None] | None = None) -> dict:
    """Fetch weather + acclimation for every (activity_id, day) that is still missing.

    Polite to Garmin: a short pause between requests, exponential back-off on errors (e.g. rate
    limiting), and it gives up after repeated failures — the next run simply continues.
    """
    import time
    sleep = sleep or time.sleep
    todo = [(aid, day) for aid, day in items if any(missing(directory, aid, day))]
    done = failed = 0
    pause = pause_s
    for i, (aid, day) in enumerate(todo, 1):
        try:
            if fetch_extras(connectapi, directory, aid, day):
                done += 1
            pause = max(pause_s, pause * 0.8)
        except Exception as e:
            failed += 1
            pause = min(30.0, max(pause * 2, 2.0))
            log.warning("extras for %s failed (%s), backing off %.0fs", aid, str(e)[:120], pause)
            if failed >= 10:
                log.warning("too many errors, stopping the backfill; it continues on the next run")
                break
        if on_progress:
            on_progress(i, len(todo))
        sleep(pause)
    return {"missing": len(todo), "fetched": done, "failed": failed}


# --- precise VO2max (one decimal, e.g. 44.1) --------------------------------------------
# GarminDB only keeps Garmin's rounded VO2max (44). Garmin's daily history has the precise value
# for running ("generic") and cycling — the whole history in a single request.

VO2MAX_URL = "/metrics-service/metrics/maxmet/daily/{start}/{end}"
VO2MAX_FILE = "vo2max.json"
VO2MAX_HISTORY_DAYS = 5 * 365
VO2MAX_OVERLAP_DAYS = 14


def update_vo2max(connectapi: Callable, directory: Path, today: date | None = None) -> int:
    """Fetch new precise VO2max values and merge them into vo2max.json. Returns the number of days stored.

    First run: the whole history (one request). Afterwards: from shortly before the newest stored day.
    """
    from datetime import timedelta
    today = today or date.today()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / VO2MAX_FILE
    try:
        known = json.loads(path.read_text())
    except (OSError, ValueError):
        known = {}
    start = (date.fromisoformat(max(known)) - timedelta(days=VO2MAX_OVERLAP_DAYS)) if known \
        else today - timedelta(days=VO2MAX_HISTORY_DAYS)
    rows = connectapi(VO2MAX_URL.format(start=start, end=today)) or []
    for row in rows if isinstance(rows, list) else []:
        entry = {}
        for sport, key in (("running", "generic"), ("cycling", "cycling")):
            v = (row.get(key) or {}).get("vo2MaxPreciseValue")
            if isinstance(v, (int, float)):
                entry[sport] = float(v)
        day = (row.get("generic") or row.get("cycling") or {}).get("calendarDate")
        if entry and day:
            known[str(day)[:10]] = {**known.get(str(day)[:10], {}), **entry}
    path.write_text(json.dumps(dict(sorted(known.items()))))
    return len(known)


def read_vo2max(directory: Path) -> dict[str, dict]:
    """{"2026-09-28": {"running": 44.1, "cycling": 41.3}, …}"""
    try:
        return json.loads((directory / VO2MAX_FILE).read_text())
    except (OSError, ValueError):
        return {}
