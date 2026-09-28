import json
import stat

from healthdash import db
from healthdash.config import UserConfig
from healthdash.sync import garmindb_runner


def fake_cli(tmp_path, output: str, rc: int = 0):
    exe = tmp_path / "fake_garmindb.sh"
    exe.write_text(f"#!/bin/sh\necho '{output}'\nexit {rc}\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


def make_user(tmp_path, with_db: bool):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    base = tmp_path / "HealthData"
    (cfg_dir / "GarminConnectConfig.json").write_text(json.dumps(
        {"directories": {"relative_to_home": False, "base_dir": str(base)}}))
    if with_db:
        (base / "DBs").mkdir(parents=True)
        (base / "DBs" / "garmin_activities.db").write_bytes(b"")
    return UserConfig(id="u", name="U", garmindb_config_dir=str(cfg_dir))


def test_login_failure_with_exit_zero_is_a_failure(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    monkeypatch.setattr(garmindb_runner, "garmindb_cli", lambda: fake_cli(tmp_path, "Failed to login!"))
    assert garmindb_runner.run_sync(conn, make_user(tmp_path, with_db=True)) is False
    row = conn.execute("SELECT * FROM sync_status").fetchone()
    assert row["last_success"] is None and "login" in row["last_error"].lower()


def test_successful_sync_records_success(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    monkeypatch.setattr(garmindb_runner, "garmindb_cli", lambda: fake_cli(tmp_path, "Download complete"))
    assert garmindb_runner.run_sync(conn, make_user(tmp_path, with_db=True)) is True
    assert conn.execute("SELECT last_success FROM sync_status").fetchone()[0]


def test_no_database_after_sync_is_a_failure(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    monkeypatch.setattr(garmindb_runner, "garmindb_cli", lambda: fake_cli(tmp_path, "ok"))
    assert garmindb_runner.run_sync(conn, make_user(tmp_path, with_db=False)) is False
