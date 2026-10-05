"""The training buddy: a little animal on the wall whose mood follows your data.

Each person picks an animal (Accounts → Training buddy). The mood is derived from what the wall
already knows — Garmin readiness, last night's sleep, today's workout and verdict, recent training —
in this order: overjoyed → hungry → sleepy → happy → content. At night the wall shows it asleep.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from . import db

ANIMALS = ("mouse", "cat", "bunny", "fox", "bear", "penguin", "frog", "hedgehog")
FOOD = {"mouse": "cheese", "cat": "fish", "bunny": "carrots", "fox": "berries", "bear": "honey",
        "penguin": "fish", "frog": "flies", "hedgehog": "apples"}
DEFAULT = "mouse"
HUNGRY_DAYS = 3                # no workout today or the 2 days before → hungry
MIN_WORKOUT_S = 600
SLEEPY_SLEEP_SCORE = 60


def _key(user_id: str) -> str:
    return f"buddy.{user_id}.animal"


def get_animal(conn: sqlite3.Connection, user_id: str) -> str:
    v = db.get_state(conn, _key(user_id), DEFAULT)
    return v if v in ANIMALS else DEFAULT


def set_animal(conn: sqlite3.Connection, user_id: str, animal: str) -> None:
    if animal not in ANIMALS:
        raise ValueError(f"unknown animal {animal!r}")
    db.set_state(conn, _key(user_id), animal)


def mood(*, readiness: dict | None, health_latest: dict | None, form: float | None,
         today_workout: dict | None, last_workout: dict | None, sessions: list[dict], today: date) -> str:
    done = (today_workout or {}).get("done") or {}
    lw = last_workout or {}
    new_best = str(lw.get("start_time", ""))[:10] == today.isoformat() and \
        any(i.get("tone") == "best" for i in lw.get("improvements") or [])
    if done.get("verdict") == "better" or new_best:
        return "overjoyed"
    since = (today - timedelta(days=HUNGRY_DAYS - 1)).isoformat()
    if not any(s["start_time"][:10] >= since and (s.get("duration_s") or 0) >= MIN_WORKOUT_S for s in sessions):
        return "hungry"
    level = (readiness or {}).get("level")
    sleep = (health_latest or {}).get("sleep_score")
    if level in ("LOW", "POOR") or (isinstance(sleep, (int, float)) and sleep < SLEEPY_SLEEP_SCORE):
        return "sleepy"
    if level in ("HIGH", "PRIME") or (level is None and form is not None and form > 5):
        return "happy"
    return "content"


def line(m: str, animal: str, today_workout: dict | None, streak: dict | None) -> str:
    food = FOOD.get(animal, "snacks")
    w = today_workout or {}
    if m == "overjoyed":
        return f"{food.capitalize()} party! That was amazing."
    if m == "hungry":
        return "My bowl is empty… one more workout?"
    if m == "sleepy":
        return "Yawn… an easy one today?"
    if w and not w.get("done"):
        return f"{w.get('title') or 'Workout'} today! Bring me back some {food}?"
    if w.get("done"):
        return f"Full belly, happy {animal}. Rest well!"
    if (streak or {}).get("needed"):
        n = streak["needed"]
        return f"{n} more workout{'s' if n > 1 else ''} keep{'s' if n == 1 else ''} our streak alive."
    return "Steady days add up." if m == "content" else "Let's move today!"


def block(conn: sqlite3.Connection, user_id: str, *, readiness, health_latest, form, today_workout, last_workout,
          streak, sessions: list[dict], today: date | None = None) -> dict:
    today = today or datetime.now().date()
    animal = get_animal(conn, user_id)
    m = mood(readiness=readiness, health_latest=health_latest, form=form, today_workout=today_workout,
             last_workout=last_workout, sessions=sessions, today=today)
    return {"animal": animal, "food": FOOD[animal], "mood": m, "line": line(m, animal, today_workout, streak)}
