import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from healthdash import db, profile
from healthdash.config import UserConfig


def garmindb_dir(tmp_path, rhr_values=(50, 52, 51, 49, 50, 53), activity_maxes=(185, 188, 191, 170),
                 gender="FEMALE"):
    base = tmp_path / "HealthData"
    (base / "FitFiles" / "Activities").mkdir(parents=True)
    (base / "DBs").mkdir()
    (base / "FitFiles" / "social-profile.json").write_text(json.dumps({"displayName": "abc123", "fullName": "Alex Runner"}))
    (base / "FitFiles" / "user-settings.json").write_text(json.dumps({"userData": {"gender": gender, "lactateThresholdHeartRate": 168}}))
    (base / "FitFiles" / "Activities" / "1_ACTIVITY.fit").write_bytes(b"")
    today = datetime.now().date()
    with sqlite3.connect(base / "DBs" / "garmin.db") as c:
        c.execute("CREATE TABLE resting_hr (day TEXT, resting_heart_rate REAL)")
        c.executemany("INSERT INTO resting_hr VALUES (?, ?)",
                      [((today - timedelta(days=i)).isoformat(), v) for i, v in enumerate(rhr_values)])
    with sqlite3.connect(base / "DBs" / "garmin_activities.db") as c:
        c.execute("CREATE TABLE activities (activity_id TEXT, start_time TEXT, max_hr INTEGER)")
        c.executemany("INSERT INTO activities VALUES (?, ?, ?)",
                      [(str(i), (datetime.now() - timedelta(days=i)).isoformat(sep=" "), m)
                       for i, m in enumerate(activity_maxes)])
    return base


@pytest.fixture
def watch(monkeypatch):
    """Stand-in for the zones_target/user_profile messages inside the FIT files."""
    data = {"zones_target": {"max_heart_rate": 192, "threshold_heart_rate": 170, "functional_threshold_power": 245},
            "user_profile": {"gender": "female", "resting_heart_rate": 58}}
    from healthdash.ingest import fit_parser
    monkeypatch.setattr(fit_parser, "parse_fit_profile", lambda path: data)
    return data


def test_everything_comes_from_garmin(tmp_path, watch):
    found = profile.derive(garmindb_dir(tmp_path))
    assert found["name"][0] == "Alex Runner"
    assert found["sex"][0] == "female"
    assert found["max_hr"] == (192, "HR zones on your watch")
    assert found["rest_hr"][0] == 50  # measured daily resting HR beats the watch setting (58)
    assert found["ftp"][0] == 245
    assert found["lthr"][0] == 168  # user settings come first


def test_outdated_watch_max_hr_is_replaced_by_measured(tmp_path, watch):
    watch["zones_target"]["max_heart_rate"] = 180
    found = profile.derive(garmindb_dir(tmp_path, activity_maxes=(195, 196, 197, 150)))
    assert found["max_hr"][0] == 195
    assert "outdated" in found["max_hr"][1]


def test_without_watch_settings_uses_measured_max(tmp_path, monkeypatch):
    from healthdash.ingest import fit_parser
    monkeypatch.setattr(fit_parser, "parse_fit_profile", lambda path: {})
    found = profile.derive(garmindb_dir(tmp_path))
    assert found["max_hr"][0] == 185  # 3rd highest of 191/188/185


def test_resolve_precedence_and_refresh_change_detection(tmp_path, watch):
    conn = db.connect(tmp_path / "app.db")
    base = garmindb_dir(tmp_path)
    u = UserConfig(id="u")
    assert profile.resolve(conn, u).max_hr == profile.DEFAULTS["max_hr"]  # nothing known yet
    assert profile.refresh(conn, u, base) is True  # first profile → process history
    r = profile.resolve(conn, u)
    assert (r.max_hr, r.rest_hr, r.sex, r.display_name, r.initials) == (192, 50, "female", "Alex Runner", "AR")
    assert profile.refresh(conn, u, base) is False  # nothing changed
    watch["zones_target"]["max_heart_rate"] = 196
    assert profile.refresh(conn, u, base) is True  # zones moved → reprocess
    # an explicit override in users.json still wins
    assert profile.resolve(conn, UserConfig(id="u", max_hr=200)).max_hr == 200
    assert profile.describe(conn, u)["max_hr"]["source"] == "HR zones on your watch"
