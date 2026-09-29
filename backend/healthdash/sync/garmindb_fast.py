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
  * activities are compared with what is saved: a summary or details file is only rewritten when
    Garmin's version differs (renamed, RPE/feel added, …), recent activities are always checked

Differential import (HEALTHDASH_SYNC_SINCE = start of the last successful sync, set by run_sync):
  * `--latest` imports only files written since then, instead of GarminDB's "last 24 hours".
    Files are only written when new or changed, so this is a real comparison.
  * the analyze step only recalculates the affected year(s) instead of all of them

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

from healthdash.sync import garmin_extras

root_logger = logging.getLogger()

BASE_PAUSE_S = float(os.environ.get("HEALTHDASH_GARMIN_PAUSE", "0.25"))
MAX_PAUSE_S = 8.0
KEEP_HYDRATION = os.environ.get("HEALTHDASH_HYDRATION") == "1"


def _sync_since() -> datetime.datetime | None:
    raw = os.environ.get("HEALTHDASH_SYNC_SINCE")
    try:
        return datetime.datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


SYNC_SINCE = _sync_since()

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


def _through_today(date, days: int) -> int:
    """GarminDB's ranges stop at yesterday (range(0, today - start)). Garmin files last night's
    sleep, HRV and resting HR under *today's* date, so include today when the range ends yesterday."""
    if date + datetime.timedelta(days=days) == datetime.date.today():
        return days + 1
    return days


def get_stat(self, stat_function, directory, date, days, overwrite):
    cached = _CACHED.get(stat_function.__name__)
    pace = Pace()
    for n in tqdm(range(0, _through_today(date, days)), unit="days"):
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
    for n in tqdm(range(0, _through_today(date, days)), unit="days"):
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


# --- activities: compare with what is saved ------------------------------------

def _write_if_changed(base: str, data) -> bool:
    """Save GarminDB-style `<base>.json` only when the content differs. Returns True if written.
    Unchanged files keep their mtime, which is what the differential import keys on."""
    path = Path(base + ".json")
    new = json.loads(json.dumps(data, default=str))
    try:
        if json.loads(path.read_text()) == new:
            return False
    except (OSError, ValueError):
        pass
    path.write_text(json.dumps(new))
    return True


def _is_recent(self, activity: dict) -> bool:
    start = str(activity.get("startTimeLocal") or activity.get("startTimeGMT") or "")[:10]
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(start)).days <= self.download_days_overlap
    except ValueError:
        return False


def get_activities(self, directory, count, overwrite=False):
    """GarminDB's activity download, plus change detection for activities it already has."""
    self.temp_dir = tempfile.mkdtemp()
    root_logger.info("Getting activities: '%s' (%d) temp %s", directory, count, self.temp_dir)
    activities = self._Download__get_activity_summaries(0, count) or []
    extras = garmin_extras.extras_dir(Path(directory).parent.parent)  # <HealthData>/Extras
    pace = Pace()
    new = updated = 0
    for activity in tqdm(activities, unit="activities"):
        aid = str(activity.get("activityId", ""))
        if not aid.isdigit():  # used in file names: never trust it to be a plain number
            root_logger.warning("get_activities: skipping activity with unexpected id %r", aid[:40])
            continue
        base = f"{directory}/activity_{aid}"
        is_new = not os.path.isfile(base + ".json")
        summary_changed = _write_if_changed(base, activity)  # the list already holds the current summary
        # Garmin's weather + heat acclimation for this activity (what Garmin Connect shows), once
        day = str(activity.get("startTimeLocal") or "")[:10]
        if day and any(garmin_extras.missing(extras, aid, day)):
            _fetch_with_retries(lambda: garmin_extras.fetch_extras(self.garmin.connectapi, extras, aid, day), pace, aid)
            pace.wait()
        if not (is_new or overwrite or summary_changed or _is_recent(self, activity)):
            continue  # unchanged and old: no more requests

        def fetch(aid=aid, is_new=is_new):
            details = self.garmin.connectapi(f"{self.garmin_connect_activity_service_url}/{aid}")
            details_changed = _write_if_changed(f"{directory}/activity_details_{aid}", details)
            if is_new or overwrite or not os.path.isfile(f"{directory}/{aid}.fit"):
                self._Download__save_activity_file(aid)
            return details_changed

        result = {}
        ok = _fetch_with_retries(lambda: result.__setitem__("changed", fetch()), pace, aid)
        if is_new:
            new += 1
        elif ok and (summary_changed or result.get("changed")):
            updated += 1
            root_logger.info("get_activities: %s changed in Garmin Connect", aid)
        pace.wait()
    self._Download__unzip_files(directory)
    shutil.rmtree(self.temp_dir, ignore_errors=True)
    root_logger.info("Activities: %d new, %d updated", new, updated)
    try:  # precise VO2max history (44.1 instead of GarminDB's 44) — one request
        root_logger.info("VO2max: %d days with precise values", garmin_extras.update_vo2max(self.garmin.connectapi, extras))
    except Exception as e:  # nice-to-have, never fail the sync because of it
        root_logger.warning("VO2max update failed: %s", e)


# --- differential import + analyze ---------------------------------------------

def _patch_differential_import(since: datetime.datetime) -> None:
    from idbutils.file_processor import FileProcessor

    import garmindb.analyze as an

    original_dir_to_files = FileProcessor.dir_to_files.__func__
    since_ts = since.timestamp()

    def dir_to_files(cls, input_dir, file_regex, latest=False, recursive=False):
        files = original_dir_to_files(cls, input_dir, file_regex, False, recursive)
        if not latest:
            return files
        changed = [f for f in files if os.stat(f).st_mtime > since_ts]
        root_logger.info("Import: %d of %d files in %s changed since %s", len(changed), len(files), input_dir, since)
        return changed

    FileProcessor.dir_to_files = classmethod(dir_to_files)

    def summary(self):
        years = sorted(set(an.Monitoring.get_years(self.garmin_mon_db) + an.Activities.get_years(self.garmin_act_db)
                           + an.SleepEvents.get_years(self.garmin_db)))
        affected = [y for y in years if y >= since.year]
        root_logger.info("Analyze: only %s (of %s), data before %s is unchanged", affected, years, since.date())
        for year in affected:
            self._Analyze__calculate_year(year)

    an.Analyze.summary = summary


def install() -> None:
    dl.Download._Download__get_stat = get_stat
    dl.Download.get_monitoring = get_monitoring
    dl.Download.get_hydration = get_hydration
    dl.Download.get_activities = get_activities
    if SYNC_SINCE is not None:
        _patch_differential_import(SYNC_SINCE)


def main() -> None:
    install()
    cli = Path(sys.executable).parent / "garmindb_cli.py"
    if not cli.exists():
        cli = Path(shutil.which("garmindb_cli.py") or "garmindb_cli.py")
    sys.argv = [str(cli), *sys.argv[1:]]
    runpy.run_path(str(cli), run_name="__main__")


if __name__ == "__main__":
    main()
