"""Run GarminDB's own CLI with faster, resumable download loops.

GarminDB downloads one request per day per data type and then always sleeps 1 s — even for days
it already has. For the JSON types it also makes the request *before* checking whether the file
exists, and monitoring has no skip at all, so every interrupted first download starts over.

This wrapper patches only the download loops (nothing else) and then runs the unmodified
`garmindb_cli.py` with the same arguments:
  * days already on disk are skipped without a request and without a pause
    (the most recent `download_days_overlap` days are always refreshed, as GarminDB intends)
  * the pause between real requests is adaptive: FITVIO_GARMIN_PAUSE (default 0.25 s),
    doubled on errors / rate limiting up to 8 s, and eased back down after successes
  * monitoring remembers finished days in `.downloaded_days.json`, so it resumes too
  * hydration is skipped (Fitvio doesn't use it; FITVIO_HYDRATION=1 keeps it)
  * garmindb.log lines get a timestamp, so run_sync can log how long each step took
  * activities are compared with what is saved: a summary or details file is only rewritten when
    Garmin's version differs (renamed, RPE/feel added, …), recent activities are always checked

Unzipping (monitoring days, activity files) only writes files that are new or differ from what is on
disk, so re-downloaded but identical files keep their mtime and are not imported again.

Differential import (FITVIO_SYNC_SINCE = start of the last successful sync, set by run_sync):
  * `--latest` imports only files written since then, instead of GarminDB's "last 24 hours".
    Files are only written when new or changed, so this is a real comparison.
  * the analyze step only fills in missing sleep rows for the changed days. GarminDB's summary databases
    (day/week/month/year stats) are not read by Fitvio, so they are only rebuilt by a full sync.

Usage (done by run_sync): python -m fitvio.sync.garmindb_fast <garmindb_cli args…>
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
import zipfile
from pathlib import Path

from tqdm import tqdm

import garmindb.download as dl

from fitvio.config import env
from fitvio.sync import garmin_extras

root_logger = logging.getLogger()

BASE_PAUSE_S = float(env("GARMIN_PAUSE", "0.25"))
MAX_PAUSE_S = 8.0
KEEP_HYDRATION = env("HYDRATION") == "1"


def _sync_since() -> datetime.datetime | None:
    raw = env("SYNC_SINCE")
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
    root_logger.info("Getting hydration: skipped, not used by Fitvio")


_original_hydration = dl.Download.get_hydration


MAX_UNZIPPED = 64 * 2**20  # one file in a Garmin download (a day of monitoring is well under 1 MB)


def unzip_changed(self, outdir):
    """GarminDB's __unzip_files, but a file is only (re)written when it is new or its bytes differ."""
    out = Path(outdir)
    written = same = 0
    for name in os.listdir(self.temp_dir):
        if not name.endswith(".zip"):
            continue
        try:
            with zipfile.ZipFile(Path(self.temp_dir) / name) as zf:
                for member in zf.infolist():
                    rel = Path(member.filename)
                    if member.is_dir() or rel.is_absolute() or ".." in rel.parts:
                        continue
                    if member.file_size > MAX_UNZIPPED:  # a tiny zip can claim gigabytes
                        root_logger.error("unzip_files: skipping %s (%d bytes)", member.filename, member.file_size)
                        continue
                    data = zf.read(member)
                    target = out / rel
                    try:
                        if target.read_bytes() == data:
                            same += 1
                            continue
                    except OSError:
                        pass
                    target.parent.mkdir(parents=True, exist_ok=True)
                    tmp = target.with_name(target.name + ".part")
                    tmp.write_bytes(data)
                    os.replace(tmp, target)
                    written += 1
        except (zipfile.BadZipFile, OSError) as e:
            root_logger.error("Failed to unzip %s to %s: %s", name, outdir, e)
    root_logger.info("unzip_files: %d written, %d unchanged → %s", written, same, outdir)


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


def _has_fit(directory: str, aid: str) -> bool:
    """GarminDB saves an activity's file as `<id>_ACTIVITY.fit` (multisport legs get their own suffix)."""
    return any(Path(directory).glob(f"{aid}_*.fit"))


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

        def fetch(aid=aid, is_new=is_new, summary_changed=summary_changed):
            details = self.garmin.connectapi(f"{self.garmin_connect_activity_service_url}/{aid}")
            details_changed = _write_if_changed(f"{directory}/activity_details_{aid}", details)
            # the file only changes with the activity (e.g. trimmed in Connect): unchanged ones are never fetched again
            if is_new or overwrite or summary_changed or details_changed or not _has_fit(directory, aid):
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
        # Fitvio reads garmin.db and garmin_activities.db only, never the summary databases. The one
        # thing analyze adds there is a sleep row built from sleep events when the sleep JSON had none.
        days = [since.date() + datetime.timedelta(days=n) for n in range(max(1, (datetime.date.today() - since.date()).days + 1))]
        root_logger.info("Analyze: sleep rows for %s..%s only (summary databases are rebuilt by a full sync)",
                         days[0], days[-1])
        with self.garmin_db.managed_session() as session:
            for day in days:
                self._Analyze__populate_sleep_for_day(day, session)

    an.Analyze.summary = summary


LOG_FORMAT = "%(asctime)s %(levelname)s:%(name)s:%(message)s"


def _timestamped_log() -> None:
    """GarminDB's log has no times; add them so run_sync can report how long each step took."""
    original = logging.basicConfig

    def basic_config(**kw):
        kw.setdefault("format", LOG_FORMAT)
        original(**kw)

    logging.basicConfig = basic_config


def install() -> None:
    _timestamped_log()
    dl.Download._Download__get_stat = get_stat
    dl.Download.get_monitoring = get_monitoring
    dl.Download.get_hydration = get_hydration
    dl.Download.get_activities = get_activities
    dl.Download._Download__unzip_files = unzip_changed
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
