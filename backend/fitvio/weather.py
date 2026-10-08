"""Which weather a session uses: Open-Meteo's hours over the session when they are there (and the
person hasn't switched it off), else what the platform gave (Garmin's weather box, Intervals.icu's
temperature), else none."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from . import db
from .activity import ParsedActivity
from .sync import open_meteo

log = logging.getLogger(__name__)

SETTING = "open_meteo:{user_id}"  # "off" = the platform's weather only; anything else = on (the default)


def enabled(conn: sqlite3.Connection, user_id: str) -> bool:
    return db.get_state(conn, SETTING.format(user_id=user_id)) != "off"


def set_enabled(conn: sqlite3.Connection, user_id: str, on: bool) -> None:
    db.set_state(conn, SETTING.format(user_id=user_id), "on" if on else "off")


def wants_lookup(act: ParsedActivity) -> bool:
    """Outdoors with a position: the only sessions weather can mean anything for."""
    return not act.indoor and bool(act.track) and act.sport != "strength"


def apply(act: ParsedActivity, directory: Path | None, use_open_meteo: bool) -> None:
    """Pick the session's weather in place; avg_temp_c follows it."""
    if not use_open_meteo or directory is None or not wants_lookup(act):
        return
    w = open_meteo.read_session(directory, act.track, act.start_time, act.duration_s)
    if w is None:
        return
    platform = act.weather or {}
    if platform.get("desc"):
        w["desc"] = platform["desc"]  # Garmin's "Cloudy" / "Rain": a label, not a number
    act.weather = w
    act.avg_temp_c = w["temp_c"]


def needs(directory: Path | None, acts: list[ParsedActivity]) -> dict:
    """{cell: {local day}} still missing for these sessions."""
    out: dict = {}
    if directory is None:
        return out
    for act in acts:
        if wants_lookup(act):
            merge_needs(out, open_meteo.missing(directory, act.track, act.start_time, act.duration_s))
    return out


def merge_needs(into: dict, more: dict) -> None:
    for cell, days in more.items():
        into.setdefault(cell, set()).update(days)


def label(w: dict | None) -> str | None:
    """Where a session's weather came from, for people: "Open-Meteo", "Garmin station Town", "Intervals.icu"."""
    if not w:
        return None
    if w.get("source") == "Garmin" or (w.get("station") and not w.get("source")):
        return f"Garmin station {w['station']}" if w.get("station") else "Garmin"
    return w.get("source")
