import json

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
    lw = a["last_workout"]  # the wall's first card: the newest workout and what it improved
    assert lw["id"] == sessions[0]["id"] and lw["improvements"] and lw["verdict"]


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
