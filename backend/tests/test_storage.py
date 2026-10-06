import sqlite3

from healthdash import db, profile, wall
from healthdash.ingest.garmindb_reader import GarminDbReader


def test_schema_is_stamped_and_older_databases_are_migrated(tmp_path):
    conn = db.connect(tmp_path / "app.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'profiles'").fetchone()

    old = sqlite3.connect(tmp_path / "old.db")  # created before vo2max_cycling and the version stamp
    old.execute("CREATE TABLE health_days (user_id TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (user_id, day))")
    old.commit()
    old.close()
    conn = db.connect(tmp_path / "old.db")
    assert "vo2max_cycling" in {r[1] for r in conn.execute("PRAGMA table_info(health_days)")}
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'readiness_days'").fetchone()


def test_reading_the_profile_never_commits_pending_writes(tmp_path):
    conn = db.connect(tmp_path / "app.db")
    conn.execute("INSERT INTO wall_state (key, value) VALUES ('k', 'v')")
    profile.stored(conn, "u")
    conn.rollback()
    assert db.get_state(conn, "k") is None


def test_baseline_sessions_come_in_one_query_in_their_order(tmp_path):
    conn = db.connect(tmp_path / "app.db")
    for i in (1, 2, 3):
        db.upsert(conn, "sessions", {"id": f"u:{i}", "user_id": "u", "activity_id": str(i), "sport": "running",
                                     "start_time": f"2026-09-0{i}T07:00:00", "features": {"ef": i}})
    assert [s["id"] for s in wall._sessions_by_id(conn, ["u:3", "gone", "u:1"])] == ["u:3", "u:1"]
    assert wall._sessions_by_id(conn, []) == []
    assert wall._sessions_by_id(conn, ["u:2"])[0]["features"] == {"ef": 2}


def test_fit_file_of_another_activity_with_the_same_prefix_is_not_used(tmp_path):
    fit_dir = tmp_path / "FitFiles" / "Activities"
    fit_dir.mkdir(parents=True)
    (fit_dir / "1234_ACTIVITY.fit").write_bytes(b"")
    reader = GarminDbReader(tmp_path)
    assert reader.find_fit("123") is None
    (fit_dir / "123_ACTIVITY.fit").write_bytes(b"")
    assert reader.find_fit("123").name == "123_ACTIVITY.fit"
    assert reader.find_fit("1234").name == "1234_ACTIVITY.fit"
