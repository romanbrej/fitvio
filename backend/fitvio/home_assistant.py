"""Home Assistant: what Fitvio shares over MQTT, and with whom.

Each person opts in (Accounts or the phone's Me screen → Home Assistant); nobody is shared by default.
A shared person shows up in Home Assistant as one device, "Fitvio <name>", through MQTT discovery, with
sensors built from the same numbers the wall shows (wall.ambient), a "Sync now" button and three event
entities: a new workout (its verdict is the event type), a failed sync and an expired Garmin login.

This module only builds topics and payloads; mqtt_bridge.py talks to the broker.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from . import db
from .config import MqttConfig, UserConfig

ORIGIN = {"name": "Fitvio", "url": "https://github.com/romanbrej/fitvio"}
VERDICTS = ("better", "in_line", "worse", "not_comparable", "load_only")
VERDICT_LABEL = {"better": "Better", "in_line": "In line", "worse": "Worse", "not_comparable": "Not comparable",
                 "load_only": "Load only"}

# key: (name, unit, device_class, icon). The value is `value_json.<key>` of the person's state topic;
# keys in ATTRIBUTES also get `value_json.attrs.<key>` as entity attributes.
SENSORS: dict[str, tuple[str, str | None, str | None, str]] = {
    "training_readiness": ("Training readiness", None, None, "mdi:gauge"),
    "hrv": ("HRV", "ms", None, "mdi:heart-pulse"),
    "resting_hr": ("Resting heart rate", "bpm", None, "mdi:heart"),
    "sleep_score": ("Sleep score", None, None, "mdi:sleep"),
    "sleep_duration": ("Sleep duration", "min", "duration", "mdi:bed-clock"),
    "body_battery": ("Body Battery", "%", None, "mdi:battery-heart-variant"),
    "vo2max": ("VO2max", "ml/kg/min", None, "mdi:lungs"),
    "fitness": ("Fitness", None, None, "mdi:chart-line"),
    "fatigue": ("Fatigue", None, None, "mdi:chart-line-variant"),
    "form": ("Form", None, None, "mdi:scale-balance"),
    "week_load": ("Week load", None, None, "mdi:weight-lifter"),
    "week_streak": ("Week streak", "weeks", None, "mdi:fire"),
    "todays_workout": ("Today's workout", None, None, "mdi:calendar-check"),
    "last_workout": ("Last workout", None, None, "mdi:run"),
    "last_sync": ("Last sync", None, "timestamp", "mdi:cloud-sync"),
    "sync_status": ("Sync status", None, None, "mdi:cloud-check"),
}
TEXT = {"todays_workout", "last_workout", "last_sync", "sync_status"}  # no long-term statistics for these
ATTRIBUTES = {"training_readiness", "hrv", "resting_hr", "week_load", "week_streak", "todays_workout", "last_workout"}
# key: (name, event types, icon)
EVENTS: dict[str, tuple[str, list[str], str]] = {
    "new_workout": ("New workout", list(VERDICTS), "mdi:trophy"),
    "sync_failed": ("Sync failed", ["sync_failed"], "mdi:cloud-alert"),
    "login_expired": ("Garmin login expired", ["login_expired"], "mdi:account-key"),
}


def is_shared(conn: sqlite3.Connection, user_id: str) -> bool:
    return db.get_state(conn, f"ha.{user_id}.shared") == "1"


def set_shared(conn: sqlite3.Connection, user_id: str, shared: bool) -> None:
    db.set_state(conn, f"ha.{user_id}.shared", "1" if shared else "0")


def slug(user_id: str) -> str:
    """The person's id as Home Assistant entity ids and MQTT topics accept it."""
    return re.sub(r"[^a-z0-9_]", "_", user_id.lower())


def availability_topic(m: MqttConfig) -> str:
    return f"{m.topic_prefix}/status"


def state_topic(m: MqttConfig, user_id: str) -> str:
    return f"{m.topic_prefix}/{slug(user_id)}/state"


def event_topic(m: MqttConfig, user_id: str, event: str) -> str:
    return f"{m.topic_prefix}/{slug(user_id)}/event/{event}"


def sync_topic(m: MqttConfig, user_id: str) -> str:
    return f"{m.topic_prefix}/{slug(user_id)}/sync"


def discovery_topic(m: MqttConfig, user_id: str) -> str:
    return f"{m.discovery_prefix}/device/fitvio_{slug(user_id)}/config"


def discovery(m: MqttConfig, user: UserConfig) -> dict:
    """One device per person with all its entities (Home Assistant's device discovery)."""
    s = slug(user.id)
    cmps: dict[str, dict] = {}
    for key, (name, unit, device_class, icon) in SENSORS.items():
        c = {"p": "sensor", "name": name, "unique_id": f"fitvio_{s}_{key}", "default_entity_id": f"sensor.fitvio_{s}_{key}",
             "state_topic": state_topic(m, user.id), "value_template": f"{{{{ value_json.{key} }}}}", "icon": icon}
        if unit:
            c["unit_of_measurement"] = unit
        if device_class:
            c["device_class"] = device_class
        if key not in TEXT:
            c["state_class"] = "measurement"
        if key in ATTRIBUTES:
            c["json_attributes_topic"] = state_topic(m, user.id)
            c["json_attributes_template"] = f"{{{{ value_json.attrs.{key} | tojson }}}}"
        cmps[key] = c
    cmps["sync_now"] = {"p": "button", "name": "Sync now", "unique_id": f"fitvio_{s}_sync_now",
                        "default_entity_id": f"button.fitvio_{s}_sync_now", "command_topic": sync_topic(m, user.id),
                        "payload_press": "PRESS", "icon": "mdi:sync"}
    for key, (name, types, icon) in EVENTS.items():
        cmps[key] = {"p": "event", "name": name, "unique_id": f"fitvio_{s}_{key}",
                     "default_entity_id": f"event.fitvio_{s}_{key}", "state_topic": event_topic(m, user.id, key),
                     "event_types": types, "icon": icon}
    return {"dev": {"ids": [f"fitvio_{s}"], "name": f"Fitvio {user.display_name}", "mf": "Fitvio"},
            "o": ORIGIN, "availability_topic": availability_topic(m), "cmps": cmps}


def _local_iso(value: str | None) -> str | None:
    """Fitvio stores local times without a zone; Home Assistant's timestamps need one."""
    return datetime.fromisoformat(value).astimezone().isoformat() if value else None


def state(amb: dict) -> dict:
    """The sensor values of one person, from their wall data (wall.ambient)."""
    health, base = amb.get("health_latest") or {}, amb.get("health_baseline") or {}
    readiness, form = amb.get("readiness") or {}, amb.get("form") or {}
    sweet, streak = amb.get("sweet_spot") or {}, amb.get("streak") or {}
    today = amb.get("today_workout")
    last = next(iter(amb.get("recent") or []), None)
    sync = amb.get("sync") or {}
    sleep = health.get("sleep_total_min")
    load, low, high = sweet.get("load"), sweet.get("low"), sweet.get("high")
    return {
        "training_readiness": readiness.get("score"),
        "hrv": health.get("hrv_last_night"),
        "resting_hr": health.get("rhr"),
        "sleep_score": health.get("sleep_score"),
        "sleep_duration": round(sleep) if sleep is not None else None,
        "body_battery": health.get("bb_max"),
        "vo2max": next((v["value"] for v in reversed(amb.get("vo2max") or [])), None),
        "fitness": form.get("fitness"),
        "fatigue": form.get("fatigue"),
        "form": form.get("form"),
        "week_load": load,
        "week_streak": streak.get("weeks"),
        "todays_workout": (today.get("title") or "Workout") if today else "Rest",
        "last_workout": VERDICT_LABEL.get(last.get("verdict"), "No verdict") if last else None,
        "last_sync": _local_iso(sync.get("last_success")),
        "sync_status": ("login_expired" if sync.get("login_expired") else "failed" if sync.get("last_error")
                        else "stale" if sync.get("stale") else "ok"),
        "attrs": {
            "training_readiness": {"level": readiness.get("level")},
            "hrv": {"status": health.get("hrv_status"), "normal_low": health.get("hrv_baseline_low"),
                    "normal_high": health.get("hrv_baseline_high"), "weekly_average": health.get("hrv_weekly")},
            "resting_hr": {"normal": base.get("rhr")},
            "week_load": {"sweet_spot_low": low, "sweet_spot_high": high,
                          "status": None if None in (load, low, high)
                          else "below" if load < low else "above" if load > high else "in"},
            "week_streak": {"this_week": streak.get("this_week"), "needed": streak.get("needed")},
            "todays_workout": {"sport": today.get("sport"), "description": today.get("description"),
                               "done": bool(today.get("done"))} if today else {},
            "last_workout": {"verdict": last.get("verdict"), "sport": last.get("sport"), "name": last.get("name"),
                             "headline": last.get("headline"), "time": _local_iso(last.get("start_time"))}
                            if last else {},
        },
    }


def new_workout_event(row: dict) -> dict:
    """A new workout's event: the verdict is the event type, the rest become attributes."""
    return {"event_type": row["verdict"], "verdict": VERDICT_LABEL.get(row["verdict"], row["verdict"]),
            "sport": row["sport"], "name": row["name"], "headline": row["headline"],
            "time": _local_iso(row["start_time"]), "session_id": row["id"]}
