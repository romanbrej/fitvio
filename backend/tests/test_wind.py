"""Head- and tailwind on outdoor runs: direction of travel from the FIT positions, the wind model, the
switch, and what the verdict says."""
import math
from datetime import datetime

import pytest

from fitvio.activity import ParsedActivity, Record
from fitvio.analytics import heat, wind
from fitvio.analytics.features import compute_features
from fitvio.ingest import fit_parser
from fitvio.models.sports import RunningModel

from .test_exclusions import client  # noqa: F401  (the API on made-up data)
from .test_heat_weather import USER

START = datetime(2026, 7, 14, 9, 0)
NORTH_20 = wind._vector(20, 0)  # 20 km/h at 10 m, from the north


def _hourly(kmh, deg, hours=("08:00", "09:00", "10:00", "11:00")):
    return {"temp_c": 12, "dew_point_c": 4, "wind_kmh": kmh, "wind_deg": deg, "source": "Open-Meteo",
            "hourly": [{"t": t, "temp_c": 12, "dew_point_c": 4, "wind_kmh": kmh, "wind_deg": deg} for t in hours]}


def out_and_back(minutes=50, effort=3.0, hr=145, headings=(0, 180), weather=None):
    """A flat run at constant effort (constant HR): out one way, back the other, the speed set by the wind."""
    at = wind.WindAt(weather, START)
    recs, dist, n = [], 0.0, minutes * 60
    for i in range(n):
        heading = headings[0] if i < n / 2 else headings[1]
        v = effort / wind.still_air_factor(effort, heading, at(i)) if at else effort
        dist += v
        recs.append(Record(t=float(i), hr=hr, speed=v, distance=dist, altitude=100.0, heading=heading))
    return ParsedActivity(activity_id="w1", start_time=START, sport="running", name="Run", duration_s=n,
                          distance_m=dist, records=recs, weather=weather, track=[(0, 52.4, 9.7)])


# --- direction of travel ----------------------------------------------------------------------

def _walk(bearing, steps, step_m=3.0, lat=52.4, lon=9.7):
    out = []
    for _ in range(steps):
        out.append((lat, lon))
        lat += step_m * math.cos(math.radians(bearing)) / 111195
        lon += step_m * math.sin(math.radians(bearing)) / (111195 * math.cos(math.radians(lat)))
    return out


@pytest.mark.parametrize("bearing", [0, 90, 225, 350])
def test_heading_from_positions(bearing):
    h = fit_parser._Heading()
    got = [h.push(p) for p in _walk(bearing, 20)]
    assert got[:8] == [None] * 8                                 # under 25 m so far: no direction yet
    assert all(abs((g - bearing + 180) % 360 - 180) < 0.5 for g in got[10:])
    assert len(h.recent) <= 11                                   # only the last ~25 m are held


def test_no_heading_when_standing_or_without_fix():
    h = fit_parser._Heading()
    assert [h.push((52.4, 9.7)) for _ in range(30)] == [None] * 30
    assert h.push(None) is None


def test_fit_record_gets_heading_but_no_position():
    assert "heading" in Record.__dataclass_fields__
    assert not {"lat", "lon", "position", "position_lat"} & set(Record.__dataclass_fields__)


# --- the model --------------------------------------------------------------------------------

def test_still_air_is_unchanged():
    assert wind.still_air_factor(3.0, 0, (0.0, 0.0)) == pytest.approx(1.0)


def test_headwind_costs_more_than_a_tailwind_gives_back():
    head = wind.still_air_factor(3.0, 0, NORTH_20) - 1      # running north into it
    tail = wind.still_air_factor(3.0, 180, NORTH_20) - 1    # running south with it
    cross = wind.still_air_factor(3.0, 90, NORTH_20) - 1
    assert 0.02 < head < 0.05                                # ~3.5 %: a 20 km/h forecast is ~10 km/h at 1 m
    assert -0.02 < tail < 0
    assert abs(tail) < head / 2
    assert 0 < cross < 0.01                                  # a crosswind still adds air speed
    assert wind.still_air_factor(5.0, 0, NORTH_20) > wind.still_air_factor(3.0, 0, NORTH_20)  # faster: more drag


def test_correction_is_capped():
    gale = wind._vector(150, 0)
    assert wind.still_air_factor(2.0, 0, gale) == pytest.approx(1 + wind.MAX_FACTOR)
    assert wind.still_air_factor(2.0, 180, gale) == pytest.approx(1 - wind.MAX_FACTOR)


def test_wind_between_hours_turns_the_short_way():
    w = {"hourly": [{"t": "09:00", "wind_kmh": 18, "wind_deg": 350}, {"t": "10:00", "wind_kmh": 18, "wind_deg": 10}]}
    east, north = wind.WindAt(w, START)(1800)
    assert north > 4.5 and abs(east) < 0.1                    # half way: from the north, not the south


def test_platform_reading_as_fallback():
    at = wind.WindAt({"temp_c": 20, "wind_kmh": 18, "wind_dir": "ene"}, START)
    east, north = at(600)
    assert math.degrees(math.atan2(east, north)) == pytest.approx(67.5)
    assert not wind.WindAt({"temp_c": 20}, START)
    assert not wind.WindAt(None, START)


def test_nothing_to_correct_without_headings_or_wind():
    act = out_and_back(weather=_hourly(20, 0))
    speeds = [r.speed for r in act.records]
    assert wind.adjusted_speeds(act.records, speeds, None, START) is None
    for r in act.records:
        r.heading = None
    assert wind.adjusted_speeds(act.records, speeds, _hourly(20, 0), START) is None


# --- features, the adjustment, the switch -----------------------------------------------------------

def test_wind_corrects_efficiency_not_drift():
    """Out into a headwind, home with it behind: the run looks slow (the net loss of wind) and its drift
    negative. Efficiency is corrected back to the steady effort it was; drift stays as run — it comes from
    heat and fluid loss, and on real runs the hourly 11 km wind made it less comparable, not more."""
    windy = compute_features(out_and_back(weather=_hourly(25, 0)), USER)["features"]
    calm = compute_features(out_and_back(weather=_hourly(0, 0)), USER)["features"]
    assert windy["ef"] < calm["ef"]
    assert windy["wind"]["ef"] == pytest.approx(calm["ef"], rel=0.003)
    assert windy["wind"]["pct"] > 0.3
    assert "decoupling" not in windy["wind"]
    assert calm.get("wind", {}).get("pct") in (None, 0)


def loop(minutes=50, laps=10, weather=None):
    """Round and round: every direction in both halves (a 5-min square, ten times)."""
    act = out_and_back(minutes=minutes, weather=weather)
    side = minutes * 60 / laps / 4
    for r in act.records:
        r.heading = float(int(r.t // side) % 4 * 90)
    return act


def test_halves_headwind_tells_out_and_back_from_loop():  # for wind-report's out-and-back column
    from fitvio.analytics import physio
    w = _hourly(25, 0)

    def halves(act):
        return wind.halves_headwind_kmh(physio.steady_slice(act.records), w, START)
    assert halves(out_and_back(weather=w)) < -40      # into the north wind, home with it behind: ~2 × 25 km/h
    assert abs(halves(loop(weather=w))) < wind.DRIFT_HALVES_KMH   # half laps left over
    assert abs(halves(out_and_back(weather=w, headings=(90, 270)))) < 1  # out and back across the wind


def test_indoor_and_rides_get_no_wind():
    act = out_and_back(weather=_hourly(25, 0))
    act.indoor = True
    assert "wind" not in compute_features(act, USER)["features"]
    ride = out_and_back(weather=_hourly(25, 0))
    ride.sport = "cycling"
    assert "wind" not in compute_features(ride, USER)["features"]


def test_adjust_starts_from_still_air_when_on():
    f = compute_features(out_and_back(weather=_hourly(25, 0)), USER)["features"]
    s = {"sport": "running", "indoor": 0, "start_time": START.isoformat(), "duration_s": 3000, "features": f}
    resp = heat.priors()
    heat.adjust([s], resp, wind=True)
    assert f["ef_adj"] == pytest.approx(f["wind"]["ef"] * (1 + f["heat_adj_pct"] / 100), abs=1e-4)
    assert f["decoupling_adj"] == pytest.approx(f["decoupling"], abs=1e-4)   # drift as run
    assert f["wind_adj_pct"] == round(f["wind"]["pct"], 2)
    heat.adjust([s], resp, wind=False)
    assert f["ef_adj"] == pytest.approx(f["ef"] * (1 + f["heat_adj_pct"] / 100), abs=1e-4)
    assert f["decoupling_adj"] == pytest.approx(f["decoupling"], abs=1e-4)
    assert f["wind_adj_pct"] == 0


def test_verdict_says_how_much_was_wind():
    f = compute_features(out_and_back(weather=_hourly(25, 270)), USER)["features"]

    def note():
        return next((n["text"] for n in RunningModel().context_notes({"features": f}, None, None, {})
                     if n["kind"] == "wind"), None)
    f["wind_adj_pct"] = 1.4
    assert note() == "Windy: 25 km/h (Open-Meteo) — efficiency adjusted +1.4 % for head- and tailwind"
    f["wind_adj_pct"] = -0.8
    assert note() == "Windy: 25 km/h (Open-Meteo) — efficiency adjusted −0.8 % for head- and tailwind"
    f["wind_adj_pct"] = 0.3
    assert note() is None


def _runs(conn):
    from fitvio import pipeline
    return [s for s in pipeline.user_sessions(conn, "a") if s["sport"] == "running" and s["features"].get("wind")]


def test_switch_off_and_on_rewrites_without_reading_files(client, monkeypatch):  # noqa: F811
    from fitvio import db, pipeline, weather
    from fitvio.api import main
    conn = db.connect(main._cfg.db_path)
    runs = _runs(conn)
    assert runs, "the demo runs are out-and-backs in the wind"
    assert all(s["features"]["wind_adj_pct"] == round(s["features"]["wind"]["pct"], 2) for s in runs)
    monkeypatch.setattr(pipeline, "reader_for", lambda user: pytest.fail("no file is read again"))

    assert client.put("/api/users/a/wind", json={"wind": False}).status_code == 403  # home network only
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    assert client.put("/api/users/nobody/wind", json={"wind": False}).status_code == 404
    assert client.put("/api/users/a/wind", json={"wind": "no"}).status_code == 422
    off = client.put("/api/users/a/wind", json={"wind": False}).json()
    assert off["wind"] is False and off["recomputed"] > 0
    assert client.get("/api/users/a/wind").json() == {"wind": False}
    assert weather.wind_enabled(conn, "a") is False
    for s in _runs(conn):
        f = s["features"]
        assert f["wind_adj_pct"] == 0
        assert f["ef_adj"] == pytest.approx(f["ef"] * (1 + f["heat_adj_pct"] / 100), abs=1e-4)
    assert client.put("/api/users/a/wind", json={"wind": False}).json()["recomputed"] == 0  # no change, no work
    assert client.put("/api/users/a/wind", json={"wind": True}).json()["wind"] is True
    for s in _runs(conn):
        f = s["features"]
        assert f["ef_adj"] == pytest.approx(f["wind"]["ef"] * (1 + f["heat_adj_pct"] / 100), abs=1e-4)



def test_activity_has_real_and_weather_adjusted_pace():
    """Real pace stays as run; the adjusted one is what the same effort would have given in cool still air."""
    f = compute_features(out_and_back(weather={**_hourly(25, 0), "temp_c": 26, "dew_point_c": 20,
                                               "hourly": [{**h, "temp_c": 26, "dew_point_c": 20}
                                                          for h in _hourly(25, 0)["hourly"]]}), USER)["features"]
    s = {"sport": "running", "indoor": 0, "start_time": START.isoformat(), "duration_s": 3000, "features": f}
    heat.adjust([s], heat.priors(), wind=True)
    assert f["heat_adj_pct"] > 1
    assert f["wind"]["avg_speed"] > f["avg_speed"]             # the wind cost pace overall
    assert f["avg_speed_adj"] == pytest.approx(f["wind"]["avg_speed"] * (1 + f["heat_adj_pct"] / 100), abs=1e-4)
    heat.adjust([s], heat.priors(), wind=False)
    assert f["avg_speed_adj"] == pytest.approx(f["avg_speed"] * (1 + f["heat_adj_pct"] / 100), abs=1e-4)


def test_interval_reps_are_compared_weather_adjusted():
    """Reps out into the wind and back: rep pace and rep efficiency get each lap's still-air pace, and the
    interval verdict compares only the adjusted values."""
    from fitvio.activity import Lap
    act = out_and_back(weather=_hourly(25, 0))
    act.name = "Intervals 6x3'"
    for r in act.records:  # 3 min hard / 3 min easy, the lap's speed from its records
        r.speed *= 1.25 if 300 <= r.t < 2700 and int((r.t - 300) // 180) % 2 == 0 else 1.0
    act.laps = []
    for start, dur in [(0, 300), *[(300 + i * 180, 180) for i in range(13)], (2640, 360)]:
        seg = [r for r in act.records if start <= r.t < start + dur]
        act.laps.append(Lap(start_s=start, duration_s=dur, avg_speed=sum(r.speed for r in seg) / len(seg),
                            avg_hr=145))
    feats = compute_features(act, USER)
    f = feats["features"]
    assert feats["session_type"] == "intervals" and f["work_speed"]
    assert f["wind"]["work_speed"] != pytest.approx(f["work_speed"], rel=1e-4)
    s = {"sport": "running", "indoor": 0, "start_time": START.isoformat(), "duration_s": 3000,
         "session_type": "intervals", "features": f}
    heat.adjust([s], heat.priors(), wind=True)
    assert f["work_speed_adj"] == pytest.approx(f["wind"]["work_speed"] * (1 + f["heat_adj_pct"] / 100), abs=1e-4)
    specs = {m.key: m for m in RunningModel().interval_metrics}
    assert specs["work_speed"].value(s) == f["work_speed_adj"] and specs["work_ef"].value(s) == f["work_ef_adj"]
