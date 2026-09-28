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
