"""Intervals.icu as a data source: download, reading, profile, sync and the Accounts connect flow."""
import json
import time
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from fitvio import config, db, pipeline
from fitvio.api import main
from fitvio.config import UserConfig
from fitvio.ingest import intervals_reader as icu
from fitvio.sync import intervals_runner

from .test_analytics import steady_records

TODAY = date(2026, 10, 7)
FIT = b"\x0e\x10\x00\x00\x00\x00\x00\x00.FIT" + b"\x00" * 20  # header only: the parser is faked below

ATHLETE = {"id": "i123", "name": "Sam Fitbit", "sex": "F", "icu_weight": 61.5, "icu_resting_hr": 52,
           "sportSettings": [{"types": ["Run", "TrailRun"], "max_hr": 188, "lthr": 170},
                             {"types": ["Ride"], "ftp": 210, "max_hr": None}]}


def activity(aid, day, typ="Run", **kw):
    return {"id": aid, "start_date_local": f"{day}T07:30:00", "type": typ, "name": f"{typ} {day}",
            "moving_time": 2700, "elapsed_time": 2800, "distance": 8000.0, "average_heartrate": 145,
            "max_heartrate": 172, "total_elevation_gain": 40.0, "file_type": "fit", "source": "GARMIN_CONNECT",
            "icu_rpe": 4, "feel": 2, **kw}


class FakeIntervals:
    """Answers like Intervals.icu; records every request."""

    def __init__(self, activities=(), wellness=(), athlete=ATHLETE, fail=None):
        self.activities, self.wellness, self.athlete, self.fail = list(activities), list(wellness), athlete, fail
        self.calls = []

    def __call__(self, path, params):
        self.calls.append((path, params))
        if self.fail:
            raise self.fail
        if path == "/athlete/i123":
            return json.dumps(self.athlete).encode()
        if path == "/athlete/i123/activities":
            return json.dumps(self.activities).encode()
        if path == "/athlete/i123/wellness":
            return json.dumps(self.wellness).encode()
        if path.endswith("/file") or path.endswith("/fit-file"):
            return FIT
        raise AssertionError(path)

    def client(self):
        return icu.Client("i123", "secret-key-123", fetch=self)


@pytest.fixture(autouse=True)
def fake_fit(monkeypatch):
    """A 45-min steady run at 150 bpm for every FIT file."""
    monkeypatch.setattr(icu, "parse_fit", lambda path: {
        "records": steady_records(minutes=45, speed=1000 / 400, hr=150), "laps": [], "lengths": [], "sets": [],
        "session": {"sport": "running", "sub_sport": "generic"}})


def test_athlete_id_accepts_what_people_paste():
    assert icu.normalize_athlete_id("i123") == "i123"
    assert icu.normalize_athlete_id(" 123 ") == "i123"
    assert icu.normalize_athlete_id("https://intervals.icu/athlete/i123/") == "i123"
    with pytest.raises(ValueError):
        icu.normalize_athlete_id("../../etc")


def test_api_key_is_sent_as_basic_auth_and_never_in_the_url():
    seen = {}
    client = icu.Client("i123", "secret-key-123", fetch=lambda p, q: seen.setdefault("x", (p, q)) and b"{}")
    client.athlete()
    assert "secret" not in json.dumps(seen)
    assert client._auth == "Basic QVBJX0tFWTpzZWNyZXQta2V5LTEyMw=="  # API_KEY:secret-key-123


def test_credentials_file_is_private(tmp_path):
    icu.save_credentials(tmp_path / "u", "i123", "secret-key-123")
    assert (tmp_path / "u" / "credentials.json").stat().st_mode & 0o077 == 0
    assert (tmp_path / "u").stat().st_mode & 0o077 == 0
    assert icu.load_credentials(tmp_path / "u") == ("i123", "secret-key-123")


def test_download_keeps_files_and_marks_only_changed_summaries(tmp_path):
    api = FakeIntervals([activity("i1", "2026-10-01"), activity("i2", "2026-10-03", source="STRAVA"),
                         activity("../x", "2026-10-04")],
                        [{"id": "2026-10-06", "restingHR": 50, "hrv": 61.0, "sleepSecs": 27000, "steps": 9000}])
    stats = icu.download(tmp_path, api.client(), full=True, today=TODAY)
    assert stats == {"listed": 2, "files": 1, "changed": 1, "strava_only": 1}   # Strava stubs and bad ids skipped
    assert (tmp_path / "activities" / "i1.fit").read_bytes() == FIT
    assert not list(tmp_path.glob("**/x*"))
    oldest = dict(api.calls[1][1])["oldest"]
    assert oldest == "2021-10-08"                                                 # full: 5 years

    api.calls.clear()
    stats = icu.download(tmp_path, api.client(), today=TODAY)
    assert (stats["files"], stats["changed"]) == (0, 0)                           # nothing downloaded twice
    assert dict(api.calls[1][1])["oldest"] == "2026-09-23"                        # normal: last 2 weeks

    api.activities[0]["name"] = "Renamed in Intervals"
    assert icu.download(tmp_path, api.client(), today=TODAY)["changed"] == 1


def test_first_download_can_be_limited_for_a_quick_test(tmp_path, monkeypatch):
    monkeypatch.setenv("FITVIO_INTERVALS_HISTORY_DAYS", "30")
    api = FakeIntervals()
    icu.download(tmp_path, api.client(), full=True, today=TODAY)
    assert dict(api.calls[1][1])["oldest"] == "2026-09-07"


def test_after_downtime_sync_catches_up_since_last_success(tmp_path, monkeypatch):
    api = FakeIntervals([activity("i1", "2026-09-10")])
    user = make_user(tmp_path, monkeypatch, api)
    conn = db.connect(tmp_path / "app.db")
    oldest = lambda: [dict(q)["oldest"] for p, q in api.calls if p.endswith(("/activities", "/wellness"))]  # noqa: E731
    assert icu.download(user.intervals_path, api.client(), today=TODAY)["listed"] == 1   # no last sync: 14 days
    assert oldest() == ["2026-09-23", "2026-09-23"]
    # the server was off: last success 30 days ago → read back to the day before it
    db.upsert(conn, "sync_status", {"user_id": "sam", "last_success": "2026-09-07T08:00:00"})
    api.calls.clear()
    monkeypatch.setattr(icu, "date", type("D", (date,), {"today": staticmethod(lambda: TODAY)}))
    assert intervals_runner.run_sync(conn, user)
    assert oldest() == ["2026-09-06", "2026-09-06"]                                       # the day before it
    # synced yesterday: the normal 14-day window, nothing downloaded twice
    api.calls.clear()
    db.upsert(conn, "sync_status", {"user_id": "sam", "last_success": "2026-10-06T08:00:00"})
    assert intervals_runner.run_sync(conn, user)
    assert oldest() == ["2026-09-23", "2026-09-23"]
    assert not [p for p, _ in api.calls if "/activity/" in p]


def test_original_file_falls_back_to_intervals_fit(tmp_path):
    api = FakeIntervals([activity("i1", "2026-10-01", file_type="gpx")])
    icu.download(tmp_path, api.client(), today=TODAY)
    assert [p for p, _ in api.calls if "/activity/" in p] == ["/activity/i1/fit-file"]


def test_reader_maps_activity_and_wellness(tmp_path):
    api = FakeIntervals([activity("i1", "2026-10-01", trainer=True, has_weather=True, average_weather_temp=24.0)],
                        [{"id": "2026-10-06", "restingHR": 50, "hrv": 61.0, "sleepSecs": 27000, "sleepScore": 80,
                          "weight": 61.0, "steps": 9000}, {"id": "2026-10-05", "comments": "only a note"}])
    icu.download(tmp_path, api.client(), today=TODAY)
    r = icu.IntervalsReader(tmp_path)
    assert r.available and r.activity_ids() == [("i1", "2026-10-01T07:30:00")]
    act = r.load_activity("i1")
    assert (act.sport, act.indoor, act.duration_s, act.distance_m, act.rpe, act.feel) == \
        ("running", True, 2700.0, 8000.0, 4.0, 75)                                # feel 2 ("good") → 75
    assert act.weather == {"temp_c": 24.0, "source": "Intervals.icu"} and act.records
    assert r.load_activity("../../credentials") is None
    assert r.health_days(datetime(2026, 10, 1)) == [
        {"day": "2026-10-06", "rhr": 50, "hrv_last_night": 61.0, "sleep_total_min": 450.0, "sleep_score": 80,
         "weight_kg": 61.0, "steps": 9000}]


def test_profile_from_settings_or_estimated(tmp_path):
    api = FakeIntervals([activity(f"i{i}", f"2026-09-{10 + i:02d}", max_heartrate=180 + i) for i in range(4)],
                        [{"id": f"2026-10-0{d}", "restingHR": 48 + d} for d in range(1, 6)])
    icu.download(tmp_path, api.client(), today=TODAY)
    found = icu.IntervalsReader(tmp_path).profile(today=TODAY)
    assert found["max_hr"][0] == 188 and "Intervals.icu settings" in found["max_hr"][1]
    assert found["rest_hr"] == (51, "median resting HR from Intervals.icu, last 30 days")
    assert (found["name"][0], found["sex"][0], found["lthr"][0], found["ftp"][0], found["weight_kg"][0]) == \
        ("Sam Fitbit", "female", 170, 210, 61.5)

    # nothing set in Intervals.icu: estimated from the data, and labelled so
    api.athlete = {"id": "i123", "name": "Sam"}
    api.wellness = []
    (tmp_path / "wellness.json").unlink()
    icu.download(tmp_path, api.client(), today=TODAY)
    found = icu.IntervalsReader(tmp_path).profile(today=TODAY)
    assert found["max_hr"] == (181.0, "estimated: highest HR in your activities (last 12 months)")
    assert "rest_hr" not in found                                                  # → default, "set it in Accounts"


def make_user(tmp_path, monkeypatch, api):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    user = UserConfig(id="sam", intervals_dir="data/intervals/sam")
    icu.save_credentials(user.intervals_path, "i123", "secret-key-123")
    monkeypatch.setattr(intervals_runner, "client_for", lambda u: api.client())
    return user


def test_sync_and_ingest_measure_pace_at_reference_hr(tmp_path, monkeypatch):
    api = FakeIntervals([activity("i1", "2026-10-01"), activity("i2", "2026-10-03")])
    user = make_user(tmp_path, monkeypatch, api)
    conn = db.connect(tmp_path / "app.db")
    ok, result = intervals_runner.sync_user(conn, user, full=True)
    assert ok and result["activities"] == 2 and result["profile"]["max_hr"] == 188
    s = pipeline.user_sessions(conn, "sam")[-1]
    assert s["sport"] == "running" and s["features"]["ref_hr"] == round(52 + 0.7 * (188 - 52))  # 147
    assert s["features"]["speed_at_ref_hr"] == pytest.approx(2.5, rel=0.02)          # the 6:40 /km held at ~150
    assert conn.execute("SELECT last_error FROM sync_status WHERE user_id='sam'").fetchone()[0] is None


def test_revoked_key_is_reported_not_crashed(tmp_path, monkeypatch):
    api = FakeIntervals(fail=icu.AuthFailed("Intervals.icu rejected the API key — check it in Accounts"))
    user = make_user(tmp_path, monkeypatch, api)
    conn = db.connect(tmp_path / "app.db")
    assert intervals_runner.run_sync(conn, user) is False
    assert "rejected the API key" in conn.execute("SELECT last_error FROM sync_status").fetchone()[0]


def test_daytime_check_syncs_every_ten_minutes(tmp_path, monkeypatch):
    from fitvio.sync import activity_watch as w
    api = FakeIntervals([activity("i1", "2026-10-01")])
    user = make_user(tmp_path, monkeypatch, api)
    cfg = config.AppConfig(users=[user, UserConfig(id="demo")])
    conn = db.connect(tmp_path / "app.db")
    synced = []
    fake = lambda c, u: (synced.append(u.id), intervals_runner.run_sync(c, u))[1:] + (None,)  # noqa: E731
    noon = datetime(2026, 10, 7, 12, 0)
    assert w.check_intervals(conn, cfg, noon, sync=fake) == {"sam": "synced"}
    conn.execute("UPDATE sync_status SET last_attempt = ?", (noon.isoformat(),))
    assert w.check_intervals(conn, cfg, datetime(2026, 10, 7, 12, 5), sync=fake) == {}     # not due yet
    assert w.check_intervals(conn, cfg, datetime(2026, 10, 7, 12, 10), sync=fake) == {"sam": "synced"}
    assert w.check_intervals(conn, cfg, datetime(2026, 10, 7, 3, 0), sync=fake) == {}       # night
    assert synced == ["sam", "sam"]


# --- Accounts: connect from the UI --------------------------------------------------

def wait_for(client, job_id, phases, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["phase"] in phases:
            return j
        time.sleep(0.02)
    raise AssertionError(f"job stuck in {j['phase']}")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FITVIO_CONFIG", str(tmp_path / "users.json"))
    monkeypatch.setenv("FITVIO_DB", str(tmp_path / "app.db"))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    main.reset_config()
    api = FakeIntervals([activity("i1", "2026-10-01")])
    monkeypatch.setattr(intervals_runner, "client_for", lambda u: api.client())
    monkeypatch.setattr(icu, "Client", lambda a, k, fetch=None: _RealClient(a, k, fetch=api))
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    c = TestClient(main.app)
    c.api = api
    yield c
    main.app.dependency_overrides.clear()
    main.reset_config()


_RealClient = icu.Client


def test_connect_intervals_from_the_ui(client, tmp_path):
    r = client.post("/api/accounts/intervals", json={"athlete_id": "https://intervals.icu/athlete/i123",
                                                     "api_key": "secret-key-123"})
    assert r.status_code == 200, r.text
    job = wait_for(client, r.json()["id"], ("done", "error"))
    assert job["phase"] == "done", job
    assert job["user_id"] == "sam_fitbit" and job["result"]["activities"] == 1
    users = json.loads((tmp_path / "users.json").read_text())["users"]
    assert users == [{"id": "sam_fitbit", "color": "#3B82F6", "intervals_dir": "data/intervals/sam_fitbit"}]
    assert "secret" not in json.dumps(job) and "secret" not in (tmp_path / "users.json").read_text()
    acc = client.get("/api/accounts").json()[0]
    assert acc["source"] == "intervals" and acc["activities"] == 1
    # the same athlete twice is refused
    r = client.post("/api/accounts/intervals", json={"athlete_id": "i123", "api_key": "secret-key-123"})
    assert r.status_code == 409


def test_wrong_key_leaves_nothing_behind(client, tmp_path):
    client.api.fail = icu.AuthFailed("Intervals.icu rejected the API key — check it in Accounts")
    r = client.post("/api/accounts/intervals", json={"athlete_id": "i123", "api_key": "wrong-key-123"})
    job = wait_for(client, r.json()["id"], ("done", "error"))
    assert job["phase"] == "error" and "rejected the API key" in job["error"]
    assert not (tmp_path / "users.json").exists() and not list((tmp_path / "data").glob("intervals/*"))


def test_own_max_hr_wins_and_reprocesses(client, tmp_path):
    r = client.post("/api/accounts/intervals", json={"athlete_id": "i123", "api_key": "secret-key-123"})
    wait_for(client, r.json()["id"], ("done",))
    r = client.put("/api/users/sam_fitbit/profile", json={"max_hr": 196, "rest_hr": None})
    assert r.status_code == 200
    assert r.json()["profile"]["max_hr"] == {"value": 196.0, "source": "set by you"}
    wait_for(client, r.json()["job"]["id"], ("done",))
    conn = db.connect(tmp_path / "app.db")
    s = pipeline.user_sessions(conn, "sam_fitbit")[-1]
    assert s["features"]["ref_hr"] == round(52 + 0.7 * (196 - 52))                      # zones followed
    assert client.put("/api/users/sam_fitbit/profile", json={"max_hr": 300}).status_code == 422


def test_own_max_hr_survives_syncs_until_you_accept_the_new_one(client, tmp_path):
    from fitvio import profile
    r = client.post("/api/accounts/intervals", json={"athlete_id": "i123", "api_key": "secret-key-123"})
    wait_for(client, r.json()["id"], ("done",))
    r = client.put("/api/users/sam_fitbit/profile", json={"max_hr": 196, "rest_hr": 50})
    wait_for(client, r.json()["job"]["id"], ("done",))
    assert "suggested" not in r.json()["profile"]["max_hr"]          # 188 was on screen when you typed 196

    def mine():
        return next(a for a in client.get("/api/accounts").json() if a["id"] == "sam_fitbit")["profile"]

    conn = db.connect(tmp_path / "app.db")
    user = config.load_config(tmp_path / "users.json").user("sam_fitbit")

    def sync_max_hr(bpm):  # the Intervals.icu setting changes and a sync stores it
        athlete = {**ATHLETE, "sportSettings": [{"types": ["Run"], "max_hr": bpm, "lthr": 172}]}
        (user.data_dir / "athlete.json").write_text(json.dumps(athlete))
        profile.refresh(conn, user, icu.IntervalsReader(user.data_dir))

    # yours still counts; the new value is only offered
    sync_max_hr(201)
    p = mine()
    assert p["max_hr"]["value"] == 196.0 and p["max_hr"]["source"] == "set by you"
    assert p["max_hr"]["suggested"]["value"] == 201
    assert profile.resolve(conn, user).max_hr == 196.0

    # "Keep mine": not offered again …
    r = client.post("/api/users/sam_fitbit/profile/dismiss", json={"field": "max_hr"})
    assert r.status_code == 200 and "suggested" not in r.json()["profile"]["max_hr"]
    assert client.post("/api/users/sam_fitbit/profile/dismiss", json={"field": "rest_hr"}).status_code == 422
    # … until the source changes again
    sync_max_hr(203)
    assert mine()["max_hr"]["suggested"]["value"] == 203

    # "Use 203": the source's value counts, your own resting HR stays
    r = client.put("/api/users/sam_fitbit/profile", json={"max_hr": None, "rest_hr": 50})
    assert r.json()["profile"]["max_hr"]["value"] == 203 and r.json()["profile"]["rest_hr"]["source"] == "set by you"
    wait_for(client, r.json()["job"]["id"], ("done",))


# --- readiness without Garmin ---------------------------------------------------------

def test_readiness_estimate_from_hrv_rhr_sleep_and_form():
    from fitvio.coach import estimate_readiness
    base = {"hrv_last_night": 70.0, "rhr": 50.0}
    usual = {"day": "2026-10-07", "hrv_last_night": 70, "rhr": 50, "sleep_score": 80}
    r = estimate_readiness(usual, base, 0.0, TODAY)
    assert (r["score"], r["level"], r["feedback"], r["source"]) == (68, "MODERATE", "FITVIO_NORMAL", "fitvio")  # .3·60 + .2·70 + .25·80 + .25·65
    good = estimate_readiness({**usual, "hrv_last_night": 80, "rhr": 47, "sleep_score": 92}, base, 12.0, TODAY)
    assert good["level"] == "HIGH" and good["score"] > r["score"]
    bad = estimate_readiness({**usual, "hrv_last_night": 55, "rhr": 54}, base, -25.0, TODAY)
    assert bad["level"] in ("LOW", "POOR") and bad["feedback"] == "FITVIO_HRV_LOW"
    assert bad["factors"]["hrv"] < 30
    # no data from last night yet, or too little to say anything: no score
    assert estimate_readiness({**usual, "day": "2026-10-06"}, base, 0.0, TODAY) is None
    assert estimate_readiness({"day": "2026-10-07", "sleep_score": 80}, base, 0.0, TODAY) is None


def test_intervals_user_gets_estimate_and_no_body_battery(tmp_path, monkeypatch):
    from fitvio import wall
    api = FakeIntervals([activity("i1", "2026-10-01")],
                        [{"id": (TODAY.fromordinal(TODAY.toordinal() - d)).isoformat(), "restingHR": 50,
                          "hrv": 70.0, "sleepScore": 80} for d in range(10)])
    user = make_user(tmp_path, monkeypatch, api)
    monkeypatch.setattr(icu, "date", type("D", (date,), {"today": staticmethod(lambda: TODAY)}))
    conn = db.connect(tmp_path / "app.db")
    intervals_runner.sync_user(conn, user, full=True)
    monkeypatch.setattr(wall, "date", type("D", (date,), {"today": staticmethod(lambda: TODAY)}))
    a = wall.ambient(conn, config.AppConfig(users=[user]), "sam")
    assert a["source"] == "intervals"
    assert a["readiness"]["source"] == "fitvio" and a["readiness"]["level"] in ("MODERATE", "HIGH")
    assert a["health_latest"].get("bb_max") is None
