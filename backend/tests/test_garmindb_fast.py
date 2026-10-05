import datetime
import json

import pytest

import garmindb.download as dl
from healthdash.sync import garmindb_fast as fast


class FakeDownload:
    download_days_overlap = 3

    def __init__(self):
        self.calls = []

    def _Download__get_sleep_day(self, directory, day, overwrite=False):
        self.calls.append(day)
        (directory / f"sleep_{day}.json").write_text("{}")

    def _Download__get_monitoring_day(self, day):
        self.calls.append(day)
        (datetime.date.today() - day).days  # noqa: B018  (would hit the network)

    def _Download__unzip_files(self, outdir):
        pass


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(fast.time, "sleep", lambda s: None)


def sleep_fn(obj):
    # bound method whose __name__ matches GarminDB's private day function
    def __get_sleep_day(directory, day, overwrite=False):
        return obj._Download__get_sleep_day(directory, day, overwrite)
    return __get_sleep_day


def test_cached_days_are_skipped_but_recent_days_refreshed(tmp_path):
    d = FakeDownload()
    start = datetime.date.today() - datetime.timedelta(days=9)
    for n in range(10):  # everything already on disk
        (tmp_path / f"sleep_{start + datetime.timedelta(days=n)}.json").write_text("{}")
    fast.get_stat(d, sleep_fn(d), tmp_path, start, 10, overwrite=False)
    # only the last `download_days_overlap` days (+ today) are fetched again
    assert d.calls == [start + datetime.timedelta(days=n) for n in range(6, 10)]


def test_missing_days_are_fetched(tmp_path):
    d = FakeDownload()
    start = datetime.date(2022, 1, 1)
    fast.get_stat(d, sleep_fn(d), tmp_path, start, 5, overwrite=False)
    assert len(d.calls) == 5
    d.calls.clear()
    fast.get_stat(d, sleep_fn(d), tmp_path, start, 5, overwrite=False)  # resumed run: nothing to do
    assert d.calls == []


def test_monitoring_resumes_from_marker(tmp_path):
    d = FakeDownload()
    mon = tmp_path / "Monitoring"
    (mon / "2022").mkdir(parents=True)
    dirf = lambda year: str(mon / str(year))
    start = datetime.date(2022, 3, 1)
    fast.get_monitoring(d, dirf, start, 4)
    assert len(d.calls) == 4
    assert len(json.loads((mon / ".downloaded_days.json").read_text())) == 4
    d.calls.clear()
    fast.get_monitoring(d, dirf, start, 6)
    assert d.calls == [start + datetime.timedelta(days=4), start + datetime.timedelta(days=5)]


def test_failed_day_is_retried_and_not_marked_done(tmp_path):
    d = FakeDownload()
    mon = tmp_path / "Monitoring"
    (mon / "2022").mkdir(parents=True)

    def boom(day):
        raise RuntimeError("429 Too Many Requests")
    d._Download__get_monitoring_day = boom
    fast.get_monitoring(d, lambda y: str(mon / str(y)), datetime.date(2022, 3, 1), 1)
    assert json.loads((mon / ".downloaded_days.json").read_text()) == []


def test_pace_backs_off_and_recovers():
    p = fast.Pace(0.25)
    p.failed()
    assert p.current == 1.0
    for _ in range(10):
        p.failed()
    assert p.current == fast.MAX_PAUSE_S
    for _ in range(50):
        p.ok()
    assert p.current == 0.25


def test_install_patches_garmindb_and_skips_hydration(caplog):
    fast.install()
    assert dl.Download._Download__get_stat is fast.get_stat
    with caplog.at_level("INFO"):
        dl.Download.get_hydration(object(), None, datetime.date(2022, 1, 1), 10, False)
    assert "Getting hydration: skipped" in caplog.text  # still logged, so the UI step list stays correct


def test_ranges_ending_yesterday_include_today(tmp_path):
    """Last night's sleep/HRV is filed under today's date — it must be fetched today, not tomorrow."""
    d = FakeDownload()
    today = datetime.date.today()
    start = today - datetime.timedelta(days=2)
    fast.get_stat(d, sleep_fn(d), tmp_path, start, 2, overwrite=False)  # GarminDB: start .. yesterday
    assert d.calls[-1] == today
    assert fast._through_today(datetime.date(2022, 1, 1), 5) == 5       # historic ranges unchanged


def test_unzip_writes_only_new_or_changed_files(tmp_path):
    import os
    import zipfile

    temp, out = tmp_path / "temp", tmp_path / "out"
    temp.mkdir()
    out.mkdir()
    for name, data in (("same.fit", b"same"), ("changed.fit", b"old")):
        (out / name).write_bytes(data)
        os.utime(out / name, (1_000_000, 1_000_000))
    with zipfile.ZipFile(temp / "day.zip", "w") as z:
        z.writestr("same.fit", b"same")
        z.writestr("changed.fit", b"new")
        z.writestr("new.fit", b"fresh")
        z.writestr("../escape.fit", b"no")
    fast.unzip_changed(type("D", (), {"temp_dir": str(temp)})(), str(out))

    assert (out / "same.fit").stat().st_mtime == 1_000_000      # identical → untouched → not re-imported
    assert (out / "changed.fit").read_bytes() == b"new" and (out / "changed.fit").stat().st_mtime > 1_000_000
    assert (out / "new.fit").read_bytes() == b"fresh"
    assert not (tmp_path / "escape.fit").exists() and not list(out.glob("*.part"))
