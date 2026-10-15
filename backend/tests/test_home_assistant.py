"""Home Assistant: discovery and state payloads, the opt-in, the MQTT bridge and the embed headers."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fitvio import db, mqtt_bridge, wall
from fitvio import home_assistant as ha
from fitvio.api import main
from fitvio.config import MqttConfig, load_config
from fitvio.demo import generate
from fitvio.sync import activity_watch

M = MqttConfig(host="broker")


class FakeClient:
    def __init__(self):
        self.sent: list[tuple[str, str, bool]] = []

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload, retain))

    def take(self):
        sent, self.sent = self.sent, []
        return sent


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": [{"id": "a", "name": "Alex"}, {"id": "b", "name": "Bo"}],
                                "mqtt": {"host": "broker", "username": "fitvio"}}))
    monkeypatch.setenv("FITVIO_CONFIG", str(path))
    cfg = load_config(path)
    cfg.db_path = tmp_path / "app.db"
    conn = db.connect(cfg.db_path)
    generate(conn, cfg, days=30)
    return cfg, conn


def add_workout(conn, uid, start: datetime, verdict="better"):
    sid = f"{uid}:{start:%Y%m%d%H%M}"
    db.upsert(conn, "sessions", {"id": sid, "user_id": uid, "activity_id": sid, "name": "Morning Run",
                                 "sport": "running", "start_time": start.isoformat(timespec="seconds")})
    db.upsert(conn, "verdicts", {"session_id": sid, "user_id": uid, "created_at": datetime.now().isoformat(),
                                 "verdict": verdict, "confidence": "high", "headline": "Faster at the same heart rate",
                                 "trend": "{}"})
    conn.commit()
    return sid


def after_demo(conn, uid):
    """A "now" just after the newest generated workout, so new ones are newer than everything."""
    newest = conn.execute("SELECT max(start_time) FROM sessions WHERE user_id = ?", (uid,)).fetchone()[0]
    return datetime.fromisoformat(newest) + timedelta(hours=2)


def topics(sent):
    return [t for t, _, _ in sent]


def test_mqtt_config_is_optional_and_the_password_comes_from_the_environment(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": []}))
    assert load_config(path).mqtt is None
    path.write_text(json.dumps({"users": [], "mqtt": {"host": "10.0.0.2", "port": 1884, "username": "u"}}))
    monkeypatch.setenv("FITVIO_MQTT_PASSWORD", "s3cret")
    m = load_config(path).mqtt
    assert (m.host, m.port, m.username, m.password, m.topic_prefix, m.discovery_prefix) == \
        ("10.0.0.2", 1884, "u", "s3cret", "fitvio", "homeassistant")


def test_nobody_is_shared_by_default(setup):
    _, conn = setup
    assert not ha.is_shared(conn, "a")
    ha.set_shared(conn, "a", True)
    assert ha.is_shared(conn, "a") and not ha.is_shared(conn, "b")


def test_discovery_is_one_device_per_person_with_every_entity(setup):
    cfg, _ = setup
    d = ha.discovery(M, cfg.user("a"))
    assert ha.discovery_topic(M, "a") == "homeassistant/device/fitvio_a/config"
    assert d["dev"] == {"ids": ["fitvio_a"], "name": "Fitvio Alex", "mf": "Fitvio"} and d["o"]["name"] == "Fitvio"
    assert d["availability_topic"] == "fitvio/status"
    sensors = {k for k, c in d["cmps"].items() if c["p"] == "sensor"}
    assert sensors == set(ha.SENSORS)
    for key, c in d["cmps"].items():
        assert c["unique_id"] == f"fitvio_a_{key}" and c["default_entity_id"] == f"{c['p']}.fitvio_a_{key}"
    readiness = d["cmps"]["training_readiness"]
    assert readiness["state_topic"] == "fitvio/a/state" and readiness["value_template"] == "{{ value_json.training_readiness }}"
    assert readiness["json_attributes_template"] == "{{ value_json.attrs.training_readiness | tojson }}"
    assert d["cmps"]["last_sync"]["device_class"] == "timestamp" and "state_class" not in d["cmps"]["last_sync"]
    assert d["cmps"]["sync_now"] == {**d["cmps"]["sync_now"], "p": "button", "command_topic": "fitvio/a/sync",
                                     "payload_press": "PRESS"}
    assert d["cmps"]["new_workout"]["event_types"] == ["better", "in_line", "worse", "not_comparable", "load_only"]
    assert d["cmps"]["login_expired"]["state_topic"] == "fitvio/a/event/login_expired"


def test_ids_become_valid_entity_ids_and_topics():
    assert ha.slug("Anna-Lena.K") == "anna_lena_k"
    assert ha.state_topic(M, "Anna-Lena.K") == "fitvio/anna_lena_k/state"


def test_state_takes_the_wall_numbers(setup):
    cfg, conn = setup
    amb = wall.ambient(conn, cfg, "a")
    s = ha.state(amb)
    assert set(ha.SENSORS) <= set(s) and set(s["attrs"]) == ha.ATTRIBUTES
    h = amb["health_latest"]
    assert (s["hrv"], s["resting_hr"], s["body_battery"], s["sleep_score"]) == \
        (h["hrv_last_night"], h["rhr"], h["bb_max"], h["sleep_score"])
    assert s["sleep_duration"] == round(h["sleep_total_min"])
    assert (s["fitness"], s["fatigue"], s["form"]) == (amb["form"]["fitness"], amb["form"]["fatigue"], amb["form"]["form"])
    assert s["week_streak"] == amb["streak"]["weeks"] and s["week_load"] == amb["sweet_spot"]["load"]
    assert s["attrs"]["hrv"]["normal_low"] == h["hrv_baseline_low"]
    assert datetime.fromisoformat(s["last_sync"]).tzinfo is not None  # Home Assistant needs a zone
    json.dumps(db.finite(s))  # sendable


def test_state_of_someone_without_data():
    s = ha.state({"user_id": "x"})
    assert s["training_readiness"] is None and s["todays_workout"] == "Rest" and s["last_workout"] is None
    assert s["sync_status"] == "ok" and s["attrs"]["week_load"]["status"] is None


def test_state_says_why_a_sync_needs_attention():
    assert ha.state({"sync": {"login_expired": True, "last_error": "x"}})["sync_status"] == "login_expired"
    assert ha.state({"sync": {"last_error": "timeout"}})["sync_status"] == "failed"
    assert ha.state({"sync": {"stale": True}})["sync_status"] == "stale"
    s = ha.state({"sweet_spot": {"low": 300, "high": 500, "load": 520}})
    assert s["attrs"]["week_load"]["status"] == "above"


def test_bridge_publishes_only_people_who_opted_in(setup):
    cfg, conn = setup
    client = FakeClient()
    bridge = mqtt_bridge.Bridge(client, lambda uid: None)
    bridge.tick(conn, cfg)
    assert client.take() == []  # nobody shared: nothing leaves the house
    ha.set_shared(conn, "a", True)
    bridge.tick(conn, cfg)
    sent = client.take()
    assert topics(sent) == ["homeassistant/device/fitvio_a/config", "fitvio/a/state"]
    assert all(retain for _, _, retain in sent)
    assert json.loads(sent[1][1])["hrv"] == wall.ambient(conn, cfg, "a")["health_latest"]["hrv_last_night"]
    bridge.tick(conn, cfg)
    assert client.take() == []  # nothing changed: nothing sent again


def test_bridge_republishes_the_state_after_a_sync(setup):
    cfg, conn = setup
    client = FakeClient()
    bridge = mqtt_bridge.Bridge(client, lambda uid: None)
    ha.set_shared(conn, "a", True)
    bridge.tick(conn, cfg)
    client.take()
    db.upsert(conn, "sync_status", {"user_id": "a", "last_attempt": datetime.now().isoformat(),
                                    "last_success": datetime.now().isoformat(), "last_error": None})
    conn.commit()
    bridge.tick(conn, cfg)
    assert topics(client.take()) == ["fitvio/a/state"]


def test_opting_out_removes_the_device_and_its_retained_state(setup):
    cfg, conn = setup
    client = FakeClient()
    bridge = mqtt_bridge.Bridge(client, lambda uid: None)
    ha.set_shared(conn, "a", True)
    bridge.tick(conn, cfg)
    client.take()
    ha.set_shared(conn, "a", False)
    bridge.tick(conn, cfg)
    assert client.take() == [("homeassistant/device/fitvio_a/config", "", True), ("fitvio/a/state", "", True)]
    bridge.tick(conn, cfg)
    assert client.take() == []
    ha.set_shared(conn, "a", True)  # and back: announced again
    bridge.tick(conn, cfg)
    assert topics(client.take()) == ["homeassistant/device/fitvio_a/config", "fitvio/a/state"]


def test_a_device_left_on_the_broker_from_before_a_restart_is_removed(setup):
    cfg, conn = setup
    client = FakeClient()
    bridge = mqtt_bridge.Bridge(client, lambda uid: None)
    bridge.on_message(M, "homeassistant/device/fitvio_b/config", b'{"dev": {}}')  # retained, b opted out meanwhile
    bridge.on_message(M, "homeassistant/device/other_thing/config", b'{"dev": {}}')  # not ours
    bridge.tick(conn, cfg)
    assert client.take() == [("homeassistant/device/fitvio_b/config", "", True), ("fitvio/b/state", "", True)]


def test_a_new_workout_is_announced_once_with_its_verdict(setup):
    cfg, conn = setup
    client = FakeClient()
    bridge = mqtt_bridge.Bridge(client, lambda uid: None)
    ha.set_shared(conn, "a", True)
    now = after_demo(conn, "a")
    bridge.tick(conn, cfg, now)  # the first round only remembers the latest workout
    assert not [t for t in topics(client.take()) if "/event/" in t]
    add_workout(conn, "a", now - timedelta(hours=1), "worse")
    sid = add_workout(conn, "a", now - timedelta(minutes=20), "better")
    bridge.tick(conn, cfg, now)
    events = [(t, json.loads(p), r) for t, p, r in client.take() if "/event/" in t]
    assert [(t, e["event_type"], r) for t, e, r in events] == [
        ("fitvio/a/event/new_workout", "worse", False), ("fitvio/a/event/new_workout", "better", False)]
    assert events[1][1] == {**events[1][1], "verdict": "Better", "sport": "running", "name": "Morning Run",
                            "headline": "Faster at the same heart rate", "session_id": sid}
    bridge.tick(conn, cfg, now)
    assert not [t for t in topics(client.take()) if "/event/" in t]  # once


def test_old_workouts_from_a_backfill_are_not_announced(setup):
    cfg, conn = setup
    client = FakeClient()
    bridge = mqtt_bridge.Bridge(client, lambda uid: None)
    ha.set_shared(conn, "a", True)
    now = after_demo(conn, "a") + timedelta(hours=cfg.wall.fresh_activity_hours)
    bridge.tick(conn, cfg, now)
    add_workout(conn, "a", now - timedelta(hours=cfg.wall.fresh_activity_hours, minutes=30))
    bridge.tick(conn, cfg, now)
    assert not [t for t in topics(client.take()) if "/event/" in t]


def test_a_failed_sync_and_an_expired_login_are_announced_once(setup):
    cfg, conn = setup
    client = FakeClient()
    bridge = mqtt_bridge.Bridge(client, lambda uid: None)
    ha.set_shared(conn, "a", True)
    bridge.tick(conn, cfg)
    client.take()
    db.upsert(conn, "sync_status", {"user_id": "a", "last_attempt": datetime.now().isoformat(), "last_error": "timeout"})
    db.set_state(conn, activity_watch._k("a", "paused_at"), datetime.now().isoformat())
    conn.commit()
    bridge.tick(conn, cfg)
    events = {t: json.loads(p) for t, p, _ in client.take() if "/event/" in t}
    assert events == {"fitvio/a/event/sync_failed": {"event_type": "sync_failed", "error": "timeout"},
                      "fitvio/a/event/login_expired": {"event_type": "login_expired"}}
    bridge.tick(conn, cfg)
    assert not [t for t in topics(client.take()) if "/event/" in t]


def test_sync_now_from_home_assistant_only_for_shared_people(setup):
    cfg, conn = setup
    started = []
    bridge = mqtt_bridge.Bridge(FakeClient(), started.append)
    ha.set_shared(conn, "a", True)
    bridge.on_message(M, "fitvio/a/sync", b"PRESS")
    bridge.on_message(M, "fitvio/b/sync", b"PRESS")  # b doesn't share: has no button
    bridge.on_message(M, "fitvio/a/sync", b"nonsense")
    bridge.tick(conn, cfg)
    assert started == ["a"]


def test_while_the_broker_is_down_nothing_is_published_and_it_catches_up_after(setup, monkeypatch):
    _, conn = setup
    client = FakeClient()
    bridge = mqtt_bridge.Bridge(client, lambda uid: None)
    ha.set_shared(conn, "a", True)
    connected = {"now": True, "new": True}
    assert mqtt_bridge.step(bridge, conn, connected, settle_s=0)
    client.take()
    connected["now"] = False  # broker gone
    start = max(datetime.now() - timedelta(minutes=5), after_demo(conn, "a") - timedelta(hours=1))
    sid = add_workout(conn, "a", start)
    assert not mqtt_bridge.step(bridge, conn, connected, settle_s=0)
    assert client.take() == []
    connected.update(now=True, new=True)  # back: everything again, and the workout from meanwhile
    assert mqtt_bridge.step(bridge, conn, connected, settle_s=0)
    sent = client.take()
    assert topics(sent)[:2] == ["homeassistant/device/fitvio_a/config", "fitvio/a/state"]
    assert [json.loads(p)["session_id"] for t, p, _ in sent if t == "fitvio/a/event/new_workout"] == [sid]


def test_a_failing_round_is_retried_and_does_not_end_the_bridge(setup, monkeypatch):
    _, conn = setup
    bridge = mqtt_bridge.Bridge(FakeClient(), lambda uid: None)
    calls = []

    def boom(*a, **kw):
        calls.append(1)
        raise RuntimeError("database is locked")
    monkeypatch.setattr(bridge, "tick", boom)
    connected = {"now": True, "new": False}
    assert not mqtt_bridge.step(bridge, conn, connected)
    assert not mqtt_bridge.step(bridge, conn, connected)
    assert len(calls) == 2


@pytest.fixture()
def client(setup):
    cfg, _ = setup
    main._cfg = cfg
    yield TestClient(main.app)
    main._cfg = None
    main.app.dependency_overrides.clear()


def test_home_assistant_settings_api(client):
    assert client.get("/api/settings/home-assistant").json() == {"configured": True, "users": {"a": False, "b": False}}
    assert client.post("/api/settings/home-assistant", json={"user_id": "a", "shared": True}).status_code == 403
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    r = client.post("/api/settings/home-assistant", json={"user_id": "a", "shared": True}).json()
    assert r["users"] == {"a": True, "b": False}
    assert client.post("/api/settings/home-assistant", json={"user_id": "zz", "shared": True}).status_code == 400
    assert client.post("/api/settings/home-assistant", json={"user_id": "a", "shared": "yes"}).status_code == 422


def test_the_wall_cannot_be_framed_unless_an_origin_is_allowed(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    main._cfg.wall.embed_origins = ["http://192.168.178.136:8123/", "http://x; script-src *"]
    r = client.get("/api/health")
    assert "x-frame-options" not in r.headers
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors http://192.168.178.136:8123;" in csp and "script-src" not in csp
