"""Heat adjustment from Garmin's activity weather + heat acclimation (not the wrist sensor)."""
import json
from datetime import datetime

import pytest

from healthdash.activity import ParsedActivity, plausible_temp
from healthdash.analytics import physio
from healthdash.analytics.features import compute_features
from healthdash.config import UserConfig
from healthdash.models.sports import RunningModel
from healthdash.sync import garmin_extras

from .test_analytics import steady_records

USER = UserConfig(id="u", name="Test", max_hr=190, rest_hr=50)

# what Garmin returned for the user's run on 28 Sep (Town station)
GARMIN_WEATHER = {"temp": 75, "apparentTemp": 75, "dewPoint": 59, "relativeHumidity": 57, "windSpeed": 3,
                  "windDirectionCompassPoint": "ene", "weatherStationDTO": {"name": "Town"},
                  "weatherTypeDTO": {"desc": "Fair"}}


@pytest.mark.parametrize("value, expected", [(127, None), (-128, None), (255, None), (70, None),
                                             (None, None), (22.5, 22.5), (-5, -5.0)])
def test_fit_no_value_markers_are_not_temperatures(value, expected):
    assert plausible_temp(value) == expected


def test_heat_table_uses_temperature_plus_dew_point():
    assert physio.heat_adjustment(None, None) == 0.0                        # no weather → no adjustment
    assert physio.heat_adjustment(12, 5) == 0.0                             # 53.6 + 41 °F: cool
    t, dp = physio.f_to_c(75), physio.f_to_c(59)                            # 75 + 59 = 134 °F
    assert physio.heat_adjustment(t, dp) == 3.0
    assert physio.heat_adjustment(t, dp, acclimation_pct=100) == 1.5       # fully acclimated: half
    assert physio.heat_adjustment(t, dp, acclimation_pct=8) == pytest.approx(2.88)
    assert physio.heat_adjustment(35, 28) == 10.0                           # 95 + 82 = 177 °F
    assert physio.heat_adjustment(37, 30) == physio.HEAT_MAX_PCT            # 99 + 86 °F: very hot & humid


def test_weather_is_read_in_metric(tmp_path):
    (tmp_path / "weather_1.json").write_text(json.dumps(GARMIN_WEATHER))
    (tmp_path / "weather_2.json").write_text("{}")                          # indoor: Garmin has none
    (tmp_path / "acclimation_2026-09-28.json").write_text(json.dumps({"heatAcclimationPercentage": 8}))
    w = garmin_extras.read_weather(tmp_path, "1")
    assert (w["temp_c"], w["dew_point_c"], w["humidity"], w["station"], w["wind_dir"]) == (23.9, 15.0, 57, "Town", "ENE")
    assert w["wind_kmh"] == pytest.approx(4.8)
    assert garmin_extras.read_weather(tmp_path, "2") is None
    assert garmin_extras.read_weather(tmp_path, "3") is None                # not downloaded yet
    assert garmin_extras.read_acclimation(tmp_path, "2026-09-28") == 8.0


def test_fetch_extras_downloads_once_and_remembers_no_weather(tmp_path):
    calls = []

    def connectapi(path):
        calls.append(path)
        if path.endswith("/weather"):
            raise RuntimeError("404 Client Error: Not Found")               # indoor activity
        return {"heatAcclimationPercentage": 5}

    assert garmin_extras.fetch_extras(connectapi, tmp_path, "42", "2026-09-28") == 2
    assert json.loads((tmp_path / "weather_42.json").read_text()) == {}
    assert garmin_extras.fetch_extras(connectapi, tmp_path, "42", "2026-09-28") == 0  # never asked again
    assert len(calls) == 2
    assert garmin_extras.fetch_extras(connectapi, tmp_path, "../x", "2026-09-28") == 0  # ids: digits only


def test_network_errors_are_not_stored_as_no_weather(tmp_path):
    def connectapi(path):
        raise RuntimeError("429 Too Many Requests")
    with pytest.raises(RuntimeError):
        garmin_extras.fetch_extras(connectapi, tmp_path, "42", "2026-09-28")
    assert not (tmp_path / "weather_42.json").exists()                      # retried next time


def test_digits_of_the_activity_id_in_an_error_are_not_a_404(tmp_path):
    def connectapi(path):  # Garmin's errors quote the URL, and ids like 12404567890 contain "404"
        raise RuntimeError(f"500 Server Error: Internal Server Error for url: https://connectapi.garmin.com{path}")
    with pytest.raises(RuntimeError):
        garmin_extras.fetch_extras(connectapi, tmp_path, "12404567890", "2026-09-28")
    assert not (tmp_path / "weather_12404567890.json").exists()             # retried next time


def test_backfill_skips_what_exists_and_backs_off(tmp_path):
    (tmp_path / "weather_1.json").write_text("{}")
    (tmp_path / "acclimation_2026-01-01.json").write_text("{}")
    fails = {"n": 0}

    def connectapi(path):
        if "/2/" in path and fails["n"] == 0:
            fails["n"] += 1
            raise RuntimeError("429")
        return {}

    pauses = []
    r = garmin_extras.backfill(connectapi, tmp_path, [("1", "2026-01-01"), ("2", "2026-01-02"), ("3", "2026-01-03")],
                               sleep=pauses.append)
    assert (r["missing"], r["fetched"], r["failed"]) == (2, 1, 1)
    assert max(pauses) >= 2.0                                               # backed off after the error


def run(weather=None, acclimation=None, indoor=False):
    act = ParsedActivity(activity_id="1", start_time=datetime(2026, 9, 28, 17, 15), sport="running",
                         name="Run", duration_s=2700, distance_m=8000, indoor=indoor,
                         records=steady_records(minutes=45, hr=137), weather=weather, heat_acclimation=acclimation)
    return compute_features(act, USER)["features"]


def test_efficiency_is_adjusted_by_weather_not_wrist_sensor():
    w = {"temp_c": 23.9, "dew_point_c": 15.0, "station": "Town"}
    cool, warm = run(), run(w, 8)
    assert cool["heat_adj_pct"] == 0 and cool["ef_adj"] == cool["ef"]
    assert warm["heat_adj_pct"] == pytest.approx(2.88)
    assert warm["ef_adj"] == pytest.approx(warm["ef"] * 1.0288, rel=1e-3)
    assert warm["weather"]["station"] == "Town" and warm["heat_acclimation"] == 8
    assert run(w, 8, indoor=True)["heat_adj_pct"] == 0                      # treadmill: no outdoor heat


def test_heat_note_only_with_real_weather():
    model = RunningModel()
    base = {"sport": "running", "indoor": 0, "avg_temp_c": 127.0}          # old fake value alone: no note
    assert not [n for n in model.context_notes({**base, "features": run()}, None, None, {}) if n["kind"] == "heat"]
    notes = model.context_notes({**base, "features": run({"temp_c": 23.9, "dew_point_c": 15.0, "station": "Town"}, 8)},
                                None, None, {})
    heat = [n["text"] for n in notes if n["kind"] == "heat"]
    assert heat == ["Warm & humid: 24 °C, dew point 15 °C (Town) — efficiency adjusted +2.9 %; heat acclimation 8 %"]


def test_multisport_legs_share_the_parent_weather(tmp_path):
    assert garmin_extras.weather_id("23160165938_2") == "23160165938"
    assert garmin_extras.weather_id("24530469905") == "24530469905"
    assert garmin_extras.weather_id("../etc/passwd") is None and garmin_extras.weather_id("1_2_3") is None
    calls = []
    garmin_extras.fetch_extras(lambda p: calls.append(p) or {"temp": 68}, tmp_path, "23160165938_1", "2026-06-07")
    garmin_extras.fetch_extras(lambda p: calls.append(p) or {"temp": 68}, tmp_path, "23160165938_2", "2026-06-07")
    assert [c for c in calls if c.endswith("/weather")] == ["/activity-service/activity/23160165938/weather"]
    assert garmin_extras.read_weather(tmp_path, "23160165938_3")["temp_c"] == 20.0


def maxmet(day, run=None, cyc=None):
    return {"generic": {"calendarDate": day, "vo2MaxPreciseValue": run, "vo2MaxValue": round(run) if run else None},
            "cycling": {"calendarDate": day, "vo2MaxPreciseValue": cyc} if cyc else None}


def test_precise_vo2max_history_first_all_then_incremental(tmp_path):
    from datetime import date
    calls = []

    def first(path):
        calls.append(path)
        return [maxmet("2025-10-08", 44.9), maxmet("2026-09-27", 44.2, 41.3), maxmet("2026-09-28", 44.1)]

    assert garmin_extras.update_vo2max(first, tmp_path, today=date(2026, 9, 29)) == 3
    assert calls == ["/metrics-service/metrics/maxmet/daily/2021-09-30/2026-09-29"]     # whole history, 1 request
    v = garmin_extras.read_vo2max(tmp_path)
    assert v["2026-09-28"] == {"running": 44.1} and v["2026-09-27"] == {"running": 44.2, "cycling": 41.3}

    calls.clear()
    garmin_extras.update_vo2max(lambda p: calls.append(p) or [maxmet("2026-09-30", 44.3)], tmp_path, today=date(2026, 9, 30))
    assert calls == ["/metrics-service/metrics/maxmet/daily/2026-09-14/2026-09-30"]     # only recent days
    assert garmin_extras.read_vo2max(tmp_path)["2026-10-08" if False else "2026-09-30"] == {"running": 44.3}
    assert len(garmin_extras.read_vo2max(tmp_path)) == 4                                  # history kept


def test_health_days_use_precise_vo2max(tmp_path):
    import sqlite3
    from healthdash.ingest.garmindb_reader import GarminDbReader
    (tmp_path / "DBs").mkdir()
    for name in ("garmin.db", "garmin_activities.db"):
        sqlite3.connect(tmp_path / "DBs" / name).close()
    (tmp_path / "Extras").mkdir()
    (tmp_path / "Extras" / "vo2max.json").write_text(json.dumps({"2026-09-28": {"running": 44.1, "cycling": 41.3}}))
    days = GarminDbReader(tmp_path).health_days(datetime(2026, 9, 1))
    assert days == [{"day": "2026-09-28", "vo2max": 44.1, "vo2max_cycling": 41.3}]
