"""Heat load over the session's hours, and the heat response learned from a person's own sessions."""
import math
import random
from datetime import datetime, timedelta

import pytest

from fitvio.analytics import heat, physio

from .test_exclusions import client  # noqa: F401  (the API on made-up data)


def _hour(t, temp, dew):
    return {"t": t, "temp_c": temp, "dew_point_c": dew}


def test_heat_load_follows_the_hours():
    start = datetime(2026, 7, 14, 9, 0)
    w = {"temp_c": 25, "dew_point_c": 15,
         "hourly": [_hour("09:00", 20, 10), _hour("10:00", 25, 15), _hour("11:00", 30, 20), _hour("12:00", 33, 22)]}
    three_h = heat.heat_load(w, start, 3 * 3600)
    # the average of the hourly %, not the % of the average weather: the hot end counts
    assert physio.heat_adjustment(20, 10) < three_h < physio.heat_adjustment(33, 22)
    assert three_h > heat.heat_load(w, start, 3600)  # the first hour alone was cooler
    assert heat.heat_load(w, start, 3600, acclimation_pct=100) == pytest.approx(heat.heat_load(w, start, 3600) / 2, abs=0.01)
    assert heat.heat_load(w, start, 3600, indoor=True) == 0


def test_heat_load_across_midnight():
    start = datetime(2026, 7, 14, 23, 40)
    w = {"hourly": [_hour("23:00", 30, 22), _hour("00:00", 30, 22), _hour("01:00", 20, 10)]}
    # 23:40–00:40: hot all the way (the 01:00 hour only starts cooling after 00:00)
    assert heat.heat_load(w, start, 3600) > physio.heat_adjustment(25, 16)


def test_heat_load_from_one_reading_and_none():
    start = datetime(2026, 7, 14, 9)
    assert heat.heat_load({"temp_c": 30, "dew_point_c": 20}, start, 3600) == physio.heat_adjustment(30, 20)
    assert heat.heat_load({"temp_c": 30}, start, 3600) == physio.heat_adjustment(30, None)  # temp − 10 guess
    assert heat.heat_load(None, start, 3600) == 0
    assert heat.heat_load({"temp_c": None}, start, 3600) == 0


def _season(sport="running", k=1.0, d=0.0, days=365, seed=1, noise=0.025, swing=0.06, every=2):
    """A year of steady sessions: fitness rises into summer just as the heat does (the trap), plus noise."""
    rng = random.Random(seed)
    out = []
    t0 = datetime(2025, 1, 1, 7)
    for i in range(0, days, every):
        t = t0 + timedelta(days=i)
        season = math.sin((i - 100) / 365 * 2 * math.pi)            # +1 mid-summer
        temp = 12 + 10 * season + rng.gauss(0, 5)
        dew = temp - 8 + rng.gauss(0, 2)
        weather = {"temp_c": temp, "dew_point_c": dew}
        load = heat.heat_load(weather, t, 3600)
        fit = 1 + swing * season                                    # fittest in summer
        ef = 1.5 * fit * (1 - k * load / 100) * math.exp(rng.gauss(0, noise))
        out.append({"id": f"s{i}", "sport": sport, "session_type": "easy", "start_time": t.isoformat(),
                    "duration_s": 3600, "indoor": 0, "has_power": 1, "excluded": False,
                    "features": {"ef": ef, "decoupling": 3 + d * load + rng.gauss(0, 1.0), "weather": weather}})
    return out


@pytest.mark.parametrize("k", [0.5, 1.5])
def test_fit_finds_a_planted_response_despite_the_summer_form(k):
    r = heat.fit_response(_season(k=k, days=730, every=1), "running")
    assert r["k_hat"] == pytest.approx(k, abs=0.35)
    assert abs(r["k"] - k) < abs(heat.PRIOR["running"]["k"] - k) or k == 1.0  # moved towards the truth


def test_fit_finds_extra_drift():
    r = heat.fit_response(_season(d=0.8, days=730, every=1), "running")
    assert r["d_hat"] == pytest.approx(0.8, abs=0.3)
    assert r["d"] > 0.4


def test_few_sessions_keep_the_prior():
    r = heat.fit_response(_season(k=2.5, days=20), "running")
    assert r["k"] == heat.PRIOR["running"]["k"] and r["d"] == 0
    rides = heat.fit_response(_season(sport="cycling", days=20), "cycling")
    assert rides["k"] == 0.5


def test_outliers_and_exclusions_are_left_out():
    sessions = _season(k=1.0, days=730, every=1)
    clean = heat.fit_response(sessions, "running")
    hot = sorted(sessions, key=lambda s: -heat.session_load(s))[:5]
    for s in hot:  # five broken hot sessions (GPS glitch: twice the efficiency)
        s["features"]["ef"] *= 2
    assert heat.fit_response(sessions, "running")["k_hat"] == pytest.approx(clean["k_hat"], abs=0.2)
    for s in sessions:
        s["excluded"] = True
    assert heat.fit_response(sessions, "running")["n"] == 0


def test_indoor_and_rides_without_power_are_not_used():
    rides = _season(sport="cycling", days=200)
    for s in rides:
        s["has_power"] = 0
    assert heat.fit_response(rides, "cycling")["sessions"] == 0
    runs = _season(days=200)
    for s in runs:
        s["indoor"] = 1
    assert heat.fit_response(runs, "running")["sessions"] == 0


def test_adjust_in_memory():
    s = {"sport": "cycling", "indoor": 0, "start_time": "2026-07-14T09:00:00", "duration_s": 3600,
         "features": {"ef": 1.8, "power_at_ref_hr": 200, "decoupling": 6.0, "weather": {"temp_c": 30, "dew_point_c": 20}}}
    indoor = {"sport": "cycling", "indoor": 1, "start_time": "2026-07-14T09:00:00", "duration_s": 3600,
              "features": {"ef": 1.8, "decoupling": 6.0}}
    heat.adjust([s, indoor], {"cycling": {"k": 0.5, "d": 0.5}})
    load = physio.heat_adjustment(30, 20)
    f = s["features"]
    assert f["heat_adj_pct"] == pytest.approx(0.5 * load, abs=0.01)
    assert f["ef_adj"] == pytest.approx(1.8 * (1 + f["heat_adj_pct"] / 100))
    assert f["power_at_ref_hr_adj"] == pytest.approx(200 * (1 + f["heat_adj_pct"] / 100))
    assert f["decoupling_adj"] == pytest.approx(6.0 - 0.5 * load)
    assert indoor["features"]["ef_adj"] == 1.8 and indoor["features"]["heat_adj_pct"] == 0


def test_binned_is_flat_after_the_right_k():
    sessions = _season(k=1.5, days=730, every=1, noise=0.01)
    rows = heat.binned(sessions, "running", 1.5)
    warm = [b for b in rows if b["bin"] != "0" and b["n"] >= 10]
    assert warm and all(abs(b["adjusted_pct"]) < 1.0 for b in warm)
    assert min(b["raw_pct"] for b in warm) < -1.0  # as measured, hot sessions looked worse


# --- in the pipeline and the API ---------------------------------------------------------------------

def _runs(conn, uid="a"):
    from fitvio import pipeline
    return [s for s in pipeline.user_sessions(conn, uid) if s["sport"] == "running" and not s["indoor"]]


def test_relearning_rewrites_and_keeps_first_shown(client):  # noqa: F811
    import json as js

    from fitvio import db, heat_response, pipeline
    from fitvio.api import main
    conn = db.connect(main._cfg.db_path)
    sid = _runs(conn)[-1]["id"]
    conn.execute("UPDATE verdicts SET first_shown_at = '2026-01-01T07:00:00' WHERE session_id = ?", (sid,))
    # pretend an older, very different response was in use
    db.set_state(conn, "heat_response:a:running", js.dumps({"k": 2.9, "d": 1.4, "n": 1, "warm": 1}))
    conn.commit()
    assert pipeline.refresh_heat(conn, "a") == ["running"]
    k = heat_response.current(conn, "a")["running"]["k"]
    for s in _runs(conn):
        f = s["features"]
        assert f["heat_adj_pct"] == round(k * heat.session_load(s), 2) and f["heat_response"]["k"] == k
    first = conn.execute("SELECT first_shown_at FROM verdicts WHERE session_id = ?", (sid,)).fetchone()[0]
    assert first == "2026-01-01T07:00:00"
    assert pipeline.refresh_heat(conn, "a") == []  # nothing new: nothing moves


def test_switch_off_gives_the_standard_factors(client):  # noqa: F811
    from fitvio import db, heat_response, pipeline
    from fitvio.api import main
    conn = db.connect(main._cfg.db_path)
    pipeline.set_heat_learning(conn, "a", False)
    assert heat_response.current(conn, "a") == heat.priors()
    for s in _runs(conn):
        assert s["features"]["heat_adj_pct"] == round(heat.session_load(s), 2)  # the table, as before part 2
        if s["features"].get("decoupling") is not None:
            assert s["features"]["decoupling_adj"] == s["features"]["decoupling"]


def test_heat_api(client, monkeypatch):  # noqa: F811
    from fitvio import heat_response
    from fitvio.api import main
    got = client.get("/api/users/a/heat").json()
    assert got["available"] and got["learn"] and set(got["sports"]) == {"running", "cycling"}
    assert got["sports"]["cycling"]["prior_k"] == 0.5
    assert client.put("/api/users/a/heat", json={"learn": False}).status_code == 403  # home network only
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    assert client.put("/api/users/nobody/heat", json={"learn": False}).status_code == 404
    assert client.put("/api/users/a/heat", json={"learn": "no"}).status_code == 422
    off = client.put("/api/users/a/heat", json={"learn": False}).json()
    assert off["learn"] is False and off["recomputed"] > 0 and off["sports"]["running"]["k"] == 1.0
    assert client.get("/api/users/a/heat").json()["learn"] is False
    assert client.put("/api/users/a/heat", json={"learn": True}).json()["learn"] is True
    monkeypatch.setattr(heat_response, "LEARN_HEAT_RESPONSE", False)  # held back: standard factors, no switch
    assert client.get("/api/users/a/heat").json()["available"] is False
    assert client.put("/api/users/a/heat", json={"learn": True}).status_code == 404


def test_sessions_without_weather_are_left_out_and_counted():
    sessions = _season(days=120)
    for s in sessions[::3]:
        s["features"].pop("weather")
    with_weather = [s for s in sessions if "weather" in s["features"]]
    assert heat.fit_response(sessions, "running")["sessions"] == len(with_weather)
    cov = heat.coverage(sessions, "running")
    assert sum(m["no_weather"] for m in cov) == len(sessions) - len(with_weather)
    assert sum(m["usable"] for m in cov) == len(with_weather)


def test_a_small_first_fit_keeps_the_standard_for_every_session(client):  # noqa: F811
    """A fit within 0.1 of the standard (e.g. 0.95 ± 1.3) changes nothing: old and new sessions keep the
    same factor, and nothing claims a personal response."""
    from fitvio import db, heat_response
    from fitvio.api import main
    conn = db.connect(main._cfg.db_path)
    for sport in heat.SPORTS:
        conn.execute("DELETE FROM wall_state WHERE key = ?", (f"heat_response:a:{sport}",))
    sessions = _runs(conn)
    near = heat.fit_response(sessions, "running")
    near_k = near["k"]
    import fitvio.analytics.heat as h
    real = h.fit_response
    try:
        h.fit_response = lambda ss, sport: {**real(ss, sport), "k": heat.PRIOR[sport]["k"] - 0.05, "d": 0.0}
        assert heat_response.refresh(conn, "a", sessions) == []
    finally:
        h.fit_response = real
    used = heat_response.current(conn, "a")["running"]
    assert used["k"] == 1.0 and used["n"] == near["n"] and near_k is not None


def test_rides_without_power_get_no_heat_adjustment():
    ride = {"sport": "cycling", "indoor": 0, "start_time": "2026-07-14T09:00:00", "duration_s": 3600,
            "features": {"avg_speed": 8.0, "weather": {"temp_c": 30, "dew_point_c": 20}}}
    heat.adjust([ride], heat.priors())
    assert ride["features"]["heat_adj_pct"] == 0  # judged on load only: no "Heat adjustment" row


def test_rewrite_reads_the_sessions_under_the_write_lock(tmp_path):
    """A heat rewrite holds the write lock from reading the sessions to storing them, so a sync in the
    other process can't store a session in between (it would be overwritten with an older copy)."""
    import sqlite3

    from fitvio import db, pipeline
    path = tmp_path / "app.db"
    conn = db.connect(path)
    conn.execute("INSERT INTO sessions (id, user_id, activity_id, sport, session_type, start_time, features) "
                 "VALUES ('u:1', 'u', '1', 'running', 'easy', '2026-07-14T09:00:00', '{\"ef\": 1.5}')")
    conn.commit()
    other = sqlite3.connect(path, timeout=0)
    seen = {}
    real = pipeline.user_sessions

    def reading(c, uid):
        if "blocked" in seen:  # only the read the rewrite works from (re-judging reads again later)
            return real(c, uid)
        try:  # the sync's write while the rewrite has read the sessions
            other.execute("UPDATE sessions SET name = 'x' WHERE id = 'u:1'")
            other.commit()
            seen["blocked"] = False
        except sqlite3.OperationalError:
            seen["blocked"] = True
        return real(c, uid)
    pipeline.user_sessions = reading
    try:
        pipeline._reapply_heat(conn, "u", ["running"])
    finally:
        pipeline.user_sessions = real
    conn.commit()
    assert seen["blocked"]
