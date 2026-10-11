"""Metric or imperial (#27): stored in SI, written in the person's units only when it's read."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from fitvio import db, units
from fitvio.api import main
from fitvio.config import load_config
from fitvio.demo import generate
from fitvio.models.sports import RunningModel, StrengthModel

METRIC_TEXT = re.compile(r"/km|km/h|°C|\bkg\b|/100m|\d km\b|\d m\b|m/beat")
IMPERIAL_TEXT = re.compile(r"/mi\b|mph|°F|\blb\b|/100yd|\d mi\b|\d ft\b|ft/beat")


def test_conversions():
    assert units.pace_s(312, units.METRIC) == "5:12 /km"
    assert units.pace_s(312, units.IMPERIAL) == "8:22 /mi"           # 312 × 1.609344 = 502.1 s
    assert units.pace(1000 / 312, units.IMPERIAL) == "8:22 /mi"
    assert units.pace_s(299.6, units.METRIC) == "5:00 /km"            # never "4:60"
    assert units.pace(0, units.IMPERIAL) == "—"
    assert units.swim_pace(105, units.IMPERIAL) == "1:36 /100yd"      # 100 yd = 91.44 m
    assert units.swim_pace(105, units.METRIC) == "1:45 /100m"
    assert units.pace_seconds(8, units.IMPERIAL) == (13, "s/mi")
    assert units.pace_seconds(-8, units.IMPERIAL) == (-13, "s/mi")
    assert units.swim_seconds(3, units.IMPERIAL) == (3, "s/100yd")
    assert units.distance(10_000, units.IMPERIAL) == "6.2 mi"
    assert units.swim_distance(1500, units.IMPERIAL) == "1640 yd"
    assert units.temp(28, units.IMPERIAL) == "82 °F" and units.temp(-5, units.IMPERIAL) == "23 °F"
    assert units.wind(20, units.IMPERIAL) == "12 mph"
    assert units.weight(80, units.IMPERIAL) == "176.4 lb" and units.weight(80, units.METRIC) == "80.0 kg"
    assert units.weight_diff(-2.5, units.IMPERIAL) == "-5.5 lb"
    assert units.elevation(250, units.IMPERIAL) == "820 ft"
    assert units.per_beat(1.65, units.IMPERIAL) == "5.41 ft/beat"


def test_default_from_env_and_per_person_override(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    monkeypatch.delenv("FITVIO_UNITS", raising=False)
    assert units.for_user(conn, "a") == units.METRIC
    monkeypatch.setenv("FITVIO_UNITS", " Imperial ")
    assert units.for_user(conn, "a") == units.IMPERIAL
    units.set_for_user(conn, "a", units.METRIC)  # a person's own choice beats the install's default
    assert (units.for_user(conn, "a"), units.for_user(conn, "b")) == (units.METRIC, units.IMPERIAL)
    monkeypatch.setenv("FITVIO_UNITS", "furlongs")
    assert units.for_user(conn, "b") == units.METRIC
    with pytest.raises(ValueError):
        units.set_for_user(conn, "a", "furlongs")


def _run(**features):
    return {"id": "r1", "user_id": "a", "sport": "running", "session_type": "easy", "start_time": "2026-10-01T07:00:00",
            "distance_m": 10_000, "ascent_m": 250, "features": {
                "heat_adj_pct": 2.0, "weather": {"temp_c": 28.0, "dew_point_c": 18.0, "wind_kmh": 20.0},
                "wind_adj_pct": 1.0, **features}}


def test_running_verdict_is_written_again_in_imperial():
    model, run = RunningModel(), _run()
    deltas = [{"key": "speed_at_ref_hr", "label": "Pace at fixed HR (weather-adj.)", "value": 1000 / 300,
               "baseline": 1000 / 310, "delta": 0.1, "delta_pct": 3.3, "z": 1.5, "weight": 0.35, "better": 1, "n": 6,
               "value_fmt": "5:00 /km", "baseline_fmt": "5:10 /km"}]
    context = model.context_notes(run, {"sleep_total_min": 300}, None, {})
    stored = {"verdict": "better", "deltas": deltas, "baseline_ids": ["x"] * 6, "context": context,
              "reasons": model.reasons(run, deltas, 6, "easy runs") + ["New all-time 5-min power best: 300 W"]}
    assert model.render(stored, run, units.METRIC) == {**stored, "deltas": deltas}  # metric: as stored

    v = model.render(stored, run, units.IMPERIAL)
    assert v["deltas"][0]["value_fmt"] == "8:03 /mi" and v["deltas"][0]["baseline_fmt"] == "8:19 /mi"
    assert v["reasons"][0] == "Pace at fixed HR (weather-adj.) 3.3% better than your 6 similar easy runs (8:03 /mi vs 8:19 /mi)"
    assert v["reasons"][1] == stored["reasons"][1]  # unit-free extras stay
    assert [c["kind"] for c in v["context"]] == [c["kind"] for c in context] == ["heat", "wind", "hills", "sleep"]
    text = json.dumps(v, ensure_ascii=False)
    assert not METRIC_TEXT.search(text.replace("Short sleep", "")), text
    assert "82 °F" in text and "12 mph" in text and "820 ft" in text
    assert "°C" not in json.dumps(stored, ensure_ascii=False).replace("°C", "") and stored["deltas"] is deltas  # not changed


def test_render_keeps_what_it_cannot_write_again():
    run = _run()
    old = {"verdict": "better", "baseline_ids": ["x"] * 3, "context": [{"kind": "heat", "text": "Warm: 30 °C"}],
           "deltas": [{"key": "retired_metric", "value": 1.0, "z": 1.0, "value_fmt": "1.0 km"}],
           "reasons": ["Retired metric 1.0 km"]}
    v = RunningModel().render(old, {**run, "features": {}}, units.IMPERIAL)
    assert v["deltas"] == old["deltas"] and v["reasons"] == old["reasons"]  # unknown metric: stored text
    assert v["context"] == old["context"]                                   # no weather in the session any more
    excluded = {"verdict": "excluded", "deltas": [], "reasons": ["You left this session out"], "context": []}
    assert RunningModel().render(excluded, run, units.IMPERIAL)["context"] == []  # no notes appear


def test_strength_in_pounds():
    deltas = [{"key": "squat", "label": "Squat", "value": 100.0, "baseline": 95.0, "delta": 5.0, "delta_pct": 5.3,
               "z": 1.0, "n": 3, "all_time_best": 98.0, "value_fmt": "100.0 kg e1RM", "baseline_fmt": "95.0 kg"}]
    stored = {"verdict": "better", "deltas": deltas, "context": [],
              "reasons": StrengthModel.lift_reasons(deltas)}
    assert stored["reasons"] == ["Squat: 100.0 kg e1RM, up 5.3% vs best of last 3",
                                 "New personal record: Squat 100.0 kg e1RM"]
    v = StrengthModel().render(stored, {"features": {}}, units.IMPERIAL)
    assert v["reasons"] == ["Squat: 220.5 lb e1RM, up 5.3% vs best of last 3",
                            "New personal record: Squat 220.5 lb e1RM"]
    assert v["deltas"][0]["baseline_fmt"] == "209.4 lb"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("units")
    (tmp / "users.json").write_text(json.dumps({"users": [{"id": "a", "name": "Alex", "max_hr": 190, "rest_hr": 48}]}))
    cfg = load_config(tmp / "users.json")
    cfg.db_path = tmp / "app.db"
    generate(db.connect(cfg.db_path), cfg, days=60)
    main._cfg = cfg
    main.app.dependency_overrides[main.local_network_only] = lambda: None  # the test client isn't on a LAN
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    main._cfg = None


def _texts(client) -> str:
    """Everything the server writes as text for person a: the wall, and every session's verdict and gains."""
    parts = [client.get("/api/users/a/ambient").json()["last_workout"]]
    for s in client.get("/api/users/a/sessions?limit=500").json():
        d = client.get(f"/api/sessions/{s['id']}").json()
        parts.append({k: d[k] for k in ("verdict", "improvements") if k in d})
    return json.dumps(parts, ensure_ascii=False)


def test_switching_units_rewrites_every_text_and_back(client):
    assert client.get("/api/users/a/units").json() == {"units": "metric", "default": "metric"}
    metric = _texts(client)
    assert METRIC_TEXT.search(metric) and not IMPERIAL_TEXT.search(metric)

    r = client.put("/api/users/a/units", json={"units": "imperial"})
    assert r.status_code == 200 and r.json()["units"] == "imperial"
    assert [u["units"] for u in client.get("/api/config").json()["users"]] == ["imperial"]
    assert client.get("/api/users/a/ambient").json()["units"] == "imperial"
    imperial = _texts(client)
    hits = sorted({m.group(0) for m in METRIC_TEXT.finditer(imperial)})
    assert not hits, f"metric text left in imperial: {hits}"
    for unit in ("/mi", "°F", "lb", "ft", "/100yd"):
        assert unit in imperial, unit

    client.put("/api/users/a/units", json={"units": "metric"})
    assert _texts(client) == metric  # nothing stored changed


def test_units_endpoint_refuses_anything_else(client):
    assert client.put("/api/users/a/units", json={"units": "imperial"}).status_code == 200
    assert client.put("/api/users/a/units", json={"units": "furlongs"}).status_code == 422
    assert client.put("/api/users/a/units", json={"units": "metric", "x": 1}).status_code == 422
    assert client.put("/api/users/nobody/units", json={"units": "metric"}).status_code == 404
