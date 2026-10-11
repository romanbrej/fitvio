"""#32: GarminDB stores a US Garmin account's data in its own units (lb, mi, ft, mph, °F); Fitvio reads SI."""
import datetime
import sqlite3

import pytest

from fitvio import db, pipeline
from fitvio.activity import ParsedActivity
from fitvio.config import UserConfig
from fitvio.ingest.garmindb_reader import GarminDbReader

from .test_analytics import steady_records


def make_dbs(base, system=None):
    (base / "DBs").mkdir()
    with sqlite3.connect(base / "DBs" / "garmin.db") as c:
        c.execute("CREATE TABLE weight (day DATE PRIMARY KEY, weight FLOAT)")
        c.execute("INSERT INTO weight VALUES ('2026-10-01', ?)", (165.35 if system == "statute" else 75.0,))
        if system:
            c.execute("CREATE TABLE attributes (timestamp DATETIME, key VARCHAR PRIMARY KEY, value VARCHAR)")
            c.execute("INSERT INTO attributes VALUES ('2026-10-01 07:00:00', 'measurement_system', ?)",
                      (f"DisplayMeasure.{system}",))
    statute = system == "statute"
    with sqlite3.connect(base / "DBs" / "garmin_activities.db") as c:
        c.execute("CREATE TABLE activities (activity_id VARCHAR PRIMARY KEY, name VARCHAR, sport VARCHAR, "
                  "sub_sport VARCHAR, start_time DATETIME, elapsed_time TIME, moving_time TIME, distance FLOAT, "
                  "ascent FLOAT, avg_hr INTEGER, max_hr INTEGER, self_eval_feel VARCHAR, self_eval_effort VARCHAR, "
                  "start_lat FLOAT, start_long FLOAT)")
        c.execute("INSERT INTO activities VALUES ('1', 'Run', 'running', 'generic', '2026-10-01 07:00:00', "
                  "'00:50:00', '00:50:00', ?, ?, 140, 160, NULL, NULL, NULL, NULL)",
                  (6.2137119 if statute else 10.0, 328.084 if statute else 100.0))
        c.execute("CREATE TABLE activity_records (activity_id VARCHAR, record INTEGER, timestamp DATETIME, "
                  "hr INTEGER, speed FLOAT, distance FLOAT, altitude FLOAT, cadence INTEGER, temperature FLOAT)")
        c.execute("INSERT INTO activity_records VALUES ('1', 1, '2026-10-01 07:10:00', 140, ?, ?, ?, 85, ?)",
                  (8.0530 if statute else 12.96, 1.0 if statute else 1.609344,
                   328.084 if statute else 100.0, 68.0 if statute else 20.0))
        c.execute("CREATE TABLE activity_laps (activity_id VARCHAR, lap INTEGER, start_time DATETIME, "
                  "elapsed_time TIME, moving_time TIME, distance FLOAT, avg_hr INTEGER, avg_speed FLOAT)")
        c.execute("INSERT INTO activity_laps VALUES ('1', 0, '2026-10-01 07:00:00', '00:05:00', '00:05:00', ?, 140, ?)",
                  (1.0 if statute else 1.609344, 12.0 if statute else 19.312128))


@pytest.mark.parametrize("system", ["statute", "metric", None])
def test_garmindb_values_are_read_as_si_whatever_the_account_units(tmp_path, system):
    make_dbs(tmp_path, system)
    r = GarminDbReader(tmp_path)
    assert r.statute is (system == "statute")
    [day] = r.health_days(datetime.datetime(2026, 9, 1))
    assert day["weight_kg"] == pytest.approx(75.0, abs=0.01)
    act = r.load_activity("1")  # no FIT file: summary, records and laps from the DB
    assert act.distance_m == pytest.approx(10000, abs=1)
    assert act.ascent_m == pytest.approx(100, abs=0.01)
    [rec] = act.records
    assert (rec.speed, rec.distance, rec.altitude, rec.temperature) == pytest.approx((3.6, 1609.344, 100, 20), abs=0.01)
    [lap] = act.laps
    assert (lap.distance_m, lap.avg_speed) == pytest.approx((1609.344, 5.36448), abs=0.01)


def test_new_analysis_version_rereads_every_stored_health_day(tmp_path, monkeypatch):
    """Weight rows imported before the fix were stored in lb: a deploy rewrites all of them, not just 14 days."""
    conn = db.connect(tmp_path / "app.db")
    user = UserConfig(id="u", garmindb_config_dir=str(tmp_path / "cfg"), max_hr=190, rest_hr=50)
    start = (datetime.datetime.now() - datetime.timedelta(days=2)).replace(microsecond=0)
    act = ParsedActivity(activity_id="7", start_time=start, sport="running", name="Run", duration_s=2700,
                         distance_m=8000, records=steady_records(minutes=45, hr=137))
    pipeline.store_activity(conn, user, act)
    pipeline.store_health(conn, "u", [{"day": "2024-03-01", "weight_kg": 165.35}])
    asked = []

    class FakeReader:
        def __init__(self, base):
            self.base, self.db_dir, self.available = base, base, True

        def activity_ids(self, since):
            return [("7", str(start))]

        def changed_activity_ids(self, since):
            return set()

        def load_activity(self, aid):
            return act

        def health_days(self, since):
            asked.append(since)
            return [{"day": "2024-03-01", "weight_kg": 75.0}] if since.date() <= datetime.date(2024, 3, 1) else []

    import fitvio.ingest.garmindb_reader as reader_mod
    monkeypatch.setattr(reader_mod, "GarminDbReader", FakeReader)
    monkeypatch.setattr(reader_mod, "base_dir_from_config", lambda d: tmp_path)
    monkeypatch.setattr(pipeline.profile, "refresh", lambda conn, user, base: False)

    db.set_state(conn, "analysis_version:u", "10")
    assert pipeline.ingest_from_garmindb(conn, user)["reprocessed"] is True
    assert asked[-1].date() == datetime.date(2024, 3, 1)
    assert conn.execute("SELECT weight_kg FROM health_days WHERE user_id = 'u'").fetchone()[0] == 75.0
    pipeline.ingest_from_garmindb(conn, user)  # up to date again: back to the recent days only
    assert asked[-1].date() > datetime.date.today() - datetime.timedelta(days=15)


def test_update_reprocesses_newest_first_and_shows_the_progress(tmp_path, monkeypatch):
    """#32 follow-up: the first sync after an update recalculates the whole history. Oldest first, today's
    run kept its old distance until the very end (minutes on a small server) while the weight was already
    fixed, so it looked like the fix had broken distances. Newest first, with the progress on the wall."""
    from fitvio import wall
    from fitvio.config import AppConfig

    conn = db.connect(tmp_path / "app.db")
    user = UserConfig(id="u", garmindb_config_dir=str(tmp_path / "cfg"), max_hr=190, rest_hr=50)
    now = datetime.datetime.now().replace(microsecond=0)
    starts = {str(i): now - datetime.timedelta(days=30 - i) for i in range(1, 31)}

    def act(aid, distance_m):
        return ParsedActivity(activity_id=aid, start_time=starts[aid], sport="running", name="Run", duration_s=2700,
                              distance_m=distance_m, records=steady_records(minutes=45, hr=137))

    for aid in starts:  # stored by the old version: miles read as km
        pipeline.store_activity(conn, user, act(aid, 5906))
    db.set_state(conn, "analysis_version:u", "10")
    order, progress = [], []

    class FakeReader:
        def __init__(self, base):
            self.base, self.db_dir, self.available = base, base, True

        def activity_ids(self, since):
            return [(aid, str(s)) for aid, s in starts.items()]

        def changed_activity_ids(self, since):
            return set()

        def load_activity(self, aid):
            order.append(aid)
            progress.append(wall.sync_info(conn, AppConfig(users=[user]), "u")["reprocessing"])
            return act(aid, 9511)

        def health_days(self, since):
            return []

    import fitvio.ingest.garmindb_reader as reader_mod
    monkeypatch.setattr(reader_mod, "GarminDbReader", FakeReader)
    monkeypatch.setattr(reader_mod, "base_dir_from_config", lambda d: tmp_path)
    monkeypatch.setattr(pipeline.profile, "refresh", lambda conn, user, base: False)

    assert pipeline.ingest_from_garmindb(conn, user)["reprocessed"] is True
    assert order == sorted(starts, key=int, reverse=True)  # today's run first
    assert progress[0] == {"done": 0, "total": 30} and progress[25] == {"done": 25, "total": 30}
    assert wall.sync_info(conn, AppConfig(users=[user]), "u")["reprocessing"] is None  # done: back to "Synced …"
    assert {r[0] for r in conn.execute("SELECT distance_m FROM sessions")} == {9511}


def test_an_interrupted_reprocess_does_not_leave_the_label_behind(tmp_path, monkeypatch):
    """A reprocess for a new max HR that crashes halfway isn't repeated by the next sync (the version is
    current and the HR didn't move again): that sync must still clear the "Updating history" progress."""
    from fitvio import wall
    from fitvio.config import AppConfig

    conn = db.connect(tmp_path / "app.db")
    user = UserConfig(id="u", garmindb_config_dir=str(tmp_path / "cfg"), max_hr=190, rest_hr=50)
    start = (datetime.datetime.now() - datetime.timedelta(days=2)).replace(microsecond=0)
    act = ParsedActivity(activity_id="7", start_time=start, sport="running", name="Run", duration_s=2700,
                         distance_m=8000, records=steady_records(minutes=45, hr=137))
    pipeline.store_activity(conn, user, act)
    db.set_state(conn, "analysis_version:u", pipeline.ANALYSIS_VERSION)
    crash = [True]

    class FakeReader:
        def __init__(self, base):
            self.base, self.db_dir, self.available = base, base, True

        def activity_ids(self, since):
            return [("7", str(start))]

        def changed_activity_ids(self, since):
            return set()

        def load_activity(self, aid):
            if crash[0]:
                raise RuntimeError("corrupt file")
            return act

        def health_days(self, since):
            return []

    import fitvio.ingest.garmindb_reader as reader_mod
    monkeypatch.setattr(reader_mod, "GarminDbReader", FakeReader)
    monkeypatch.setattr(reader_mod, "base_dir_from_config", lambda d: tmp_path)
    monkeypatch.setattr(pipeline.profile, "refresh", lambda conn, user, base: True)  # a new max HR
    with pytest.raises(RuntimeError):
        pipeline.ingest_from_garmindb(conn, user)
    assert wall.sync_info(conn, AppConfig(users=[user]), "u")["reprocessing"] is None  # cleared on the way out

    db.set_state(conn, pipeline.reprocess_key("u"), "25/400")  # killed outright (restart): nothing ran
    crash[0] = False
    monkeypatch.setattr(pipeline.profile, "refresh", lambda conn, user, base: False)
    assert pipeline.ingest_from_garmindb(conn, user)["reprocessed"] is False
    assert wall.sync_info(conn, AppConfig(users=[user]), "u")["reprocessing"] is None
