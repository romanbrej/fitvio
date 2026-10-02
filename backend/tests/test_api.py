import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from healthdash import db
from healthdash.api import main
from healthdash.config import load_config
from healthdash.demo import generate


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    cfg_path = tmp / "users.json"
    cfg_path.write_text(json.dumps({"users": [
        {"id": "a", "name": "Alex Runner", "max_hr": 190, "rest_hr": 48},
        {"id": "b", "name": "Bo", "max_hr": 185, "rest_hr": 55},
    ]}))
    cfg = load_config(cfg_path)
    cfg.db_path = tmp / "app.db"
    generate(db.connect(cfg.db_path), cfg, days=60)
    main._cfg = cfg
    yield TestClient(main.app)
    main._cfg = None


def test_config(client):
    r = client.get("/api/config").json()
    assert [u["initials"] for u in r["users"]] == ["AR", "B"]


def test_wall_shows_fresh_verdict_then_select_goes_ambient(client):
    w = client.get("/api/wall").json()
    assert w["mode"] == "verdict"
    assert w["user_id"] == "a"  # demo: user a's run finished most recently
    assert w["session"]["verdict"]["headline"]
    client.post("/api/wall/select", json={"user_id": "b"})
    w = client.get("/api/wall").json()
    assert w["mode"] in ("ambient", "verdict")
    if w["mode"] == "verdict":  # b's own fresh run may still be up
        assert w["user_id"] == "b"


def test_verdict_shows_what_improved_and_wall_shows_fitness_curve(client):
    sessions = client.get("/api/users/a/sessions?limit=1").json()
    d = client.get(f"/api/sessions/{sessions[0]['id']}").json()
    assert "fitness" in [i["kind"] for i in d["improvements"]]
    a = client.get("/api/users/a/ambient").json()
    assert len(a["pmc"]) > 42 and "fitness_change_6w" in a
    # today's change = all of today's training: last pmc row minus the one before
    today, prev = a["pmc"][-1], a["pmc"][-2]
    for k in ("fitness", "fatigue", "form"):
        assert a["today_change"][k] == pytest.approx(today[k] - prev[k], abs=0.11)
    assert a["form"]["form"] == pytest.approx(a["form"]["fitness"] - a["form"]["fatigue"], abs=0.11)
    lw = a["last_workout"]  # the wall's first card on the day of a workout: what it improved
    if sessions[0]["start_time"][:10] == datetime.now().date().isoformat():
        assert lw["id"] == sessions[0]["id"] and lw["improvements"] and lw["verdict"]
    else:
        assert lw is None


def test_last_workout_card_resets_at_midnight():
    from healthdash.wall import _is_today
    assert _is_today("2026-09-29T19:30:00", datetime(2026, 9, 29, 23, 59))
    assert not _is_today("2026-09-29T19:30:00", datetime(2026, 9, 30, 0, 0))


def test_session_detail_and_lists(client):
    sessions = client.get("/api/users/a/sessions?limit=5").json()
    assert len(sessions) == 5
    d = client.get(f"/api/sessions/{sessions[0]['id']}").json()
    assert d["streams"]["t"]
    assert "baseline_sessions" in d
    assert client.get("/api/users/a/pmc?days=30").json()[-1]["fitness"] > 0
    assert client.get("/api/users/a/health?days=14").json()
    assert "agreement_pct" in client.get("/api/users/a/validation").json()


def test_unknown_user_404(client):
    assert client.get("/api/users/nope/ambient").status_code == 404


def test_sport_status_running_pace_and_cycling_wkg():
    from datetime import date as d
    from healthdash import improvements, wall
    today = d(2026, 10, 2)

    def run(day, speed, typ="easy"):
        return {"sport": "running", "session_type": typ, "indoor": 0, "start_time": f"2026-09-{day:02d}T07:00:00",
                "features": {"speed_at_ref_hr_adj": speed, "ref_hr": 151}}

    # 5 steady runs getting faster at 151 bpm (6:40 → 6:20 /km); the fast intervals must not count
    runs = [run(1 + 7 * i, 1000 / (400 - 5 * i)) for i in range(5)] + [run(30, 1000 / 240, "intervals")]
    st = wall.sport_status(runs, "running", None, improvements.Weights([], 85), today)
    assert st["pace_s_per_km"] == pytest.approx(385, abs=1)   # median of the last 3 steady runs
    assert st["change_s_per_km"] > 15 and st["ref_hr"] == 151

    ride = {"sport": "cycling", "session_type": "easy", "has_power": 1, "start_time": "2026-09-20T07:00:00",
            "features": {"ef": 1.14, "power_at_ref_hr": 170.0, "ref_hr": 151}}
    st = wall.sport_status([ride], "cycling", 230, improvements.Weights([], 85), today)
    assert (st["w_per_beat"], st["ftp_wkg"], st["hr_wkg"]) == (1.14, 2.71, 2.0)
    # no rides with power: FTP W/kg still shows
    st = wall.sport_status([], "cycling", 230, improvements.Weights([], 85), today)
    assert st["w_per_beat"] is None and st["ftp_wkg"] == 2.71
