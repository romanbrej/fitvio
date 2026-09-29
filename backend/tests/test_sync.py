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
    monkeypatch.setattr(garmindb_runner, "garmindb_command", lambda: [fake_cli(tmp_path, "Failed to login!")])
    assert garmindb_runner.run_sync(conn, make_user(tmp_path, with_db=True)) is False
    row = conn.execute("SELECT * FROM sync_status").fetchone()
    assert row["last_success"] is None and "login" in row["last_error"].lower()


def test_successful_sync_records_success(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    monkeypatch.setattr(garmindb_runner, "garmindb_command", lambda: [fake_cli(tmp_path, "Download complete")])
    assert garmindb_runner.run_sync(conn, make_user(tmp_path, with_db=True)) is True
    assert conn.execute("SELECT last_success FROM sync_status").fetchone()[0]


def test_no_database_after_sync_is_a_failure(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    monkeypatch.setattr(garmindb_runner, "garmindb_command", lambda: [fake_cli(tmp_path, "ok")])
    assert garmindb_runner.run_sync(conn, make_user(tmp_path, with_db=False)) is False


def test_steps_are_reported_from_garmindb_log_and_log_stays_private(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    exe = tmp_path / "fake_steps.sh"
    # like GarminDB: truncate garmindb.log in the working dir, log each data type, print progress bars
    exe.write_text("""#!/bin/sh
: > garmindb.log
echo "INFO:root:Getting daily summaries: 2021-09-28 (1826)" >> garmindb.log; echo " 50%|#####| 913/1826"
echo "INFO:root:Getting hydration: 2021-09-28 (1826)" >> garmindb.log; echo "  3%|     | 56/1826"
echo "INFO:root:Getting hydration: 2021-09-28 (1826)" >> garmindb.log; echo "  4%|     | 70/1826"
echo "INFO:__main__:___Importing All Data___" >> garmindb.log; echo "done"
""")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(garmindb_runner, "garmindb_command", lambda: [str(exe)])
    steps = []
    user = make_user(tmp_path, with_db=True)
    assert garmindb_runner.run_sync(conn, user, on_step=lambda i, n, k, label: steps.append((i + 1, n, label)))
    assert steps == [(2, 10, "Daily summaries"), (3, 10, "Hydration"), (9, 10, "Importing into the database")]
    log = user.garmindb_dir.parent / "garmindb.log"  # not in the project root
    assert log.exists() and log.stat().st_mode & 0o077 == 0


def test_moved_project_config_is_repaired_to_relative_paths(tmp_path):
    from healthdash.ingest.garmindb_reader import base_dir_from_config
    person = tmp_path / "data" / "garmindb" / "alex"
    cfg_dir = person / "config"
    cfg_dir.mkdir(parents=True)
    old = "/Users/someone/Documents/old-place/data/garmindb/alex"
    (cfg_dir / "GarminConnectConfig.json").write_text(json.dumps({
        "directories": {"relative_to_home": False, "base_dir": f"{old}/HealthData"},
        "credentials": {"user": "a@example.com", "password_file": f"{old}/config/password.txt"}}))
    garmindb_runner.normalize_config(cfg_dir)
    cfg = json.loads((cfg_dir / "GarminConnectConfig.json").read_text())
    assert cfg["directories"]["base_dir"] == "HealthData"
    assert cfg["credentials"]["password_file"] == "config/password.txt"
    assert base_dir_from_config(cfg_dir) == person / "HealthData"
    assert (cfg_dir / "GarminConnectConfig.json").stat().st_mode & 0o077 == 0


def test_new_configs_use_relative_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(garmindb_runner, "PROJECT_ROOT", tmp_path)
    user = UserConfig(id="sam", garmindb_config_dir=str(tmp_path / "data/garmindb/sam/config"))
    cfg_dir = garmindb_runner.init_user_config(user, "sam@example.com")
    cfg = json.loads((cfg_dir / "GarminConnectConfig.json").read_text())
    assert cfg["directories"]["base_dir"] == "HealthData"
    assert cfg["credentials"]["password_file"] == "config/password.txt"
