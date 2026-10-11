"""#32: the same training on a US-units and a metric Garmin account must look the same everywhere.

Both accounts go through GarminDB's real import (FIT files, activity summary + details JSON, weigh-ins),
which stores one in mi / ft / lb and the other in km / m / kg. Fitvio reads both back as SI, so every
API answer must be identical, and both must match what was recorded."""
import datetime as dt
import json
import math
import subprocess
import sys
from pathlib import Path

import garmindb
import pytest
from fastapi.testclient import TestClient

from fitvio import db, pipeline
from fitvio.api import main
from fitvio.config import load_config
from fitvio.sync.garmindb_runner import garmindb_cli

from .fitgen import activity_fit

TODAY = dt.date.today()
# (activity id, days ago, sport 1 run / 2 ride, km, ascent m, power W, laps, FIT file?)
PLAN = [("101", 20, 1, 8.42, 60.0, None, 1, True), ("102", 17, 1, 10.1, 210.5, None, 3, True),
        ("103", 15, 2, 32.6, 280.0, 190, 2, True), ("104", 12, 1, 6.62, 35.0, None, 1, False),
        ("105", 9, 1, 12.3, 150.0, None, 3, True), ("106", 6, 2, 41.2, 120.0, 205, 1, True),
        ("107", 3, 1, 9.51, 83.0, None, 1, True), ("108", 1, 1, 7.75, 22.0, None, 2, True)]
WEIGHTS = {(TODAY - dt.timedelta(days=d)).isoformat(): round(75 + 0.4 * (d % 3 - 1), 1) for d in range(0, 21, 4)}
WATCH = {"statute_us": 1, "metric": 0}


def build_account(root: Path, system: str) -> Path:
    cfg_dir, hd = root / "config", root / "HealthData"
    acts = hd / "FitFiles" / "Activities"
    for d in (cfg_dir, acts, hd / "Weight"):
        d.mkdir(parents=True)
    cfg = json.loads((Path(garmindb.__file__).parent / "GarminConnectConfig.json.example").read_text())
    cfg["directories"].update({"relative_to_home": False, "base_dir": str(hd)})
    cfg["settings"]["metric"] = True  # what Fitvio writes; GarminDB follows the account instead
    (cfg_dir / "GarminConnectConfig.json").write_text(json.dumps(cfg))
    (hd / "FitFiles" / "user-settings.json").write_text(json.dumps({"userData": {
        "measurementSystem": system, "gender": "MALE", "weight": 75000.0, "height": 180.0,
        "vo2MaxRunning": 58, "vo2MaxCycling": 55, "handedness": "RIGHT"}}))
    watch = {k: WATCH[system] for k in ("dist_setting", "speed_setting", "elev_setting", "temperature_setting")}
    for aid, ago, sport, km, ascent, power, laps, has_fit in PLAN:
        start = dt.datetime.combine(TODAY - dt.timedelta(days=ago), dt.time(6, 12))
        mins = int(km * (2.2 if sport == 2 else 5.6))
        kind = {"typeId": sport, "typeKey": "cycling" if sport == 2 else "running", "parentTypeId": 17}
        common = {"distance": km * 1000, "elevationGain": ascent, "elapsedDuration": mins * 60.0,
                  "movingDuration": mins * 60.0, "averageSpeed": km * 1000 / (mins * 60), "averageHR": 140,
                  "maxHR": 150}
        if has_fit:
            (acts / f"{aid}_ACTIVITY.fit").write_bytes(activity_fit(
                start.replace(tzinfo=dt.timezone.utc), mins, km * 1000, ascent, watch, sport=sport, power=power,
                laps=laps, temp_c=24))
        (acts / f"activity_{aid}.json").write_text(json.dumps({
            "activityId": int(aid), "activityName": "Ride" if sport == 2 else "Run", "activityType": kind,
            "eventType": {"typeId": 9, "typeKey": "uncategorized"}, "lapCount": laps,
            "startTimeLocal": start.strftime("%Y-%m-%d %H:%M:%S"), **common}))
        (acts / f"activity_details_{aid}.json").write_text(json.dumps({
            "activityId": int(aid), "metadataDTO": {}, "activityTypeDTO": kind,
            "summaryDTO": {"startTimeLocal": start.strftime("%Y-%m-%dT%H:%M:%S.0"), "directWorkoutRpe": 30, **common}}))
    for day, kg in WEIGHTS.items():
        (hd / "Weight" / f"weight_{day}.json").write_text(json.dumps({
            "startDate": day, "endDate": day, "dateWeightList": [{"weight": kg * 1000, "date": 0}]}))
    subprocess.run([sys.executable, garmindb_cli(), "-f", str(cfg_dir), "--all", "--import"], cwd=root,
                   check=True, capture_output=True)
    return cfg_dir


@pytest.fixture(scope="module")
def twins(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("twins")
    us, metric = build_account(tmp / "us", "statute_us"), build_account(tmp / "metric", "metric")
    (tmp / "users.json").write_text(json.dumps({"users": [
        {"id": "us", "name": "Twin", "garmindb_config_dir": str(us)},
        {"id": "metric", "name": "Twin", "garmindb_config_dir": str(metric)}]}))
    cfg = load_config(tmp / "users.json")
    cfg.db_path = tmp / "app.db"
    conn = db.connect(cfg.db_path)
    for u in cfg.users:
        pipeline.ingest(conn, u)
    main._cfg = cfg
    yield conn, TestClient(main.app), tmp
    main._cfg = None


def test_garmindb_really_stored_the_us_account_in_us_units(twins):
    import sqlite3
    _, _, tmp = twins
    rows = {}
    for who in ("us", "metric"):
        with sqlite3.connect(tmp / who / "HealthData" / "DBs" / "garmin_activities.db") as c:
            rows[who] = c.execute("SELECT distance FROM activities WHERE activity_id = '107'").fetchone()[0]
    assert rows["metric"] == pytest.approx(9.51) and rows["us"] == pytest.approx(9.51 / 1.609344, rel=1e-3)


def test_both_accounts_match_what_was_recorded(twins):
    conn, _, _ = twins
    for who in ("us", "metric"):
        got = {r["activity_id"]: (r["distance_m"], r["ascent_m"])
               for r in conn.execute("SELECT * FROM sessions WHERE user_id = ?", (who,))}
        assert set(got) == {p[0] for p in PLAN}, who  # the JSON-only activity (no FIT) too
        for aid, _, _, km, ascent, *_ in PLAN:
            assert got[aid][0] == pytest.approx(km * 1000, rel=1e-3), (who, aid)
            assert got[aid][1] == pytest.approx(ascent, abs=1), (who, aid)
        weights = {r["day"]: r["weight_kg"] for r in conn.execute(
            "SELECT day, weight_kg FROM health_days WHERE user_id = ? AND weight_kg IS NOT NULL", (who,))}
        assert weights == pytest.approx(WEIGHTS, abs=0.05), who


def _differences(a, b, where=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in set(a) | set(b) if k not in ("id", "user_id", "session_id", "created_at")
                for d in _differences(a.get(k), b.get(k), f"{where}.{k}")]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{where}: {len(a)} vs {len(b)} items"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _differences(x, y, f"{where}[{i}]")]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return [] if math.isclose(a, b, rel_tol=2e-3, abs_tol=0.05) else [f"{where}: {a} vs {b}"]
    if isinstance(a, str) and isinstance(b, str):
        return [] if a.replace("us:", "metric:") == b else [f"{where}: {a!r} vs {b!r}"]
    return [] if a == b else [f"{where}: {a!r} vs {b!r}"]


@pytest.mark.parametrize("path", ["ambient", "sessions", "session-types", "pmc", "health?days=30", "profile",
                                  "validation", "weather", "heat", "wind", "units"])
def test_every_view_is_the_same_for_both_accounts(twins, path):
    _, client, _ = twins
    us, metric = (client.get(f"/api/users/{who}/{path}") for who in ("us", "metric"))
    assert us.status_code == metric.status_code == 200
    assert _differences(us.json(), metric.json()) == []


def test_every_session_page_is_the_same_for_both_accounts(twins):
    _, client, _ = twins
    for aid, *_ in PLAN:
        us, metric = (client.get(f"/api/sessions/{who}:{aid}").json() for who in ("us", "metric"))
        assert _differences(us, metric) == [], aid
