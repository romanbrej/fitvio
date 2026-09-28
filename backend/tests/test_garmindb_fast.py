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
