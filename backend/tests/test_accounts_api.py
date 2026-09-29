import json
import time

import pytest
from fastapi.testclient import TestClient

from healthdash import accounts, config
from healthdash.api import main


def wait_for(client, job_id, phases, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["phase"] in phases:
            return j
        time.sleep(0.02)
    raise AssertionError(f"job stuck in {j['phase']}")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HEALTHDASH_CONFIG", str(tmp_path / "users.json"))
    monkeypatch.setenv("HEALTHDASH_DB", str(tmp_path / "app.db"))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    main.reset_config()

    def fake_login(user, mfa_prompt=None):
        pw = (user.garmindb_dir / "password.txt").read_text()
        if pw != "right":
            raise RuntimeError("401 Unauthorized")
        if mfa_prompt() != "123456":
            raise RuntimeError("invalid MFA code")
        return "Alex Runner"

    def fake_sync(conn, user, full=False, timeout_s=0, on_line=None, on_step=None):
        on_step(2, 10, "hydration", "Hydration")
        on_line("Downloading activities: 100%")
        return True

    monkeypatch.setattr(accounts, "login_interactive", fake_login)
    monkeypatch.setattr(accounts, "run_sync", fake_sync)
    monkeypatch.setattr(accounts.pipeline, "ingest_from_garmindb", lambda conn, user, full=False, **kw: {"activities": 42})
    c = TestClient(main.app)
    yield c
    main.app.dependency_overrides.clear()
    main.reset_config()


def test_setup_is_refused_outside_the_home_network(client):
    r = client.post("/api/accounts", json={"email": "a@example.com", "password": "right"})
    assert r.status_code == 403  # TestClient's host is not a private IP


def test_connect_with_mfa_from_the_ui(client, tmp_path):
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    assert client.get("/api/wall").json()["mode"] == "setup"

    job = client.post("/api/accounts", json={"email": "alex@example.com", "password": "right"}).json()
    assert "password" not in json.dumps(job)
    wait_for(client, job["id"], {"mfa_required"})
    assert client.post(f"/api/jobs/{job['id']}/mfa", json={"code": "123456"}).status_code == 200
    done = wait_for(client, job["id"], {"done", "error"})
    assert done["phase"] == "done", done
    assert done["name"] == "Alex Runner" and done["result"] == {"activities": 42}
    assert done["log"] == ["Downloading activities: 100%"]
    assert (done["step"], done["step_index"], done["step_total"]) == ("Hydration", 2, 10)

    users = json.loads((tmp_path / "users.json").read_text())["users"]
    assert [u["id"] for u in users] == ["alex"]
    assert [u["id"] for u in client.get("/api/config").json()["users"]] == ["alex"]  # config reloaded
    # connecting the same Garmin account twice is refused
    again = client.post("/api/accounts", json={"email": "ALEX@example.com", "password": "right"})
    assert again.status_code == 409


def test_wrong_password_leaves_nothing_behind(client, tmp_path):
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    job = client.post("/api/accounts", json={"email": "sam@example.com", "password": "wrong"}).json()
    done = wait_for(client, job["id"], {"done", "error"})
    assert done["phase"] == "error" and "Login failed" in done["error"]
    assert not (tmp_path / "users.json").exists()
    assert not (tmp_path / "data" / "garmindb" / "sam").exists()


def test_mfa_code_when_not_asked_is_rejected(client):
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    assert client.post("/api/jobs/nope/mfa", json={"code": "123456"}).status_code == 409


@pytest.mark.parametrize("new, message", [(0, "Up to date"), (1, "1 new activity"), (3, "3 new activities")])
def test_sync_now_reports_what_arrived(client, tmp_path, monkeypatch, new, message):
    from healthdash import db
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    (tmp_path / "users.json").write_text(json.dumps({"users": [{"id": "alex", "garmindb_config_dir": "x/config"}]}))
    main.reset_config()
    conn = db.connect(tmp_path / "app.db")  # an existing activity → this is a "latest" sync, not a first download
    conn.execute("INSERT INTO sessions (id, user_id, activity_id, sport, start_time) VALUES ('alex:1','alex','1','running','2026-09-01T07:00:00')")
    conn.commit()
    fulls = []
    monkeypatch.setattr(accounts.pipeline, "ingest_from_garmindb",
                        lambda conn, user, full=False, **kw: (fulls.append(full), {"activities": new})[1])
    job = client.post("/api/users/alex/sync").json()
    done = wait_for(client, job["id"], {"done", "error"})
    assert done["phase"] == "done" and done["message"] == message
    assert fulls == [False]  # only the latest days, not the whole history
