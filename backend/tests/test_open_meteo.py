"""Hourly weather from Open-Meteo: start point, cache, failures, which weather a session uses, backfill.
Never calls Open-Meteo: answers come from a recorded response (fixtures/open_meteo)."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from fitvio import db, pipeline, weather
from fitvio.activity import ParsedActivity
from fitvio.analytics.features import compute_features
from fitvio.api import main
from fitvio.ingest import fit_parser
from fitvio.ingest import intervals_reader as icu
from fitvio.sync import intervals_runner, open_meteo

from .test_analytics import steady_records
from .test_exclusions import client  # noqa: F401  (the API on made-up data)
from .test_heat_weather import USER
from .test_intervals import FakeIntervals, activity, make_user

RECORDED = json.loads((Path(__file__).parent / "fixtures/open_meteo/hannover_2026-07-14_15.json").read_text())
HOME = (52.4, 9.7)
NOW = datetime(2026, 10, 8, 20, 30)


class FakeOpenMeteo:
    """Answers every request with the recorded two days (14–15 Jul 2026, Hannover); records the URLs."""

    def __init__(self, fail=None):
        self.urls, self.fail = [], fail

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise self.fail
        q = parse_qs(urlparse(url).query)
        first, last = q["start_date"][0], q["end_date"][0]
        h = RECORDED["hourly"]
        idx = [i for i, t in enumerate(h["time"]) if first <= t[:10] <= last]
        return json.dumps({**RECORDED, "hourly": {k: [v[i] for i in idx] for k, v in h.items()}}).encode()


TRACK = [(0, *HOME)]


def run_act(start=datetime(2026, 7, 14, 7, 15), minutes=45, weather_=None, track=TRACK, indoor=False):
    return ParsedActivity(activity_id="r1", start_time=start, sport="running", name="Run", duration_s=minutes * 60,
                          distance_m=8000, indoor=indoor, records=steady_records(minutes=minutes, hr=150),
                          weather=weather_, track=list(track))


# --- start point ---------------------------------------------------------------------------------

class Frame:
    def __init__(self, **fields):
        self.fields = fields

    def has_field(self, n):
        return n in self.fields

    def get_value(self, n):
        return self.fields[n]


def test_fit_position_is_converted_from_semicircles_and_rounded():
    lat, lon = 52.3922968, 9.7345720  # a house: never kept
    frame = Frame(position_lat=round(lat / fit_parser.SEMICIRCLE_DEG), position_long=round(lon / fit_parser.SEMICIRCLE_DEG))
    assert fit_parser._position(frame) == (52.4, 9.7)
    assert fit_parser._position(Frame(position_lat=None, position_long=None)) is None
    assert fit_parser._position(Frame()) is None


@pytest.mark.parametrize("lat, lon, expected", [(52.3923, 9.7346, (52.4, 9.7)), (-0.04, -0.04, (0.0, 0.0)),
                                               (0, 0, None), (91, 0, None), ("x", 1, None), (None, None, None),
                                               (float("nan"), 1, None)])
def test_rounded(lat, lon, expected):
    assert open_meteo.rounded(lat, lon) == expected


def test_track_samples_every_30_min_and_only_new_cells():
    track = []
    for t, pos in [(0, (52.4, 9.7)), (600, (52.5, 9.7)),      # 10 min: too soon
                   (1800, (52.4, 9.7)),                       # 30 min, same cell: dropped
                   (2400, (52.5, 9.6)), (3000, (52.6, 9.5)),  # 40 min: new cell; 50 min: too soon after it
                   (4200, (52.6, 9.5)), (4300, None)]:        # 70 min: new cell; no fix: ignored
        open_meteo.add_to_track(track, t, pos)
    assert track == [(0, 52.4, 9.7), (2400, 52.5, 9.6), (4200, 52.6, 9.5)]
    assert open_meteo.cell_at(track, -1800) == (52.4, 9.7)                         # before the start: the start
    assert open_meteo.cell_at(track, 2399) == (52.4, 9.7) and open_meteo.cell_at(track, 3600) == (52.5, 9.6)


# --- cache and failures --------------------------------------------------------------------------

def test_one_request_per_place_and_range_stored_per_day(tmp_path):
    om = FakeOpenMeteo()
    r = open_meteo.fetch_missing(tmp_path, {HOME: {date(2026, 7, 14), date(2026, 7, 15)}}, fetch=om, now=NOW,
                                 sleep=lambda s: None)
    assert (r["requests"], r["days"], r["error"]) == (1, 2, None)
    q = parse_qs(urlparse(om.urls[0]).query)
    assert q["latitude"] == ["52.4"] and q["longitude"] == ["9.7"] and q["timezone"] == ["auto"]
    assert om.urls[0].startswith(open_meteo.FORECAST_API)
    stored = json.loads((tmp_path / "om_52.4_9.7_2026-07-14.json").read_text())
    assert len(stored["time"]) == 24 and stored["complete"] is True
    assert open_meteo.missing(tmp_path, TRACK, datetime(2026, 7, 14, 7), 3600) == {}


def test_old_sessions_use_the_archive_and_ranges_split_at_the_switch():
    assert open_meteo.url_for(HOME, date(2019, 5, 1), date(2019, 5, 3)).startswith(open_meteo.ARCHIVE_API)
    days = [date(2021, 12, 30), date(2021, 12, 31), date(2022, 1, 1), date(2022, 1, 5), date(2022, 3, 1)]
    assert open_meteo._ranges(days) == [(date(2021, 12, 30), date(2021, 12, 31)), (date(2022, 1, 1), date(2022, 1, 5)),
                                        (date(2022, 3, 1), date(2022, 3, 1))]


@pytest.mark.parametrize("error", [open_meteo.WeatherUnavailable("Open-Meteo answered 429"),
                                   open_meteo.WeatherUnavailable("Open-Meteo not reachable: timed out")])
def test_failures_are_never_cached_and_stop_the_run(tmp_path, error):
    om = FakeOpenMeteo(fail=error)
    needs = {HOME: {date(2026, 7, 14)}, (48.1, 11.6): {date(2026, 7, 15)}}
    r = open_meteo.fetch_missing(tmp_path, needs, fetch=om, now=NOW, sleep=lambda s: None)
    assert r["requests"] == 1 and r["error"] and r["pending"] == 2                # stopped at the first failure
    assert not list(tmp_path.glob("om_*"))                                          # retried on the next sync


def test_no_data_is_remembered_but_not_for_today(tmp_path):
    empty = lambda url: b"{}"  # noqa: E731  (what a 400 "outside the data" becomes)
    open_meteo.fetch_range(tmp_path, HOME, date(2026, 10, 1), date(2026, 10, 8), fetch=empty, now=NOW)
    assert json.loads((tmp_path / "om_52.4_9.7_2026-10-01.json").read_text()) == {}
    assert not (tmp_path / "om_52.4_9.7_2026-10-08.json").exists()               # today: ask again later
    assert not (tmp_path / "om_52.4_9.7_2026-10-07.json").exists()


def test_today_is_only_cached_up_to_when_it_was_fetched(tmp_path):
    morning = datetime(2026, 7, 14, 9, 0)
    open_meteo.fetch_range(tmp_path, HOME, date(2026, 7, 14), date(2026, 7, 14), fetch=FakeOpenMeteo(), now=morning)
    assert open_meteo.missing(tmp_path, TRACK, datetime(2026, 7, 14, 7, 15), 45 * 60) == {}
    # the evening run must not get the forecast that was cached in the morning
    assert open_meteo.missing(tmp_path, TRACK, datetime(2026, 7, 14, 19, 0), 45 * 60) == {HOME: {date(2026, 7, 14)}}


# --- reading a session ---------------------------------------------------------------------------

def test_session_weather_covers_only_its_hours(tmp_path):
    open_meteo.fetch_range(tmp_path, HOME, date(2026, 7, 14), date(2026, 7, 15), fetch=FakeOpenMeteo(), now=NOW)
    w = open_meteo.read_session(tmp_path, TRACK, datetime(2026, 7, 14, 7, 15), 45 * 60)
    h = RECORDED["hourly"]
    assert [x["t"] for x in w["hourly"]] == ["07:00", "08:00"]                   # 06:45 … 08:30
    assert w["temp_c"] == pytest.approx((h["temperature_2m"][7] + h["temperature_2m"][8]) / 2, abs=0.05)
    assert w["dew_point_c"] == pytest.approx((h["dew_point_2m"][7] + h["dew_point_2m"][8]) / 2, abs=0.05)
    assert w["source"] == "Open-Meteo" and w["wind_dir"] in open_meteo.COMPASS
    # past midnight: hours from both days
    late = open_meteo.read_session(tmp_path, TRACK, datetime(2026, 7, 14, 23, 20), 60 * 60)
    assert [x["t"] for x in late["hourly"]] == ["23:00", "00:00"]
    assert open_meteo.read_session(tmp_path, TRACK, datetime(2026, 7, 16, 7), 3600) is None  # not fetched
    assert open_meteo.read_session(tmp_path, [], datetime(2026, 7, 14, 7), 3600) is None


def test_a_long_ride_takes_each_hour_where_it_was(tmp_path):
    """3 h ride heading away from home: every hour comes from the cell the rider was in."""
    away, far = (52.3, 9.5), (52.2, 9.3)
    ride = [(0, *HOME), (3600, *away), (7200, *far)]
    start = datetime(2026, 7, 14, 9, 0)
    assert open_meteo.missing(tmp_path, ride, start, 3 * 3600) == {
        HOME: {date(2026, 7, 14)}, away: {date(2026, 7, 14)}, far: {date(2026, 7, 14)}}
    om = FakeOpenMeteo()
    for cell in (HOME, far):
        open_meteo.fetch_range(tmp_path, cell, date(2026, 7, 14), date(2026, 7, 14), fetch=om, now=NOW)
    assert open_meteo.read_session(tmp_path, ride, start, 3 * 3600) is None          # the middle cell is missing
    open_meteo.fetch_range(tmp_path, away, date(2026, 7, 14), date(2026, 7, 14), fetch=om, now=NOW)
    for cell, shift in ((away, 1.0), (far, 2.0)):  # make each cell's hours tell apart
        path = tmp_path / f"om_{cell[0]:.1f}_{cell[1]:.1f}_2026-07-14.json"
        raw = json.loads(path.read_text())
        raw["temperature_2m"] = [t + shift for t in raw["temperature_2m"]]
        path.write_text(json.dumps(raw))
    w = open_meteo.read_session(tmp_path, ride, start, 3 * 3600)
    h = RECORDED["hourly"]["temperature_2m"]
    got = {x["t"]: (x["lat"], x["lon"], x["temp_c"]) for x in w["hourly"]}
    assert got == {"09:00": (*HOME, h[9]), "10:00": (*away, h[10] + 1), "11:00": (*far, h[11] + 2),
                   "12:00": (*far, h[12] + 2)}


def test_compass_points():
    assert open_meteo.compass(350) == "N" and open_meteo.compass(10) == "N" and open_meteo.compass(180) == "S"


# --- which weather a session uses ----------------------------------------------------------------

GARMIN_BOX = {"temp_c": 28.0, "dew_point_c": 20.0, "station": "Town", "desc": "Fair", "source": "Garmin"}


def test_open_meteo_wins_over_the_garmin_box_and_the_box_is_the_fallback(tmp_path):
    open_meteo.fetch_range(tmp_path, HOME, date(2026, 7, 14), date(2026, 7, 15), fetch=FakeOpenMeteo(), now=NOW)
    act = run_act(weather_=dict(GARMIN_BOX))
    weather.apply(act, tmp_path, True)
    assert act.weather["source"] == "Open-Meteo" and act.weather["desc"] == "Fair"
    assert act.avg_temp_c == act.weather["temp_c"]
    for act in (run_act(start=datetime(2026, 7, 20, 7), weather_=dict(GARMIN_BOX)),   # not fetched
                run_act(weather_=dict(GARMIN_BOX), indoor=True),                         # treadmill
                run_act(weather_=dict(GARMIN_BOX), track=[])):                           # no GPS
        weather.apply(act, tmp_path, True)
        assert act.weather == GARMIN_BOX
    off = run_act(weather_=dict(GARMIN_BOX))
    weather.apply(off, tmp_path, False)                                                  # switched off
    assert off.weather == GARMIN_BOX


def test_outdoor_rides_get_the_weather_and_indoor_rides_dont(tmp_path):
    open_meteo.fetch_range(tmp_path, HOME, date(2026, 7, 14), date(2026, 7, 15), fetch=FakeOpenMeteo(), now=NOW)
    road, trainer = run_act(), run_act(indoor=True)
    for act in (road, trainer):
        act.sport, act.sub_sport = "cycling", "road_biking"
        weather.apply(act, tmp_path, True)
    assert road.weather["source"] == "Open-Meteo" and trainer.weather is None
    f = compute_features(road, USER)["features"]
    assert f["weather"]["dew_point_c"] is not None and f["track"] == [[0, 52.4, 9.7]]
    assert open_meteo.missing(tmp_path, TRACK, datetime(2026, 7, 20, 9), 3 * 3600)  # a ride's days are fetched too


def test_intervals_session_gets_a_real_dew_point(tmp_path):
    """Intervals.icu only gives a temperature: the heat correction guessed the dew point as temp − 10."""
    open_meteo.fetch_range(tmp_path, HOME, date(2026, 7, 14), date(2026, 7, 15), fetch=FakeOpenMeteo(), now=NOW)
    start = datetime(2026, 7, 14, 16, 0)
    guessed = run_act(start=start, weather_={"temp_c": 27.0, "source": "Intervals.icu"})
    filled = run_act(start=start, weather_={"temp_c": 27.0, "source": "Intervals.icu"})
    weather.apply(filled, tmp_path, True)
    assert filled.weather["dew_point_c"] is not None
    a, b = compute_features(guessed, USER)["features"], compute_features(filled, USER)["features"]
    assert a["heat_load_pct"] != b["heat_load_pct"] and b["track"] == [[0, 52.4, 9.7]]


@pytest.mark.parametrize("w, text", [({"source": "Open-Meteo"}, "Open-Meteo"),
                                     ({"source": "Garmin", "station": "Town"}, "Garmin station Town"),
                                     ({"station": "Town"}, "Garmin station Town"),  # stored before the source field
                                     ({"source": "Intervals.icu"}, "Intervals.icu"), (None, None)])
def test_label(w, text):
    assert weather.label(w) == text


# --- sync: today's run first, then the history --------------------------------------------------

@pytest.fixture
def gps_fit(monkeypatch):
    monkeypatch.setattr(icu, "parse_fit", lambda path: {
        "records": steady_records(minutes=45, speed=1000 / 400, hr=150), "laps": [], "lengths": [], "sets": [],
        "session": {"sport": "running", "sub_sport": "generic"}, "track": TRACK})


def sources(conn):
    return [(s["features"].get("weather") or {}).get("source") for s in pipeline.user_sessions(conn, "sam")]


def test_sync_fetches_weather_and_backfills_with_verdicts_recomputed(tmp_path, monkeypatch, gps_fit):
    api = FakeIntervals([activity("i1", "2026-07-14", has_weather=True, average_weather_temp=20.0),
                         activity("i2", "2026-07-15", has_weather=True, average_weather_temp=21.0)])
    user = make_user(tmp_path, monkeypatch, api)
    conn = db.connect(tmp_path / "app.db")
    om = FakeOpenMeteo(fail=open_meteo.WeatherUnavailable("offline"))
    monkeypatch.setattr(open_meteo, "_urlopen", om)
    ok, result = intervals_runner.sync_user(conn, user, full=True)
    assert ok and sources(conn) == ["Intervals.icu", "Intervals.icu"]               # offline: verdicts anyway
    assert result["weather"]["error"]
    conn.execute("UPDATE verdicts SET first_shown_at = '2026-07-15T09:00:00' WHERE user_id = 'sam'")
    conn.commit()

    om.fail = None                                                                    # back online
    result = pipeline.ingest(conn, user)
    assert result["weather"]["updated"] == 2 and sources(conn) == ["Open-Meteo", "Open-Meteo"]
    assert len(om.urls) == 2                                                          # one failed + one range
    rows = conn.execute("SELECT first_shown_at, created_at FROM verdicts WHERE user_id = 'sam'").fetchall()
    assert all(r["first_shown_at"] == "2026-07-15T09:00:00" for r in rows)            # the wall doesn't pop up again
    assert all(r["created_at"] > "2026-07-15" for r in rows)

    calls = len(om.urls)
    assert pipeline.ingest(conn, user)["weather"]["updated"] == 0 and len(om.urls) == calls  # nothing left to do


def test_switched_off_gives_exactly_the_platform_weather_verdicts(tmp_path, monkeypatch, gps_fit):
    api = FakeIntervals([activity(f"i{d}", f"2026-07-{d:02d}", has_weather=True, average_weather_temp=26.0)
                         for d in range(1, 16)])
    user = make_user(tmp_path, monkeypatch, api)
    conn = db.connect(tmp_path / "app.db")
    weather.set_enabled(conn, "sam", False)
    intervals_runner.sync_user(conn, user, full=True)
    before = conn.execute("SELECT session_id, verdict, score FROM verdicts ORDER BY session_id").fetchall()
    assert set(sources(conn)) == {"Intervals.icu"}

    monkeypatch.setattr(open_meteo, "_urlopen", FakeOpenMeteo())
    weather.set_enabled(conn, "sam", True)
    pipeline.ingest(conn, user, full=True)
    assert "Open-Meteo" in sources(conn)

    weather.set_enabled(conn, "sam", False)                                           # roll back
    pipeline.ingest(conn, user, full=True)
    after = conn.execute("SELECT session_id, verdict, score FROM verdicts ORDER BY session_id").fetchall()
    assert [tuple(r) for r in after] == [tuple(r) for r in before] and set(sources(conn)) == {"Intervals.icu"}


# --- the setting ----------------------------------------------------------------------------------

def test_setting_api(client):  # noqa: F811
    assert client.get("/api/users/a/weather").json() == {"open_meteo": True}         # on by default
    assert client.put("/api/users/a/weather", json={"open_meteo": False}).status_code == 403  # home network only
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    assert client.put("/api/users/nobody/weather", json={"open_meteo": False}).status_code == 404
    assert client.put("/api/users/a/weather", json={"open_meteo": "no"}).status_code == 422
    assert client.put("/api/users/a/weather", json={"open_meteo": False}).json()["open_meteo"] is False
    assert client.get("/api/users/a/weather").json() == {"open_meteo": False}


def test_sync_learns_the_heat_response_and_redoes_verdicts_when_it_moves(tmp_path, monkeypatch, gps_fit):
    """Through a whole sync: the heat load comes from Open-Meteo's hours, the response is learned and saved,
    and when a later sync moves it, every run is rewritten and judged again without popping up."""
    from fitvio import heat_response
    from fitvio.analytics import heat
    api = FakeIntervals([activity("i1", "2026-07-14", has_weather=True, average_weather_temp=20.0),
                         activity("i2", "2026-07-15", has_weather=True, average_weather_temp=21.0)])
    user = make_user(tmp_path, monkeypatch, api)
    conn = db.connect(tmp_path / "app.db")
    monkeypatch.setattr(open_meteo, "_urlopen", FakeOpenMeteo())
    ok, result = intervals_runner.sync_user(conn, user, full=True)
    runs = pipeline.user_sessions(conn, "sam")
    assert ok and all(s["features"]["heat_load_pct"] > 0 and s["features"]["weather"]["source"] == "Open-Meteo"
                      for s in runs)
    assert heat_response.learned_yet(conn, "sam")                       # saved once, still the standard
    assert heat_response.current(conn, "sam")["running"]["k"] == 1.0
    assert all(s["features"]["heat_adj_pct"] == s["features"]["heat_load_pct"] for s in runs)
    conn.execute("UPDATE verdicts SET first_shown_at = '2026-07-15T09:00:00' WHERE user_id = 'sam'")
    conn.commit()

    # a later sync brings a run; this time the fit says heat costs this person twice the standard
    api.activities.append(activity("i3", (date.today() - timedelta(days=1)).isoformat(), has_weather=True,
                                   average_weather_temp=21.0))  # recent: a normal sync picks it up
    real = heat.fit_response
    monkeypatch.setattr(heat, "fit_response", lambda ss, sport: {**real(ss, sport), "k": 2.0}
                        if sport == "running" else real(ss, sport))
    ok, result = intervals_runner.sync_user(conn, user)
    assert ok and result["activities"] == 1 and result["heat_relearned"] == ["running"], result
    runs = pipeline.user_sessions(conn, "sam")
    assert len(runs) == 3 and all(s["features"]["heat_adj_pct"] == round(2 * s["features"]["heat_load_pct"], 2)
                                  for s in runs)                         # old and new runs alike
    rows = conn.execute("SELECT session_id, first_shown_at FROM verdicts WHERE user_id = 'sam'").fetchall()
    assert all(r["first_shown_at"] == "2026-07-15T09:00:00" for r in rows if not r["session_id"].endswith("i3"))
    assert intervals_runner.sync_user(conn, user)[1]["heat_relearned"] == []  # nothing new: nothing relearned
