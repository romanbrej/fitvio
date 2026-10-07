import json
import stat

from fitvio import db
from fitvio.config import UserConfig
from fitvio.sync import garmindb_runner


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
    from fitvio.ingest.garmindb_reader import base_dir_from_config
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


def test_step_times_come_from_the_timestamped_garmindb_log():
    log = ["2026-10-05 08:41:00,000 INFO:root:login: Roman",
           "2026-10-05 08:41:05,000 INFO:root:Getting activities: 'x' (25)",
           "no timestamp: ignored",
           "2026-10-05 08:41:35,000 INFO:root:Getting daily summaries: 2026-10-04 (1)",
           "2026-10-05 08:41:37,500 INFO:root:Getting monitoring: 2026-10-04 (1)",
           "2026-10-05 08:41:40,000 INFO:root:Getting monitoring: still monitoring",
           "2026-10-05 08:42:10,000 INFO:x:___Importing Latest Data___",
           "2026-10-05 08:42:50,000 INFO:x:___Analyzing Data___",
           "2026-10-05 08:43:00,000 INFO:x:done"]
    times = garmindb_runner.phase_times(log)
    assert times == {"login": 5, "activities": 30, "summaries": 2.5, "monitoring": 32.5, "import": 40, "analyze": 10}
    assert garmindb_runner.format_times(times).startswith("login 5s · activities 30s")


def test_quick_sync_fetches_health_data_only_and_keeps_the_last_full_sync(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    args = tmp_path / "args.txt"
    exe = tmp_path / "fake.sh"
    exe.write_text(f'#!/bin/sh\necho "$@" >> {args}\necho ok\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(garmindb_runner, "garmindb_command", lambda: [str(exe)])
    user = make_user(tmp_path, with_db=True)

    assert garmindb_runner.run_sync(conn, user)
    full_success = conn.execute("SELECT last_success FROM sync_status").fetchone()[0]
    conn.execute("UPDATE sync_status SET last_attempt = '2000-01-01T00:00:00'")
    assert garmindb_runner.run_sync(conn, user, quick=True)
    normal, quick = args.read_text().splitlines()
    assert "--all" in normal.split()
    assert "--all" not in quick.split() and {"--monitoring", "--sleep", "--rhr", "--hrv"} <= set(quick.split())
    assert "--activities" not in quick.split() and "--weight" not in quick.split()
    row = conn.execute("SELECT last_success, last_attempt FROM sync_status").fetchone()
    assert row["last_success"] == full_success      # the next normal sync still imports everything since then
    assert row["last_attempt"] != "2000-01-01T00:00:00"  # but the wall / cooldown see that it ran


# --- first download: from shortly before the first activity, not 5 years -------------------

def activity_pages(days):
    """A fake Garmin activity list: newest first, 100 per page."""
    rows = [{"activityId": i, "startTimeLocal": f"{d} 07:00:00"} for i, d in enumerate(sorted(days, reverse=True))]
    calls = []

    def connectapi(url, params):
        calls.append(params)
        start, limit = int(params["start"]), int(params["limit"])
        return rows[start:start + limit]
    return connectapi, calls


def test_first_activity_is_found_across_pages():
    from datetime import date, timedelta
    days = [(date(2026, 6, 1) + timedelta(days=i)).isoformat() for i in range(130)]   # 130 runs in 4 months
    connectapi, calls = activity_pages(days)
    user = UserConfig(id="sam")
    assert garmindb_runner.first_activity_day(user, connectapi) == date(2026, 6, 1)
    assert [c["start"] for c in calls] == ["0", "100"]
    assert garmindb_runner.first_activity_day(user, activity_pages([])[0]) is None          # no activities

    def broken(url, params):
        raise RuntimeError("429 Too Many Requests")
    assert garmindb_runner.first_activity_day(user, broken) is None                          # never fatal


def test_first_download_starts_two_months_before_the_first_activity(tmp_path, monkeypatch):
    from datetime import date
    from fitvio import accounts
    today = date(2026, 10, 7)
    user = UserConfig(id="sam")
    new_watch = activity_pages(["2026-06-01", "2026-09-30"])[0]
    assert garmindb_runner.first_download_start(user, today, new_watch) == date(2026, 4, 2)
    veteran = activity_pages(["2019-03-01", "2026-09-30"])[0]
    assert garmindb_runner.first_download_start(user, today, veteran) is None               # keep 5 years

    monkeypatch.setattr(garmindb_runner, "PROJECT_ROOT", tmp_path)
    user = UserConfig(id="sam", garmindb_config_dir=str(tmp_path / "data/garmindb/sam/config"))
    cfg_dir = garmindb_runner.init_user_config(user, "sam@example.com")
    before = json.loads((cfg_dir / "GarminConnectConfig.json").read_text())
    lines = []
    monkeypatch.setattr(accounts, "first_download_start", lambda u: date(2026, 4, 2))
    accounts.shorten_first_download(user, None, lines.append)
    after = json.loads((cfg_dir / "GarminConnectConfig.json").read_text())
    assert {after["data"][k] for k in garmindb_runner.START_KEYS} == {"04/02/2026"}
    assert {k: v for k, v in after["data"].items() if k not in garmindb_runner.START_KEYS} == \
        {k: v for k, v in before["data"].items() if k not in garmindb_runner.START_KEYS}
    assert (cfg_dir / "GarminConnectConfig.json").stat().st_mode & 0o077 == 0
    assert lines == ["Your first activity is from June 2026 — downloading from April 2026"]

    # an explicit start date (fitvio add-person --since) always wins
    from datetime import datetime
    garmindb_runner.set_start_date(cfg_dir, date(2021, 10, 7))
    accounts.shorten_first_download(user, datetime(2021, 10, 7), lines.append)
    assert json.loads((cfg_dir / "GarminConnectConfig.json").read_text())["data"]["sleep_start_date"] == "10/07/2021"
