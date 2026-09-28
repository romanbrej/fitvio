"""Run GarminDB's own CLI with faster, resumable download loops.

GarminDB downloads one request per day per data type and then always sleeps 1 s — even for days
it already has. For the JSON types it also makes the request *before* checking whether the file
exists, and monitoring has no skip at all, so every interrupted first download starts over.

This wrapper patches only the download loops (nothing else) and then runs the unmodified
`garmindb_cli.py` with the same arguments:
  * days already on disk are skipped without a request and without a pause
    (the most recent `download_days_overlap` days are always refreshed, as GarminDB intends)
  * the pause between real requests is adaptive: HEALTHDASH_GARMIN_PAUSE (default 0.25 s),
    doubled on errors / rate limiting up to 8 s, and eased back down after successes
  * monitoring remembers finished days in `.downloaded_days.json`, so it resumes too
  * hydration is skipped (Health Wall doesn't use it; HEALTHDASH_HYDRATION=1 keeps it)

Usage (done by run_sync): python -m healthdash.sync.garmindb_fast <garmindb_cli args…>
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import runpy
import shutil
import sys
import tempfile
import time
from pathlib import Path

from tqdm import tqdm

import garmindb.download as dl

root_logger = logging.getLogger()

BASE_PAUSE_S = float(os.environ.get("HEALTHDASH_GARMIN_PAUSE", "0.25"))
MAX_PAUSE_S = 8.0
KEEP_HYDRATION = os.environ.get("HEALTHDASH_HYDRATION") == "1"

# day function name → where GarminDB saves that day (".json" is appended by save_json_to_file)
_CACHED = {
    "__get_summary_day": lambda d, day: Path(d(day.year)) / f"daily_summary_{day:%Y-%m-%d}.json",
    "__get_hydration_day": lambda d, day: Path(d(day.year)) / f"hydration_{day:%Y-%m-%d}.json",
    "__get_weight_day": lambda d, day: Path(d) / f"weight_{day:%Y-%m-%d}.json",
    "__get_sleep_day": lambda d, day: Path(d) / f"sleep_{day}.json",
    "__get_rhr_day": lambda d, day: Path(d) / f"rhr_{day:%Y-%m-%d}.json",
    "__get_hrv_day": lambda d, day: Path(d) / f"hrv_{day:%Y-%m-%d}.json",
}


class Pace:
    """Adaptive politeness delay between real requests to Garmin."""

    def __init__(self, base: float = BASE_PAUSE_S):
        self.base = base
        self.current = base

    def ok(self) -> None:
        self.current = max(self.base, self.current * 0.8)

    def failed(self) -> None:
        self.current = min(MAX_PAUSE_S, max(self.current * 2, 1.0))

    def wait(self) -> None:
        time.sleep(self.current)


def _needs_refresh(self, day: datetime.date) -> bool:
    return (datetime.date.today() - day).days <= self.download_days_overlap


def _fetch_with_retries(fn, pace: Pace, day) -> bool:
    for attempt in range(1, 6):
        try:
            fn()
            pace.ok()
            return True
        except Exception as e:  # network errors, 429 rate limiting, …
            pace.failed()
            if attempt == 5:
                root_logger.error("Failed to download %s after %d attempts: %s", day, attempt, e)
                return False
            root_logger.warning("Retrying %s after error on attempt %d/5: %s", day, attempt, e)
            time.sleep(attempt * 5)
    return False


def get_stat(self, stat_function, directory, date, days, overwrite):
    cached = _CACHED.get(stat_function.__name__)
    pace = Pace()
    for n in tqdm(range(0, days), unit="days"):
        day = date + datetime.timedelta(days=n)
        refresh = overwrite or _needs_refresh(self, day)
        if cached and not refresh and cached(directory, day).exists():
            continue  # already on disk: no request, no pause
        _fetch_with_retries(lambda: stat_function(directory, day, refresh), pace, day)
        pace.wait()


def get_monitoring(self, directory_func, date, days):
    root_logger.info("Getting monitoring: %s (%d)", date, days)
    marker = Path(directory_func(date.year)).parent / ".downloaded_days.json"
    try:
        done = set(json.loads(marker.read_text()))
    except (OSError, ValueError):
        done = set()
    pace = Pace()
    for n in tqdm(range(0, days), unit="days"):
        day = date + datetime.timedelta(days=n)
        if day.isoformat() in done and not _needs_refresh(self, day):
            continue

        def fetch():
            self.temp_dir = tempfile.mkdtemp()
            try:
                self._Download__get_monitoring_day(day)
                self._Download__unzip_files(directory_func(day.year))
            finally:
                shutil.rmtree(self.temp_dir, ignore_errors=True)

        if _fetch_with_retries(fetch, pace, day):
            done.add(day.isoformat())
            if len(done) % 25 == 0:
                marker.write_text(json.dumps(sorted(done)))
        pace.wait()
    marker.write_text(json.dumps(sorted(done)))


def get_hydration(self, directory_func, date, days, overwrite):
    if KEEP_HYDRATION:
        return _original_hydration(self, directory_func, date, days, overwrite)
    root_logger.info("Getting hydration: skipped, not used by Health Wall")


_original_hydration = dl.Download.get_hydration


def install() -> None:
    dl.Download._Download__get_stat = get_stat
    dl.Download.get_monitoring = get_monitoring
    dl.Download.get_hydration = get_hydration


def main() -> None:
    install()
    cli = Path(sys.executable).parent / "garmindb_cli.py"
    if not cli.exists():
        cli = Path(shutil.which("garmindb_cli.py") or "garmindb_cli.py")
    sys.argv = [str(cli), *sys.argv[1:]]
    runpy.run_path(str(cli), run_name="__main__")


if __name__ == "__main__":
    main()
