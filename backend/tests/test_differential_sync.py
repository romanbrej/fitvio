"""Differential sync: only what is new or changed since the last successful sync is imported."""
import datetime
import json
import os
import stat
import time
from types import SimpleNamespace

import pytest

from healthdash import accounts, db, pipeline
from healthdash.activity import ParsedActivity
from healthdash.config import UserConfig
from healthdash.sync import garmindb_fast as fast
from healthdash.sync import garmindb_runner

from .test_analytics import steady_records


@pytest.fixture(autouse=True)
def isolate_patches(monkeypatch):
    """The differential patches replace GarminDB class attributes — restore them after each test."""
    from idbutils.file_processor import FileProcessor

    import garmindb.analyze as an
    monkeypatch.setattr(FileProcessor, "dir_to_files", FileProcessor.dir_to_files)
    monkeypatch.setattr(an.Analyze, "summary", an.Analyze.summary)
    monkeypatch.setattr(fast.time, "sleep", lambda s: None)


def touch(path, age_s):
    path.write_text("{}")
    t = time.time() - age_s
    os.utime(path, (t, t))


def test_import_only_takes_files_written_since_last_sync(tmp_path):
    from idbutils.file_processor import FileProcessor
    touch(tmp_path / "sleep_2021-01-01.json", age_s=3 * 86400)   # imported long ago
    touch(tmp_path / "sleep_2026-09-28.json", age_s=10)          # written by this sync
    fast._patch_differential_import(datetime.datetime.now() - datetime.timedelta(hours=1))
    latest = FileProcessor.dir_to_files(str(tmp_path), r"sleep_.*\.json", latest=True)
    assert [os.path.basename(f) for f in latest] == ["sleep_2026-09-28.json"]
    # a full (non-latest) import still sees everything
    assert len(FileProcessor.dir_to_files(str(tmp_path), r"sleep_.*\.json", latest=False)) == 2


def test_analyze_only_recalculates_affected_years(monkeypatch):
    import garmindb.analyze as an
    monkeypatch.setattr(an.Monitoring, "get_years", lambda db: [2021, 2022, 2025, 2026])
    monkeypatch.setattr(an.Activities, "get_years", lambda db: [2023, 2026])
    monkeypatch.setattr(an.SleepEvents, "get_years", lambda db: [])
    fast._patch_differential_import(datetime.datetime(2026, 9, 29, 8, 0))
    done = []
    fake = SimpleNamespace(garmin_mon_db=None, garmin_act_db=None, garmin_db=None,
                           _Analyze__calculate_year=lambda year: done.append(year))
    an.Analyze.summary(fake)
    assert done == [2026]


class FakeDownload:
    download_days_overlap = 3
    garmin_connect_activity_service_url = "/activity"

    def __init__(self, summaries, details):
        self.summaries, self.details = summaries, details
        self.detail_requests, self.fit_downloads, self.extra_requests = [], [], []
        self.garmin = SimpleNamespace(connectapi=self._connectapi)

    def _connectapi(self, url):
        if url.endswith("/weather"):
            self.extra_requests.append(url)
            return {"temp": 75, "dewPoint": 59}
        if "/maxmet/daily/" in url:
            self.extra_requests.append(url)
            return []
        if "heataltitudeacclimation" in url:
            self.extra_requests.append(url)
            return {"heatAcclimationPercentage": 8}
        aid = url.rsplit("/", 1)[1]
        self.detail_requests.append(aid)
        return self.details[aid]

    def _Download__get_activity_summaries(self, start, count):
        return self.summaries

    def _Download__save_activity_file(self, aid):
        self.fit_downloads.append(aid)

    def _Download__unzip_files(self, directory):
        pass


def summary(aid, days_ago, name="Run"):
    day = datetime.date.today() - datetime.timedelta(days=days_ago)
    return {"activityId": int(aid), "activityName": name, "startTimeLocal": f"{day} 07:00:00"}


def save(directory, base, data, age_s=10 * 86400):
    p = directory / f"{base}.json"
    p.write_text(json.dumps(data))
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


@pytest.fixture
def act_dir(tmp_path):
    d = tmp_path / "HealthData" / "FitFiles" / "Activities"
    d.mkdir(parents=True)
    return d


def test_activities_compared_with_saved_copies(act_dir):
    tmp_path = act_dir
    old = summary("1", 30)
    renamed = summary("2", 30, name="Tempo 10k")
    recent = summary("3", 1)
    for s in (old, renamed, recent):
        aid = str(s["activityId"])
        save(tmp_path, f"activity_{aid}", {**s, "activityName": "Run"})
        save(tmp_path, f"activity_details_{aid}", {"summaryDTO": {"directWorkoutFeel": 50}})
        (tmp_path / f"{aid}.fit").write_bytes(b"")
    new = summary("4", 0)
    details = {"1": {"summaryDTO": {"directWorkoutFeel": 50}}, "2": {"summaryDTO": {"directWorkoutFeel": 50}},
               "3": {"summaryDTO": {"directWorkoutFeel": 75}},  # feel added after the run
               "4": {"summaryDTO": {}}}
    d = FakeDownload([old, renamed, recent, new], details)
    before = {p.name: p.stat().st_mtime for p in tmp_path.glob("*.json")}

    fast.get_activities(d, str(tmp_path), 25)

    assert sorted(d.detail_requests) == ["2", "3", "4"]   # old + unchanged: no request at all
    assert sum("/maxmet/daily/" in u for u in d.extra_requests) == 1  # precise VO2max: one request per sync
    assert d.fit_downloads == ["4"]                       # recordings of known activities never again
    after = {p.name: p.stat().st_mtime for p in tmp_path.glob("*.json")}
    assert after["activity_1.json"] == before["activity_1.json"]            # untouched → not re-imported
    assert after["activity_details_1.json"] == before["activity_details_1.json"]
    assert json.loads((tmp_path / "activity_2.json").read_text())["activityName"] == "Tempo 10k"
    assert after["activity_details_3.json"] > before["activity_details_3.json"]  # feel changed → rewritten
    assert (tmp_path / "activity_4.json").exists()


def test_recent_but_unchanged_activity_is_not_rewritten(act_dir):
    tmp_path = act_dir
    (act_dir.parent.parent / "Extras").mkdir()
    for f in ("weather_3.json", f"acclimation_{summary('3', 1)['startTimeLocal'][:10]}.json"):
        (act_dir.parent.parent / "Extras" / f).write_text("{}")  # extras already there → no requests
    recent = summary("3", 1)
    save(tmp_path, "activity_3", recent)
    p = save(tmp_path, "activity_details_3", {"summaryDTO": {"directWorkoutFeel": 50}})
    (tmp_path / "3.fit").write_bytes(b"")
    before = p.stat().st_mtime
    d = FakeDownload([recent], {"3": {"summaryDTO": {"directWorkoutFeel": 50}}})
    fast.get_activities(d, str(tmp_path), 25)
    assert d.detail_requests == ["3"]          # checked …
    assert p.stat().st_mtime == before         # … but identical, so it is not imported again


def test_run_sync_passes_last_sync_start_only_for_latest(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    cfg_dir = tmp_path / "p" / "config"
    cfg_dir.mkdir(parents=True)
    (tmp_path / "p" / "HealthData" / "DBs").mkdir(parents=True)
    (tmp_path / "p" / "HealthData" / "DBs" / "garmin_activities.db").write_bytes(b"")
    (cfg_dir / "GarminConnectConfig.json").write_text(json.dumps(
        {"directories": {"relative_to_home": False, "base_dir": "HealthData"}}))
    seen = tmp_path / "seen.txt"
    exe = tmp_path / "fake.sh"
    exe.write_text(f'#!/bin/sh\necho "${{HEALTHDASH_SYNC_SINCE:-none}}" >> {seen}\necho ok\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(garmindb_runner, "garmindb_command", lambda: [str(exe)])
    user = UserConfig(id="u", garmindb_config_dir=str(cfg_dir))

    assert garmindb_runner.run_sync(conn, user)               # first ever sync: nothing to compare with
    first_start = conn.execute("SELECT last_success FROM sync_status").fetchone()[0]
    assert garmindb_runner.run_sync(conn, user)               # latest sync: changes since the last start
    assert garmindb_runner.run_sync(conn, user, full=True)    # full: everything
    lines = seen.read_text().split()
    expected = (datetime.datetime.fromisoformat(first_start) - garmindb_runner.SINCE_MARGIN).isoformat()
    assert lines == ["none", expected, "none"]


def test_edited_activity_is_reingested_without_retaking_the_wall(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "app.db")
    user = UserConfig(id="u", garmindb_config_dir=str(tmp_path / "cfg"), max_hr=190, rest_hr=50)
    start = (datetime.datetime.now() - datetime.timedelta(hours=2)).replace(microsecond=0)

    def act(name, feel):
        return ParsedActivity(activity_id="7", start_time=start, sport="running", name=name, duration_s=2700,
                              distance_m=8000, records=steady_records(minutes=45, hr=137), feel=feel)

    sid = pipeline.store_activity(conn, user, act("Run", None))
    pipeline.evaluate_session(conn, "u", sid)
    conn.execute("UPDATE verdicts SET first_shown_at = '2026-09-29T07:00:00'")
    conn.commit()
    db.set_state(conn, "analysis_version:u", pipeline.ANALYSIS_VERSION)

    class FakeReader:
        def __init__(self, base):
            self.base, self.db_dir, self.available = base, base, True

        def activity_ids(self, since):
            return [("7", str(start))]

        def changed_activity_ids(self, since):
            return {"7"}

        def load_activity(self, aid):
            return act("Morning Tempo", 75)

        def health_days(self, since):
            return []

    import healthdash.ingest.garmindb_reader as reader_mod
    monkeypatch.setattr(reader_mod, "GarminDbReader", FakeReader)
    monkeypatch.setattr(reader_mod, "base_dir_from_config", lambda d: tmp_path)
    monkeypatch.setattr(pipeline.profile, "refresh", lambda conn, user, base: False)

    result = pipeline.ingest_from_garmindb(conn, user, changed_since=start)
    assert (result["activities"], result["updated"]) == (0, 1)
    row = conn.execute("SELECT name, feel FROM sessions WHERE id = ?", (sid,)).fetchone()
    assert (row["name"], row["feel"]) == ("Morning Tempo", 75)
    shown = conn.execute("SELECT first_shown_at FROM verdicts WHERE session_id = ?", (sid,)).fetchone()[0]
    assert shown == "2026-09-29T07:00:00"

    # a new analysis version (after a deploy) reprocesses the whole history once, then stays differential
    db.set_state(conn, "analysis_version:u", "old")
    assert pipeline.ingest_from_garmindb(conn, user, changed_since=start)["reprocessed"] is True
    assert db.get_state(conn, "analysis_version:u") == pipeline.ANALYSIS_VERSION
    assert pipeline.ingest_from_garmindb(conn, user, changed_since=start)["reprocessed"] is False


@pytest.mark.parametrize("result, full, text", [
    ({"activities": 0, "updated": 0}, False, "Up to date"),
    ({"activities": 1, "updated": 2}, False, "1 new activity · 2 updated"),
    ({"activities": 0, "updated": 1}, False, "1 updated"),
    ({"activities": 312}, True, "312 activities imported"),
])
def test_result_message(result, full, text):
    assert accounts.result_message(result, full) == text


def test_non_numeric_activity_ids_never_become_file_names(act_dir):
    tmp_path = act_dir
    evil = {"activityId": "../../config/password", "activityName": "x", "startTimeLocal": "2026-09-29 07:00:00"}
    d = FakeDownload([evil], {})
    fast.get_activities(d, str(tmp_path), 25)
    assert list(tmp_path.iterdir()) == [] and d.detail_requests == []
