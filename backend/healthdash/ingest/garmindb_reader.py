"""Read-only access to one user's GarminDB data directory.

Layout (per GarminDB):  <base_dir>/DBs/garmin.db, garmin_activities.db
                        <base_dir>/FitFiles/Activities/<activity_id>*.fit
The generated GarminDB config uses metric units, so distance is km and speed km/h.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ..activity import Lap, ParsedActivity, Record, normalize_sport
from .fit_parser import parse_fit

log = logging.getLogger(__name__)

FEEL = {"very strong": 100, "strong": 75, "normal": 50, "weak": 25, "very weak": 0}
EFFORT = {"maximum": 10, "extremely hard": 9, "very hard": 7, "hard": 5, "somewhat hard": 4,
          "moderate": 3, "light": 2, "very light": 1, "none": 0}


def base_dir_from_config(config_dir: Path) -> Path:
    cfg = json.loads((config_dir / "GarminConnectConfig.json").read_text())
    d = cfg.get("directories", {})
    base = d.get("base_dir", "HealthData")
    if d.get("relative_to_home", True):
        return Path.home() / base
    return Path(base).expanduser()


def _ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _secs(t: str | None) -> float:
    """GarminDB Time columns: 'HH:MM:SS[.ffffff]'."""
    if not t:
        return 0.0
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace(" ", "T").split("+")[0])


class GarminDbReader:
    def __init__(self, base_dir: Path):
        self.base = Path(base_dir)
        self.db_dir = self.base / "DBs"
        self.fit_dir = self.base / "FitFiles" / "Activities"

    @property
    def available(self) -> bool:
        return (self.db_dir / "garmin_activities.db").exists()

    def activity_ids(self, since: datetime | None = None) -> list[tuple[str, str]]:
        with _ro(self.db_dir / "garmin_activities.db") as c:
            q = "SELECT activity_id, start_time FROM activities WHERE start_time IS NOT NULL"
            args: tuple = ()
            if since:
                q += " AND start_time >= ?"
                args = (since.isoformat(sep=" "),)
            return [(r["activity_id"], r["start_time"]) for r in c.execute(q + " ORDER BY start_time", args)]

    def find_fit(self, activity_id: str) -> Path | None:
        hits = sorted(self.fit_dir.glob(f"{activity_id}*.fit")) if self.fit_dir.exists() else []
        return hits[0] if hits else None

    def load_activity(self, activity_id: str) -> ParsedActivity | None:
        with _ro(self.db_dir / "garmin_activities.db") as c:
            a = c.execute("SELECT * FROM activities WHERE activity_id = ?", (activity_id,)).fetchone()
            if a is None:
                return None
            a = dict(a)
            fit_path = self.find_fit(activity_id)
            parsed = None
            if fit_path:
                try:
                    parsed = parse_fit(fit_path)
                except Exception as e:  # corrupt/partial files must not stop the sync
                    log.warning("FIT parse failed for %s: %s", fit_path, e)
            if parsed is None:
                parsed = self._records_from_db(c, activity_id, _dt(a["start_time"]))

        fs = parsed.get("session") or {}
        sport, indoor = normalize_sport(a.get("sport") or fs.get("sport"), a.get("sub_sport") or fs.get("sub_sport"))
        feel = fs.get("feel") if fs.get("feel") is not None else FEEL.get((a.get("self_eval_feel") or "").lower())
        rpe = fs.get("rpe") if fs.get("rpe") is not None else EFFORT.get((a.get("self_eval_effort") or "").lower())
        act = ParsedActivity(
            activity_id=str(activity_id),
            start_time=_dt(a["start_time"]),
            sport=sport,
            raw_sport=a.get("sport"),
            sub_sport=a.get("sub_sport"),
            name=a.get("name"),
            duration_s=_secs(a.get("moving_time")) or _secs(a.get("elapsed_time")),
            distance_m=(a["distance"] * 1000) if a.get("distance") else None,
            avg_hr=a.get("avg_hr"),
            max_hr=a.get("max_hr"),
            ascent_m=a.get("ascent") if a.get("ascent") is not None else fs.get("ascent"),
            avg_temp_c=a.get("avg_temperature") if a.get("avg_temperature") is not None else fs.get("avg_temp"),
            indoor=indoor,
            rpe=rpe,
            feel=feel,
            pool_length_m=fs.get("pool_length"),
            records=parsed["records"],
            laps=parsed["laps"],
            lengths=parsed.get("lengths", []),
            sets=parsed.get("sets", []),
            exercise_labels=parsed.get("exercise_labels", {}),
        )
        return act

    @staticmethod
    def _records_from_db(c: sqlite3.Connection, activity_id: str, start: datetime) -> dict:
        recs = []
        for r in c.execute("SELECT * FROM activity_records WHERE activity_id = ? ORDER BY record", (activity_id,)):
            if not r["timestamp"]:
                continue
            recs.append(Record(
                t=(_dt(r["timestamp"]) - start).total_seconds(),
                hr=r["hr"],
                speed=r["speed"] / 3.6 if r["speed"] is not None else None,
                distance=r["distance"] * 1000 if r["distance"] is not None else None,
                altitude=r["altitude"],
                cadence=r["cadence"],
                temperature=r["temperature"],
            ))
        laps = []
        for lap in c.execute("SELECT * FROM activity_laps WHERE activity_id = ? ORDER BY lap", (activity_id,)):
            laps.append(Lap(
                start_s=(_dt(lap["start_time"]) - start).total_seconds() if lap["start_time"] else 0.0,
                duration_s=_secs(lap["moving_time"]) or _secs(lap["elapsed_time"]),
                distance_m=lap["distance"] * 1000 if lap["distance"] else None,
                avg_hr=lap["avg_hr"],
                avg_speed=lap["avg_speed"] / 3.6 if lap["avg_speed"] else None,
            ))
        return {"records": recs, "laps": laps, "lengths": [], "sets": [], "session": {}}

    # --- health -----------------------------------------------------------
    def health_days(self, since: datetime) -> list[dict]:
        path = self.db_dir / "garmin.db"
        if not path.exists():
            return []
        day0 = since.date().isoformat()
        days: dict[str, dict] = {}

        def put(day, **kw):
            d = days.setdefault(str(day)[:10], {"day": str(day)[:10]})
            d.update({k: v for k, v in kw.items() if v is not None})

        with _ro(path) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "resting_hr" in tables:
                for r in c.execute("SELECT day, resting_heart_rate FROM resting_hr WHERE day >= ?", (day0,)):
                    put(r["day"], rhr=r["resting_heart_rate"])
            if "daily_summary" in tables:
                for r in c.execute("SELECT * FROM daily_summary WHERE day >= ?", (day0,)):
                    put(r["day"], stress_avg=r["stress_avg"], bb_max=r["bb_max"], bb_min=r["bb_min"],
                        steps=r["steps"])
                    if r["rhr"] and "rhr" not in days.get(str(r["day"])[:10], {}):
                        put(r["day"], rhr=r["rhr"])
            if "sleep" in tables:
                for r in c.execute("SELECT * FROM sleep WHERE day >= ?", (day0,)):
                    put(r["day"], sleep_total_min=_secs(r["total_sleep"]) / 60 or None,
                        sleep_deep_min=_secs(r["deep_sleep"]) / 60, sleep_light_min=_secs(r["light_sleep"]) / 60,
                        sleep_rem_min=_secs(r["rem_sleep"]) / 60, sleep_awake_min=_secs(r["awake"]) / 60,
                        sleep_score=r["score"])
            if "hrv" in tables:
                for r in c.execute("SELECT * FROM hrv WHERE day >= ?", (day0,)):
                    put(r["day"], hrv_last_night=r["last_night_avg"], hrv_weekly=r["weekly_avg"],
                        hrv_baseline_low=r["baseline_low"], hrv_baseline_high=r["baseline_upper"],
                        hrv_status=r["status"])
            if "weight" in tables:
                for r in c.execute("SELECT day, weight FROM weight WHERE day >= ?", (day0,)):
                    put(r["day"], weight_kg=r["weight"])
        # VO2max lives on the activity (running/cycling tables)
        with _ro(self.db_dir / "garmin_activities.db") as c:
            for tbl in ("steps_activities", "cycle_activities"):
                try:
                    q = (f"SELECT a.start_time, s.vo2_max FROM {tbl} s JOIN activities a USING(activity_id) "
                         "WHERE s.vo2_max IS NOT NULL AND a.start_time >= ?")
                    for r in c.execute(q, (day0,)):
                        put(r["start_time"], vo2max=r["vo2_max"])
                except sqlite3.OperationalError:
                    pass
        return sorted(days.values(), key=lambda d: d["day"])


def default_since(days: int = 400) -> datetime:
    return datetime.now() - timedelta(days=days)
