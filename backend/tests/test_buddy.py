"""Training buddy: the animal setting and the mood rules."""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from healthdash import buddy, db
from healthdash.api import main
from healthdash.config import load_config
from healthdash.demo import generate

TODAY = date(2026, 10, 5)


def sess(days_ago=0, dur=1800):
    return {"start_time": f"{(TODAY - timedelta(days=days_ago)).isoformat()}T07:00:00", "duration_s": dur}


def mood(**kw):
    base = dict(readiness=None, health_latest={}, form=0.0, today_workout=None, last_workout=None,
                sessions=[sess(1)], today=TODAY)
    base.update(kw)
    return buddy.mood(**base)


def test_animal_defaults_to_mouse_and_is_validated():
    conn = db.connect(":memory:")
    assert buddy.get_animal(conn, "u") == "mouse"
    buddy.set_animal(conn, "u", "penguin")
    assert buddy.get_animal(conn, "u") == "penguin"
    with pytest.raises(ValueError):
        buddy.set_animal(conn, "u", "dragon")
    db.set_state(conn, "buddy.u.animal", "unicorn")  # a stale/invalid stored value never reaches the wall
    assert buddy.get_animal(conn, "u") == "mouse"


def test_overjoyed_after_a_better_workout_or_a_new_best_today():
    assert mood(today_workout={"done": {"verdict": "better"}}) == "overjoyed"
    lw = {"start_time": f"{TODAY}T07:00:00", "improvements": [{"tone": "best"}]}
    assert mood(last_workout=lw) == "overjoyed"
    old = {"start_time": "2026-09-01T07:00:00", "improvements": [{"tone": "best"}]}
    assert mood(last_workout=old) != "overjoyed"


def test_hungry_after_three_days_without_a_workout_even_when_fresh():
    assert mood(sessions=[sess(3)], readiness={"level": "PRIME"}) == "hungry"
    assert mood(sessions=[sess(2)]) != "hungry"
    assert mood(sessions=[sess(0, dur=300)]) == "hungry"  # a 5-minute walk isn't a meal
    # overjoyed still wins over hungry
    assert mood(sessions=[], today_workout={"done": {"verdict": "better"}}) == "overjoyed"


def test_sleepy_happy_content():
    assert mood(readiness={"level": "POOR"}) == "sleepy"
    assert mood(health_latest={"sleep_score": 52}, readiness={"level": "HIGH"}) == "sleepy"
    assert mood(readiness={"level": "HIGH"}) == "happy"
    assert mood(readiness=None, form=12.0) == "happy"
    assert mood(readiness={"level": "MODERATE"}, form=12.0) == "content"  # Garmin's readiness wins over form
    assert mood(readiness=None, form=-3.0) == "content"


def test_line_mentions_the_food_and_todays_workout():
    assert "cheese" in buddy.line("happy", "mouse", {"title": "Schwelle"}, None)
    assert "Schwelle" in buddy.line("happy", "mouse", {"title": "Schwelle"}, None)
    assert buddy.line("overjoyed", "penguin", None, None).startswith("Fish party")
    assert "streak" in buddy.line("content", "cat", None, {"needed": 1})


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("buddy")
    cfg_path = tmp / "users.json"
    cfg_path.write_text(json.dumps({"users": [{"id": "a", "name": "Alex"}, {"id": "b", "name": "Bo"}]}))
    cfg = load_config(cfg_path)
    cfg.db_path = tmp / "app.db"
    generate(db.connect(cfg.db_path), cfg, days=30)
    main._cfg = cfg
    yield TestClient(main.app)
    main._cfg = None


def test_buddy_settings_api_round_trip(client):
    assert client.post("/api/settings/buddy", json={"user_id": "b", "animal": "frog"}).status_code == 403  # not from home
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    r = client.get("/api/settings/buddy").json()
    assert r["users"] == {"a": "mouse", "b": "mouse"} and len(r["animals"]) == 8
    r = client.post("/api/settings/buddy", json={"user_id": "b", "animal": "frog"}).json()
    assert r["users"]["b"] == "frog"
    assert client.get("/api/users/b/ambient").json()["buddy"]["animal"] == "frog"
    assert client.post("/api/settings/buddy", json={"user_id": "b", "animal": "dragon"}).status_code == 400
    assert client.post("/api/settings/buddy", json={"user_id": "zz", "animal": "cat"}).status_code == 400
    main.app.dependency_overrides.clear()


def test_ambient_has_a_buddy_with_a_valid_mood(client):
    b = client.get("/api/users/a/ambient").json()["buddy"]
    assert b["animal"] in buddy.ANIMALS and b["food"] == buddy.FOOD[b["animal"]]
    assert b["mood"] in {"happy", "content", "sleepy", "overjoyed", "hungry"} and b["line"]
