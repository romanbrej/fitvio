import json

import pytest
from fastapi.testclient import TestClient

from healthdash import config
from healthdash.api import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HEALTHDASH_CONFIG", str(tmp_path / "users.json"))
    monkeypatch.setenv("HEALTHDASH_DB", str(tmp_path / "app.db"))
    main.reset_config()
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    main.reset_config()


def test_dns_rebinding_foreign_host_is_refused(client):
    assert client.get("/api/config", headers={"Host": "evil.example"}).status_code == 421
    assert client.get("/api/config", headers={"Host": "192.168.1.20:8765"}).status_code == 200
    assert client.get("/api/config", headers={"Host": "raspberrypi.local:8765"}).status_code == 200


def test_cross_origin_post_is_refused(client):
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    r = client.post("/api/accounts", json={"email": "a@example.com", "password": "x"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_security_headers_present(client):
    r = client.get("/api/config")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


def test_no_api_docs_exposed(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).headers.get("content-type", "").startswith("application/json") is False \
            or client.get(path).status_code == 404


def test_input_limits(client):
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    assert client.post("/api/accounts", json={"email": "not-an-email", "password": "x"}).status_code == 422
    assert client.post("/api/accounts", json={"email": "a@example.com", "password": "x" * 1000}).status_code == 422
    assert client.post("/api/jobs/abc/mfa", json={"code": "12ab"}).status_code == 422
    assert client.get("/api/users/x/sessions?limit=-1").status_code == 422


def test_real_account_never_written_to_example_config(tmp_path, monkeypatch):
    example = tmp_path / "users.example.json"
    example.write_text(json.dumps({"users": []}))
    monkeypatch.setenv("HEALTHDASH_CONFIG", str(example))
    with pytest.raises(ValueError, match="example"):
        config.add_user("someone", "data/garmindb/someone/config")
    assert json.loads(example.read_text()) == {"users": []}


def test_users_config_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("HEALTHDASH_CONFIG", str(tmp_path / "users.json"))
    config.add_user("someone", "data/garmindb/someone/config")
    assert (tmp_path / "users.json").stat().st_mode & 0o077 == 0


def test_manual_sync_has_a_cooldown(client, tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from healthdash import accounts, db
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    (tmp_path / "users.json").write_text(json.dumps({"users": [{"id": "alex", "garmindb_config_dir": "x/config"}]}))
    main.reset_config()
    monkeypatch.setattr(accounts, "start_sync", lambda user, db_path, full=False: accounts.Job(kind="sync", user_id=user.id))
    conn = db.connect(tmp_path / "app.db")
    conn.execute("INSERT INTO sync_status (user_id, last_attempt) VALUES ('alex', ?)",
                 ((datetime.now() - timedelta(seconds=10)).isoformat(timespec="seconds"),))
    conn.commit()
    r = client.post("/api/users/alex/sync")
    assert r.status_code == 429 and "try again" in r.json()["detail"]
    conn.execute("UPDATE sync_status SET last_attempt = ?",
                 ((datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds"),))
    conn.commit()
    assert client.post("/api/users/alex/sync").status_code == 200


def test_person_folder_permissions_self_heal(tmp_path):
    import os

    from healthdash.sync import garmindb_runner
    person = tmp_path / "garmindb" / "alex"
    (person / "config").mkdir(parents=True)
    os.chmod(person, 0o755)  # created by an older version
    garmindb_runner.normalize_config(person / "config")
    assert person.stat().st_mode & 0o077 == 0 and (person / "config").stat().st_mode & 0o077 == 0


def test_app_data_dir_is_private(tmp_path):
    from healthdash import db
    db.connect(tmp_path / "data" / "app.db")
    assert (tmp_path / "data").stat().st_mode & 0o077 == 0


def test_auto_sync_switch(client):
    assert client.get("/api/settings/activity-check").json()["enabled"] is True
    # changing it is home-network only (TestClient's address "testclient" isn't a LAN address)
    assert client.post("/api/settings/activity-check", json={"enabled": False}).status_code == 403
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    assert client.post("/api/settings/activity-check", json={"enabled": False},
                       headers={"Origin": "https://evil.example"}).status_code == 403
    for bad in ({"enabled": "no"}, {"enabled": 0}, {"enabled": False, "x": 1}, {}):
        assert client.post("/api/settings/activity-check", json=bad).status_code == 422, bad
    r = client.post("/api/settings/activity-check", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert client.get("/api/settings/activity-check").json()["enabled"] is False
