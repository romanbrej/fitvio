"""Intervals.icu as a data source: download into a local folder, then read it like GarminDB.

Intervals.icu collects activities from many devices (Garmin, Polar, Coros, Suunto, Wahoo, Apple Watch
via HealthFit, Fitbit via Health Sync …), so one connector covers them all. Access is a personal API
key (Settings → Developer settings) — no OAuth, and the server only makes outgoing requests.

Layout of <base>  (data/intervals/<user>/, chmod 700):
    credentials.json            {"athlete_id", "api_key"}  (chmod 600, never logged or returned)
    athlete.json                profile + sport settings (max HR, LTHR, FTP)
    wellness.json               {day: wellness record}  (resting HR, HRV, sleep, weight, steps)
    activities/<id>.json        activity summary; rewritten only when it changed (→ "edited")
    activities/<id>.fit         the original FIT file, or Intervals' own FIT for other formats
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Callable

from ..activity import ParsedActivity, normalize_sport, plausible_temp
from ..config import env
from .fit_parser import parse_fit

log = logging.getLogger(__name__)

API = "https://intervals.icu/api/v1"
TIMEOUT_S = 60
MAX_BYTES = 64 * 2**20  # one answer or unpacked FIT file; a real FIT is a few MB
FULL_HISTORY_DAYS = 5 * 365  # first download; FITVIO_INTERVALS_HISTORY_DAYS=30 for a quick test
RECENT_DAYS = 14  # a normal sync re-reads at least this window: late uploads and edits (name, RPE) show up
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

# Intervals.icu activity types → the Garmin sport names normalize_sport() knows
SPORTS = {
    "Run": ("running", None), "TrailRun": ("running", "trail"), "VirtualRun": ("running", "treadmill"),
    "Ride": ("cycling", None), "GravelRide": ("cycling", "gravel_cycling"),
    "MountainBikeRide": ("cycling", "mountain"), "EBikeRide": ("cycling", "e_bike_fitness"),
    "VirtualRide": ("cycling", "virtual_ride"), "TrackRide": ("cycling", "track_cycling"),
    "Swim": ("swimming", "lap_swimming"), "OpenWaterSwim": ("swimming", "open_water"),
    "WeightTraining": ("training", "strength_training"),
}


class IntervalsError(Exception):
    """Network or server error — try again later."""


class AuthFailed(IntervalsError):
    """The API key or athlete id is wrong, or the key was revoked."""


class RateLimited(IntervalsError):
    """Intervals.icu answered 429."""


# --- credentials ------------------------------------------------------------------

def save_credentials(base: Path, athlete_id: str, api_key: str) -> None:
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    path = base / "credentials.json"
    path.write_text(json.dumps({"athlete_id": athlete_id, "api_key": api_key}))
    os.chmod(path, 0o600)


def load_credentials(base: Path) -> tuple[str, str]:
    c = json.loads((base / "credentials.json").read_text())
    return c["athlete_id"], c["api_key"]


def normalize_athlete_id(value: str) -> str:
    """'i12345', '12345' or the athlete URL from the Intervals.icu settings page → 'i12345'."""
    v = value.strip().rstrip("/").split("/")[-1]
    v = v if v.startswith("i") else f"i{v}"
    if not re.fullmatch(r"i[0-9]{1,12}", v):
        raise ValueError("the athlete id looks like i12345 (Intervals.icu → Settings → Developer settings)")
    return v


# --- HTTP ---------------------------------------------------------------------------

Fetch = Callable[[str, dict], bytes]


class Client:
    def __init__(self, athlete_id: str, api_key: str, fetch: Fetch | None = None):
        self.athlete_id = athlete_id
        self._auth = "Basic " + base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
        self._fetch = fetch or self._urlopen

    def _urlopen(self, path: str, params: dict) -> bytes:
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": self._auth, "Accept": "*/*",
                                                   "User-Agent": "fitvio"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                data = r.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthFailed("Intervals.icu rejected the API key — check it in Accounts") from None
            if e.code == 429:
                raise RateLimited("Intervals.icu rate limit — trying again later") from None
            raise IntervalsError(f"Intervals.icu answered {e.code} for {path}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise IntervalsError(f"Intervals.icu not reachable: {e}") from None
        if len(data) > MAX_BYTES:
            raise IntervalsError(f"Intervals.icu answer for {path} is larger than {MAX_BYTES // 2**20} MB")
        return data

    def json(self, path: str, **params):
        return json.loads(self._fetch(path, params))

    def athlete(self) -> dict:
        return self.json(f"/athlete/{self.athlete_id}")

    def activities(self, oldest: date, newest: date) -> list[dict]:
        return self.json(f"/athlete/{self.athlete_id}/activities", oldest=oldest.isoformat(),
                         newest=newest.isoformat())

    def wellness(self, oldest: date, newest: date) -> list[dict]:
        return self.json(f"/athlete/{self.athlete_id}/wellness", oldest=oldest.isoformat(),
                         newest=newest.isoformat())

    def fit_file(self, activity: dict) -> bytes:
        """The original file when it is a FIT (the device's own data, incl. RPE/feel), otherwise the FIT
        that Intervals.icu generates from its streams (for GPX/TCX uploads)."""
        aid = activity["id"]
        if str(activity.get("file_type") or "").lower() == "fit":
            data = self._fetch(f"/activity/{aid}/file", {})
            data = _gunzip(data)
            if data[8:12] == b".FIT":
                return data
        data = self._fetch(f"/activity/{aid}/fit-file", {})
        return _gunzip(data)


def _gunzip(data: bytes) -> bytes:
    """Unpack a gzipped file, but never beyond MAX_BYTES (a small gzip can unpack to gigabytes)."""
    if data[:2] != b"\x1f\x8b":
        return data
    try:
        d = zlib.decompressobj(wbits=31)
        out = d.decompress(data, MAX_BYTES)
    except zlib.error as e:
        raise IntervalsError(f"Intervals.icu sent a broken gzip file: {e}") from None
    if d.unconsumed_tail:
        raise IntervalsError(f"Intervals.icu file unpacks to more than {MAX_BYTES // 2**20} MB")
    return out


def _num(v) -> float | None:
    """A finite number from provider JSON, else None. json.loads turns 1e999 into inf, and an inf
    that reaches the database makes every API response containing it fail."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:  # an integer too large for a float
        return None
    return f if math.isfinite(f) else None


# --- download -----------------------------------------------------------------------

def _write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text() == text:
        return False
    path.write_text(text)
    return True


def download(base: Path, client: Client, full: bool = False, today: date | None = None,
             since: date | None = None, on_line: Callable[[str], None] = lambda s: None) -> dict:
    """Fetch new/changed activities, wellness and the athlete profile into `base`.

    A normal sync reads the last RECENT_DAYS, or back to `since` (the last successful sync) when that
    is longer ago — after the server was off for weeks, nothing in between is missed."""
    today = today or date.today()
    if full:
        oldest = today - timedelta(days=int(env("INTERVALS_HISTORY_DAYS") or FULL_HISTORY_DAYS))
    else:
        oldest = today - timedelta(days=RECENT_DAYS)
        if since and since - timedelta(days=1) < oldest:
            oldest = since - timedelta(days=1)
    newest = today + timedelta(days=1)
    acts_dir = base / "activities"
    acts_dir.mkdir(parents=True, exist_ok=True)

    athlete = client.athlete()
    _write_if_changed(base / "athlete.json", json.dumps(athlete, sort_keys=True))

    stats = {"listed": 0, "files": 0, "changed": 0, "strava_only": 0}
    for a in client.activities(oldest, newest):
        aid = str(a.get("id") or "")
        if not ID_RE.fullmatch(aid):
            continue
        stats["listed"] += 1
        if str(a.get("source") or "").upper() == "STRAVA":
            # Strava's terms keep these out of the API: Intervals.icu only returns a stub
            stats["strava_only"] += 1
            continue
        if _write_if_changed(acts_dir / f"{aid}.json", json.dumps(a, sort_keys=True)):
            stats["changed"] += 1
        fit = acts_dir / f"{aid}.fit"
        if not fit.exists():
            try:
                fit.write_bytes(client.fit_file(a))
                stats["files"] += 1
                on_line(f"{a.get('start_date_local', '')[:10]} {a.get('name') or a.get('type')}")
            except AuthFailed:
                raise
            except IntervalsError as e:  # e.g. a manual entry without a file: summary only
                log.info("intervals %s: no file for %s (%s)", base.name, aid, e)

    w_path = base / "wellness.json"
    wellness = json.loads(w_path.read_text()) if w_path.exists() else {}
    for w in client.wellness(oldest, newest):
        if w.get("id"):
            wellness[str(w["id"])[:10]] = w
    _write_if_changed(w_path, json.dumps(wellness, sort_keys=True))
    return stats


# --- reading (what the pipeline sees) -----------------------------------------------

def _local(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=None)


class IntervalsReader:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)
        self.acts_dir = self.base / "activities"

    @property
    def available(self) -> bool:
        return (self.base / "athlete.json").exists()

    def _summary(self, activity_id: str) -> dict | None:
        if not ID_RE.fullmatch(activity_id):
            return None
        path = self.acts_dir / f"{activity_id}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def _summaries(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in self.acts_dir.glob("*.json")] if self.acts_dir.exists() else []

    def activity_ids(self, since: datetime | None = None) -> list[tuple[str, str]]:
        out = [(str(a["id"]), a["start_date_local"]) for a in self._summaries() if a.get("start_date_local")]
        if since:
            out = [o for o in out if _local(o[1]) >= since]
        return sorted(out, key=lambda o: o[1])

    def changed_activity_ids(self, since: datetime) -> set[str]:
        ts = since.timestamp()
        return {p.stem for p in self.acts_dir.glob("*.json") if p.stat().st_mtime > ts} \
            if self.acts_dir.exists() else set()

    def load_activity(self, activity_id: str) -> ParsedActivity | None:
        a = self._summary(activity_id)
        if a is None:
            return None
        parsed = {"records": [], "laps": [], "lengths": [], "sets": [], "session": {}}
        fit = self.acts_dir / f"{activity_id}.fit"
        if fit.exists():
            try:
                parsed = parse_fit(fit)
            except Exception as e:  # a corrupt file must not stop the sync
                log.warning("FIT parse failed for %s: %s", fit, e)
        fs = parsed.get("session") or {}
        raw_sport, raw_sub = SPORTS.get(a.get("type") or "", (str(a.get("type") or "other").lower(), None))
        sport, indoor = normalize_sport(fs.get("sport") or raw_sport, fs.get("sub_sport") or raw_sub)
        indoor = indoor or bool(a.get("trainer"))
        rpe = _num(a.get("icu_rpe")) or _num(fs.get("rpe"))
        feel = a.get("feel")  # Intervals.icu: 1 (strong) … 5 (weak) → Fitvio 0..100, 100 = very strong
        feel = (5 - feel) * 25 if isinstance(feel, (int, float)) and 1 <= feel <= 5 else fs.get("feel")
        temp = a.get("average_weather_temp")
        return ParsedActivity(
            activity_id=str(activity_id),
            start_time=_local(a["start_date_local"]),
            sport=sport,
            raw_sport=a.get("type"),
            sub_sport=fs.get("sub_sport") or raw_sub,
            name=a.get("name"),
            duration_s=_num(a.get("moving_time")) or _num(a.get("elapsed_time")) or 0.0,
            distance_m=_num(a.get("distance")) or _num(a.get("icu_distance")),
            avg_hr=_num(a.get("average_heartrate")),
            max_hr=_num(a.get("max_heartrate")),
            ascent_m=_num(a.get("total_elevation_gain")),
            # weather at the activity (Intervals.icu's own lookup), never the wrist sensor
            avg_temp_c=plausible_temp(temp) if a.get("has_weather") else None,
            weather={"temp_c": temp, "station": "Intervals.icu weather"}
            if a.get("has_weather") and plausible_temp(temp) is not None else None,
            indoor=indoor,
            rpe=rpe if rpe and 1 <= rpe <= 10 else None,
            feel=feel,
            pool_length_m=fs.get("pool_length"),
            records=parsed["records"],
            laps=parsed["laps"],
            lengths=parsed.get("lengths", []),
            sets=parsed.get("sets", []),
            exercise_labels=parsed.get("exercise_labels", {}),
        )

    def _wellness(self) -> dict[str, dict]:
        path = self.base / "wellness.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def health_days(self, since: datetime) -> list[dict]:
        day0 = since.date().isoformat()
        out = []
        for day, w in sorted(self._wellness().items()):
            if day < day0:
                continue
            sleep = _num(w.get("sleepSecs"))
            row = {"day": day, "rhr": _num(w.get("restingHR")), "hrv_last_night": _num(w.get("hrv")),
                   "sleep_total_min": sleep / 60 if sleep else None, "sleep_score": _num(w.get("sleepScore")),
                   "weight_kg": _num(w.get("weight")), "steps": _num(w.get("steps")), "vo2max": _num(w.get("vo2max"))}
            row = {k: v for k, v in row.items() if v is not None}
            if len(row) > 1:
                out.append(row)
        return out

    def profile(self, today: date | None = None) -> dict[str, tuple[object, str]]:
        """{field: (value, source)} like profile.derive() does for Garmin. Missing or implausible
        settings are estimated from the data and labelled so; Accounts lets the person correct them."""
        today = today or date.today()
        path = self.base / "athlete.json"
        athlete = json.loads(path.read_text()) if path.exists() else {}
        found: dict[str, tuple[object, str]] = {}

        def put(field, value, source):
            if value not in (None, "", 0) and field not in found:
                found[field] = (value, source)

        name = athlete.get("name") or " ".join(filter(None, (athlete.get("firstname"), athlete.get("lastname"))))
        put("name", name, "Intervals.icu profile")
        sex = str(athlete.get("sex") or "").upper()
        put("sex", "female" if sex.startswith("F") else "male" if sex.startswith("M") else None,
            "Intervals.icu profile")
        put("weight_kg", athlete.get("icu_weight") or athlete.get("weight"), "Intervals.icu profile")

        def setting(kind: str, key: str):
            for s in athlete.get("sportSettings") or []:
                if kind in (s.get("types") or []) and s.get(key):
                    return s[key]
            return None

        mx = setting("Run", "max_hr") or setting("Ride", "max_hr")
        put("max_hr", mx if isinstance(mx, (int, float)) and 150 <= mx <= 230 else None,
            "max HR in your Intervals.icu settings")
        put("lthr", setting("Run", "lthr"), "LTHR in your Intervals.icu settings")
        put("ftp", setting("Ride", "ftp"), "FTP in your Intervals.icu settings")

        since = (today - timedelta(days=30)).isoformat()
        rest = [w["restingHR"] for d, w in self._wellness().items() if d >= since and (w.get("restingHR") or 0) > 25]
        if len(rest) >= 5:
            found["rest_hr"] = (round(median(rest)), "median resting HR from Intervals.icu, last 30 days")
        r = athlete.get("icu_resting_hr")
        put("rest_hr", r if isinstance(r, (int, float)) and 30 <= r <= 100 else None,
            "resting HR in your Intervals.icu settings")

        # Highest HR actually reached (3rd-highest activity max, to ignore optical spikes)
        year = (today - timedelta(days=365)).isoformat()
        maxes = sorted((a["max_heartrate"] for a in self._summaries()
                        if (a.get("start_date_local") or "") >= year and 120 <= (a.get("max_heartrate") or 0) <= 230),
                       reverse=True)
        if len(maxes) >= 3:
            observed = float(maxes[2])
            if "max_hr" not in found:
                found["max_hr"] = (observed, "estimated: highest HR in your activities (last 12 months)")
            elif observed > float(found["max_hr"][0]) + 2:
                found["max_hr"] = (observed, f"highest HR in your activities — above your Intervals.icu "
                                             f"setting ({found['max_hr'][0]:.0f}), which looks outdated")
        return found
