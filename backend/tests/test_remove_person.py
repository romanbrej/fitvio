"""Removing a person and their data (#34): removal.py, DELETE /api/users/{id}."""
import json
import threading

import pytest
from fastapi.testclient import TestClient

from fitvio import accounts, buddy, config, db, heat_response, home_assistant, removal, units, wall, weather
from fitvio.api import main
from fitvio.pipeline import reprocess_key
from fitvio.sync import activity_watch
from fitvio.sync.garmindb_runner import SyncBusy, UserRemoved, sync_lock

PEOPLE = ("alex", "alex_2")  # one id is a prefix of the other: removing alex must not touch alex_2


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FITVIO_CONFIG", str(tmp_path / "users.json"))
    monkeypatch.setenv("FITVIO_DB", str(tmp_path / "app.db"))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    main.reset_config()
    (tmp_path / "users.json").write_text(json.dumps({"users": [
        {"id": "alex", "garmindb_config_dir": "data/garmindb/alex/config"},
        {"id": "alex_2", "intervals_dir": "data/intervals/alex_2"},
    ]}))
    (tmp_path / "data" / "garmindb" / "alex" / "config").mkdir(parents=True)
    (tmp_path / "data" / "garmindb" / "alex" / "config" / "password.txt").write_text("secret")
    (tmp_path / "data" / "intervals" / "alex_2").mkdir(parents=True)
    (tmp_path / "data" / "intervals" / "alex_2" / "credentials.json").write_text("{}")
    conn = db.connect(tmp_path / "app.db")
    for uid in PEOPLE:
        fill(conn, uid)
    conn.close()
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    yield tmp_path
    main.app.dependency_overrides.clear()
    main.reset_config()


def fill(conn, uid):
    """A row in every table and every per-person setting, written the way the app writes them."""
    sid = f"{uid}:1"
    conn.execute("INSERT INTO sessions (id, user_id, activity_id, sport, start_time) VALUES (?, ?, '1', 'running', ?)",
                 (sid, uid, wall._now().isoformat(timespec="seconds")))
    conn.execute("INSERT INTO session_streams VALUES (?, '{}')", (sid,))
    conn.execute("INSERT INTO exercise_sets (session_id, set_index, exercise) VALUES (?, 0, 'squat')", (sid,))
    conn.execute("INSERT INTO verdicts (session_id, user_id, created_at, verdict, confidence) VALUES (?, ?, 'x', 'better', 'high')",
                 (sid, uid))
    conn.execute("INSERT INTO health_days (user_id, day) VALUES (?, '2026-10-01')", (uid,))
    conn.execute("INSERT INTO sync_status (user_id) VALUES (?)", (uid,))
    conn.execute("INSERT INTO planned_workouts (user_id, day, key) VALUES (?, '2026-10-13', 'k')", (uid,))
    conn.execute("INSERT INTO readiness_days (user_id, day) VALUES (?, '2026-10-01')", (uid,))
    conn.execute("INSERT INTO baseline_exclusions VALUES (?, ?, 'x')", (sid, uid))
    conn.execute("INSERT INTO profiles (user_id, field, value) VALUES (?, 'name', ?)", (uid, json.dumps("Alex")))
    units.set_for_user(conn, uid, "imperial")
    weather.set_enabled(conn, uid, False)
    weather.set_wind_enabled(conn, uid, False)
    heat_response.set_enabled(conn, uid, False)
    wall.set_trend_period(conn, uid, 90)
    buddy.set_animal(conn, uid, "fox")
    buddy.set_shown(conn, uid, False)
    home_assistant.set_shared(conn, uid, True)
    db.set_state(conn, f"ha.{uid}.announced", "2026-10-01T07:00:00")
    for key in (reprocess_key(uid), f"analysis_version:{uid}", f"morning.{uid}", f"max_hr_dismissed:{uid}",
                heat_response.STATE.format(user_id=uid, sport="running"), activity_watch._k(uid, "last_check")):
        db.set_state(conn, key, "1")
    db.set_state(conn, "selected_user", uid)
    conn.commit()


def rows_of(conn, uid):
    n = {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id = ?", (uid,)).fetchone()[0]
         for t in removal.USER_TABLES}
    n.update({t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE session_id = ?", (f"{uid}:1",)).fetchone()[0]
              for t in removal.SESSION_TABLES})
    return n


def state_keys(conn):
    return {r[0] for r in conn.execute("SELECT key FROM wall_state WHERE key != 'selected_user'")}


def test_remove_deletes_every_row_setting_and_the_folder_of_that_person_only(env):
    conn = db.connect(env / "app.db")
    keys_2 = {k for k in state_keys(conn) if "alex_2" in k}
    r = TestClient(main.app).delete("/api/users/alex")
    assert r.status_code == 200 and r.json() == {"removed": "alex", "pending": False}

    assert set(rows_of(conn, "alex").values()) == {0}
    assert set(rows_of(conn, "alex_2").values()) == {1}
    assert state_keys(conn) == keys_2  # every alex setting gone, every alex_2 one kept
    assert not (env / "data" / "garmindb" / "alex").exists()
    assert (env / "data" / "intervals" / "alex_2" / "credentials.json").exists()
    assert json.loads((env / "users.json").read_text()) == {
        "users": [{"id": "alex_2", "intervals_dir": "data/intervals/alex_2"}]}
    assert [u["id"] for u in TestClient(main.app).get("/api/config").json()["users"]] == ["alex_2"]


def test_remove_is_refused_outside_the_home_network_and_for_unknown_people(env):
    main.app.dependency_overrides.clear()
    assert TestClient(main.app).delete("/api/users/alex").status_code == 403
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    # another website open in a browser on the home network can't remove anyone
    assert TestClient(main.app).delete("/api/users/alex", headers={"Origin": "http://evil.example"}).status_code == 403
    assert TestClient(main.app).delete("/api/users/alex", headers={"Host": "evil.example"}).status_code == 421
    assert TestClient(main.app).delete("/api/users/nobody").status_code == 404
    assert TestClient(main.app).delete("/api/users/..%2Fdata").status_code in (404, 405)  # never reaches a person
    assert (env / "data" / "garmindb" / "alex").exists()
    assert len(json.loads((env / "users.json").read_text())["users"]) == 2


def test_a_running_sync_finishes_first_and_the_person_is_gone_from_the_wall_at_once(env):
    alex = config.load_config().user("alex")
    held, release = threading.Event(), threading.Event()

    def sync():  # another process's (or thread's) sync of alex
        with sync_lock(alex):
            held.set()
            release.wait(5)

    t = threading.Thread(target=sync)
    t.start()
    held.wait(5)
    client = TestClient(main.app)
    assert client.delete("/api/users/alex").json() == {"removed": "alex", "pending": True}
    assert [u["id"] for u in client.get("/api/config").json()["users"]] == ["alex_2"]
    assert client.get("/api/users/alex/sessions").status_code == 404
    conn = db.connect(env / "app.db")
    conn.execute("DELETE FROM verdicts WHERE user_id = 'alex_2'")
    conn.commit()
    assert wall.fresh_verdict(conn, config.load_config()) is None  # alex's fresh run never takes over the wall
    assert rows_of(conn, "alex")["sessions"] == 1  # nothing deleted under the running sync
    assert (env / "data" / "garmindb" / "alex" / "config").exists()
    assert accounts.new_user_id("alex@example.com") == "alex_3"  # the id stays taken meanwhile

    release.set()
    t.join()
    assert removal.purge_pending() == []
    assert set(rows_of(conn, "alex").values()) == {0}
    assert not (env / "data" / "garmindb" / "alex").exists()
    assert "removing" not in json.loads((env / "users.json").read_text())
    assert accounts.new_user_id("alex@example.com") == "alex"  # free again: re-adding works cleanly
    config.add_user("alex", "data/garmindb/alex/config")
    assert [u.id for u in config.load_config().users] == ["alex_2", "alex"]


def test_a_sync_with_the_old_config_neither_runs_nor_brings_the_folder_back(env):
    stale = config.load_config().user("alex")
    config.remove_user("alex")
    with pytest.raises(UserRemoved):  # removal pending: the lock refuses
        with sync_lock(stale):
            pass
    assert removal.purge_pending() == []
    with pytest.raises(UserRemoved):  # removed: no folder, and none is created
        with sync_lock(stale):
            pass
    assert not (env / "data" / "garmindb" / "alex").exists()
    assert issubclass(UserRemoved, SyncBusy)  # every sync loop already skips it quietly


def test_the_lock_is_reentrant_within_a_job_but_not_across_threads(env):
    alex = config.load_config().user("alex")
    with sync_lock(alex):
        with sync_lock(alex):  # run_sync inside a job that already holds it
            pass
        failed = []
        t = threading.Thread(target=lambda: failed.append(_try_lock(alex)))
        t.start()
        t.join()
        assert failed == [True]


def _try_lock(user):
    try:
        with sync_lock(user):
            return False
    except SyncBusy:
        return True


def test_removing_during_the_first_download_stops_it(env):
    class Proc:
        killed = False

        def kill(self):
            self.killed = True

    job = accounts._add(accounts.Job(kind="connect", user_id="alex", phase="downloading"))
    job._proc = Proc()
    accounts.remove("alex")
    assert job._proc.killed
    with pytest.raises(accounts.JobCancelled):  # an Intervals.icu download stops at its next activity
        job.line("activity 12/400")
    job.phase = "error"


def test_a_reprocess_or_sync_job_is_left_to_finish(env):
    class Proc:
        killed = False

        def kill(self):
            self.killed = True

    job = accounts._add(accounts.Job(kind="sync", user_id="alex", phase="downloading"))
    job._proc = Proc()
    accounts.remove("alex")
    assert not job._proc.killed
    job.line("still going")
    job.phase = "done"


def test_only_folders_fitvio_made_are_deleted(env, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    hand_made = config.UserConfig(id="sam", garmindb_config_dir=str(outside / "config"))
    assert removal.safe_data_dir(hand_made) is None
    sneaky = config.UserConfig(id="sam", garmindb_config_dir="data/garmindb/alex/../../../elsewhere/config")
    assert removal.safe_data_dir(sneaky) is None
    (tmp_path / "data" / "garmindb" / "sam").symlink_to(outside)
    linked = config.UserConfig(id="sam", garmindb_config_dir="data/garmindb/sam/config")
    assert removal.safe_data_dir(linked) is None
    other = config.UserConfig(id="sam", garmindb_config_dir="data/garmindb/alex/config")  # someone else's folder
    assert removal.safe_data_dir(other) is None
    assert (outside / "keep.txt").exists()


def test_removing_the_last_person_brings_back_the_setup_screen(env):
    client = TestClient(main.app)
    client.delete("/api/users/alex")
    client.delete("/api/users/alex_2")
    assert client.get("/api/wall").json()["mode"] == "setup"
    assert json.loads((env / "users.json").read_text()) == {"users": []}
    assert not list((env / "data" / "garmindb").iterdir()) and not list((env / "data" / "intervals").iterdir())
    conn = db.connect(env / "app.db")
    assert conn.execute("SELECT COUNT(*) FROM wall_state WHERE key LIKE '%alex%' OR value LIKE '%alex%'").fetchone()[0] == 0


def test_removed_right_after_connecting_ends_the_job_and_leaves_nothing(env, monkeypatch):
    import time
    monkeypatch.setattr(accounts, "login_interactive", lambda user, mfa_prompt=None: "Pat Runner")
    monkeypatch.setattr(accounts, "run_sync", lambda *a, **kw: pytest.fail("no download for a removed person"))
    job = accounts.start_connect("pat@example.com", "pw", env / "app.db",
                                 on_registered=lambda: (config.remove_user("pat"), accounts.remove("pat")))
    for _ in range(200):
        if not job.active:
            break
        time.sleep(0.02)
    assert job.phase == "error" and job.error == "This person was removed"
    assert not (env / "data" / "garmindb" / "pat").exists()  # the purge ran when the job let go
    assert "removing" not in json.loads((env / "users.json").read_text())
    assert not accounts._connect_active()  # the next person can be connected


def _slow_garmindb(tmp_path, monkeypatch):
    import sys
    from fitvio.sync import garmindb_runner
    cfg_dir = tmp_path / "data" / "garmindb" / "pat" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "GarminConnectConfig.json").write_text(json.dumps(
        {"directories": {"relative_to_home": False, "base_dir": str(tmp_path / "HealthData")}}))
    monkeypatch.setattr(garmindb_runner, "garmindb_command",
                        lambda: [sys.executable, "-c", "import time; print('start', flush=True); time.sleep(60)"])
    return garmindb_runner, db.connect(tmp_path / "app.db"), config.UserConfig(id="pat", garmindb_config_dir=str(cfg_dir))


def test_garmindb_is_stopped_when_removed_before_it_started(tmp_path, monkeypatch):
    runner, conn, user = _slow_garmindb(tmp_path, monkeypatch)
    job = accounts.Job(kind="connect", user_id="pat", phase="downloading")
    job._cancel.set()  # Remove came between registration and GarminDB's start: no process to kill yet
    seen = []
    assert not runner.run_sync(conn, user, on_line=job.line,
                               on_proc=lambda p: (seen.append(p), accounts._keep_proc(job, p)))
    assert seen[0].poll() is not None  # killed as soon as it existed


def test_garmindb_is_stopped_when_its_download_is_abandoned(tmp_path, monkeypatch):
    """The output loop ends early (here: a removal noticed on the first line): GarminDB must not go on
    writing into a folder that is being deleted."""
    runner, conn, user = _slow_garmindb(tmp_path, monkeypatch)
    job = accounts.Job(kind="connect", user_id="pat", phase="downloading")
    seen = []

    def started(p):
        seen.append(p)
        job._cancel.set()  # removed while it runs, before remove() could see the process

    with pytest.raises(accounts.JobCancelled):
        runner.run_sync(conn, user, on_line=job.line, on_proc=started)
    assert seen[0].poll() is not None


def test_an_id_that_is_a_path_is_never_deleted(env, tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    for bad in ("../../config", "..", "a/b"):
        crafted = config.UserConfig(id=bad, garmindb_config_dir=f"data/garmindb/{bad}/config")
        assert removal.safe_data_dir(crafted) is None
    assert (tmp_path / "config").exists()
