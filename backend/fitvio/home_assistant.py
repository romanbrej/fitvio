"""Home Assistant: what Fitvio shares over MQTT, and with whom.

Each person opts in (Accounts or the phone's Me screen → Home Assistant); nobody is shared by default.
A shared person shows up in Home Assistant as one device, "Fitvio <name>", through MQTT discovery, with
sensors built from the same numbers the wall shows (wall.ambient), a "Sync now" button and three event
entities: a new workout (its verdict is the event type), a failed sync and an expired Garmin login.

This module only builds topics and payloads; mqtt_bridge.py talks to the broker.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime

from . import db
from .config import MqttConfig, UserConfig

ORIGIN = {"name": "Fitvio", "url": "https://github.com/romanbrej/fitvio"}
VERDICTS = ("better", "in_line", "worse", "not_comparable", "load_only")
VERDICT_LABEL = {"better": "Better", "in_line": "In line", "worse": "Worse", "not_comparable": "Not comparable",
                 "load_only": "Load only"}
FORM_LABEL = {"very_fresh": "Very fresh", "fresh": "Fresh", "neutral": "Neutral", "productive": "Productive",
              "overreaching": "Overreaching"}
# per sport: its sensor's key and name; a person gets one only for the sports they have verdicts in
SPORTS = {"running": ("running", "Running", "mdi:run"), "cycling": ("cycling", "Cycling", "mdi:bike"),
          "swimming": ("swimming", "Swimming", "mdi:swim"), "strength": ("gym", "Gym", "mdi:dumbbell")}
# Where a sport is heading, like the wall's sport tiles (WallAmbient.tsx): a move inside the steady band
# is noise, and a sport without a session in STALE_DAYS has no direction.
STEADY = {"run_s_per_km": 4, "pct": 1.5, "gym_sessions": 2}
STALE_DAYS = 42

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
    "training_status": ("Training status", None, "enum", "mdi:run-fast"),
}
OPTIONS = {"training_status": list(FORM_LABEL.values())}  # enum sensors: the states they can have
TEXT = {"todays_workout", "last_workout", "last_sync", "sync_status", "training_status"}  # no long-term statistics
ATTRIBUTES = {"training_readiness", "hrv", "resting_hr", "week_load", "week_streak", "todays_workout", "last_workout"}
# key: (name, event types, icon)
EVENTS: dict[str, tuple[str, list[str], str]] = {
    "new_workout": ("New workout", list(VERDICTS), "mdi:trophy"),
    "sync_failed": ("Sync failed", ["sync_failed"], "mdi:cloud-alert"),
    "login_expired": ("Garmin login expired", ["login_expired"], "mdi:account-key"),
}


def announced_key(user_id: str) -> str:
    """The fresh workouts already announced to Home Assistant (mqtt_bridge.py), as a JSON list of ids."""
    return f"ha.{user_id}.announced"


def is_shared(conn: sqlite3.Connection, user_id: str) -> bool:
    return db.get_state(conn, f"ha.{user_id}.shared") == "1"


def set_shared(conn: sqlite3.Connection, user_id: str, shared: bool) -> None:
    db.set_state(conn, f"ha.{user_id}.shared", "1" if shared else "0")
    if not shared:  # sharing again starts afresh: nothing from meanwhile is announced as new
        db.set_state(conn, announced_key(user_id), "")


def slug(user_id: str) -> str:
    """The person's id as Home Assistant entity ids and MQTT topics accept it. Ids Fitvio makes already
    are; any other gets a short hash, so "anna.b" and "anna_b" don't end up as one device."""
    if re.fullmatch(r"[a-z0-9_]+", user_id):
        return user_id
    return re.sub(r"[^a-z0-9_]", "_", user_id.lower()) + "_" + hashlib.sha1(user_id.encode()).hexdigest()[:6]


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


def discovery(m: MqttConfig, user: UserConfig, sports: list[str] = ()) -> dict:
    """One device per person with all its entities (Home Assistant's device discovery). `sports`: the
    sport sensors' keys this person has (state()["sports"])."""
    s = slug(user.id)
    cmps: dict[str, dict] = {}
    sensors = {**SENSORS, **{key: (name, None, "enum", icon) for key, name, icon in SPORTS.values() if key in sports}}
    for key, (name, unit, device_class, icon) in sensors.items():
        c = {"p": "sensor", "name": name, "unique_id": f"fitvio_{s}_{key}", "default_entity_id": f"sensor.fitvio_{s}_{key}",
             "state_topic": state_topic(m, user.id), "value_template": f"{{{{ value_json.{key} }}}}", "icon": icon}
        if unit:
            c["unit_of_measurement"] = unit
        if device_class:
            c["device_class"] = device_class
        if device_class == "enum":
            c["options"] = OPTIONS.get(key, list(VERDICT_LABEL.values()))
        elif key not in TEXT:
            c["state_class"] = "measurement"
        if key in ATTRIBUTES or key in sports:
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


def _trend(sport: str, t: dict, days: int) -> tuple[float | None, str | None, float]:
    """(change, unit, steady band) of a sport over `days`, as the wall's sport tile works it out."""
    st, p = t.get("status") or {}, (t.get("periods") or {}).get(str(days))
    if sport == "running" and st.get("pace_s_per_km"):
        return (p["change"] if p else st.get("change_s_per_km")), "s/km", STEADY["run_s_per_km"]
    if sport == "cycling" and st.get("w_per_beat") is not None:
        return (p["change"] if p else st.get("w_per_beat_change_pct")), "% per heartbeat", STEADY["pct"]
    if sport == "strength" and st.get("sessions_6w") is not None:
        e1rm = p["change"] if p else st.get("e1rm_change_pct")
        if e1rm is not None:
            return e1rm, "% e1RM", STEADY["pct"]
        n, prev = (p["n"], p.get("n_prev") or 0) if p else (st["sessions_6w"], st.get("sessions_prev_6w") or 0)
        return n - prev, "sessions", STEADY["gym_sessions"]
    pct6 = t["pct_per_week"] * 6 if t.get("pct_per_week") is not None else None
    return (pct6 if pct6 is not None and abs(pct6) <= 30 else None), "%", STEADY["pct"]  # steeper: too few


def sport_states(amb: dict, now: datetime | None = None) -> tuple[dict, dict]:
    """Per sport the person has verdicts in: the newest verdict (state) and where it's heading (attributes)."""
    now = now or datetime.now()
    from .wall import DEFAULT_DAYS

    states, attrs = {}, {}
    for sport, t in (amb.get("trends") or {}).items():
        if sport not in SPORTS:
            continue
        key = SPORTS[sport][0]
        days = amb.get("trend_period") or DEFAULT_DAYS.get(sport, 42)
        change, unit, band = _trend(sport, t, days)
        stale = (now - datetime.fromisoformat(t["last_time"])).days > STALE_DAYS
        direction = (None if stale or change is None else "improving" if change >= band
                     else "declining" if change <= -band else "steady")
        states[key] = VERDICT_LABEL.get(t.get("last_verdict"))
        attrs[key] = {"trend": direction, "change": round(change, 1) if change is not None else None, "unit": unit,
                      "days": days if sport != "swimming" else 42, "verdict": t.get("last_verdict"),
                      "last_session": _local_iso(t.get("last_time"))}
    return states, attrs


def state(amb: dict) -> dict:
    """The sensor values of one person, from their wall data (wall.ambient)."""
    health, base = amb.get("health_latest") or {}, amb.get("health_baseline") or {}
    readiness, form = amb.get("readiness") or {}, amb.get("form") or {}
    sweet, streak = amb.get("sweet_spot") or {}, amb.get("streak") or {}
    today = amb.get("today_workout")
    # the newest workout with a verdict, like the new-workout event (an excluded one doesn't count)
    last = next((r for r in amb.get("recent") or [] if r.get("verdict") not in (None, "excluded")), None)
    sync = amb.get("sync") or {}
    sleep = health.get("sleep_total_min")
    load, low, high = sweet.get("load"), sweet.get("low"), sweet.get("high")
    sports, sport_attrs = sport_states(amb)
    return {
        **sports,
        "sports": sorted(sports),  # which sport sensors the device has (discovery)
        "training_status": FORM_LABEL.get(form.get("state")),
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
        "last_workout": VERDICT_LABEL.get(last["verdict"], last["verdict"]) if last else None,
        "last_sync": _local_iso(sync.get("last_success")),
        "sync_status": ("login_expired" if sync.get("login_expired") else "failed" if sync.get("last_error")
                        else "stale" if sync.get("stale") else "ok"),
        "attrs": {
            "training_readiness": {"level": readiness.get("level")},
            "hrv": {"status": health.get("hrv_status"), "normal_low": health.get("hrv_baseline_low"),
                    "normal_high": health.get("hrv_baseline_high"), "weekly_average": health.get("hrv_weekly")},
            "resting_hr": {"normal": base.get("rhr")},
            **sport_attrs,
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
