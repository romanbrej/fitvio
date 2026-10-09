"""Synthetic but physiologically plausible data, so the dashboard can be developed and
demoed without a Garmin login. Runs the real feature/verdict pipeline on it."""
from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import date, datetime, timedelta

from . import db, pipeline, profile
from .activity import ExerciseSet, Lap, ParsedActivity, Record, SwimLength
from .config import AppConfig, UserConfig
from .sync import open_meteo

STEP = 2.0  # seconds between synthetic records


def _run(rng: random.Random, uid: str, start: datetime, fitness: float, kind: str, user: UserConfig,
         temp: float, showcase: bool = False) -> ParsedActivity:
    # fitness ~ aerobic efficiency in m/min per beat (grows over the season)
    minutes = {"easy": rng.uniform(35, 55), "long": rng.uniform(80, 110), "tempo": rng.uniform(40, 55),
               "intervals": rng.uniform(45, 60)}[kind]
    hilly = rng.random() < 0.3
    recs, laps = [], []
    dist = 0.0
    n = int(minutes * 60 / STEP)
    drift = rng.uniform(0.02, 0.06) if kind != "long" else rng.uniform(0.04, 0.09)
    heat = 1 + 0.004 * max(0, temp - 15)
    if showcase:  # the run the demo wall opens on: a good day (flat, cool, steady), so the first verdict is "better"
        hilly, drift, heat, fitness = False, 0.015, 1.0, fitness * 1.06
    lap_start, lap_dist = 0.0, 0.0
    for i in range(n):
        t = i * STEP
        frac = i / n
        if kind == "easy" or kind == "long":
            target_hr = user.rest_hr + 0.62 * (user.max_hr - user.rest_hr)
        elif kind == "tempo":
            target_hr = user.rest_hr + (0.62 if frac < 0.2 or frac > 0.85 else 0.82) * (user.max_hr - user.rest_hr)
        else:
            on = 0.2 < frac < 0.85 and int((t - 0.2 * n * STEP) // 180) % 2 == 0
            target_hr = user.rest_hr + (0.9 if on else 0.6) * (user.max_hr - user.rest_hr)
        warm = min(1.0, t / 240)
        hr = user.rest_hr + (target_hr - user.rest_hr) * (0.7 + 0.3 * warm)
        hr *= 1 + drift * frac
        hr *= heat
        hr += rng.gauss(0, 1.5)
        speed = (target_hr * fitness / 60) * (0.94 + 0.06 * warm) * (1 + rng.gauss(0, 0.02))
        alt = 200 + (40 * math.sin(dist / 900) if hilly else 3 * math.sin(dist / 500))
        grade = (40 / 900 * math.cos(dist / 900)) if hilly else 0
        speed /= (1 + 3 * max(-0.1, grade))
        dist += speed * STEP
        recs.append(Record(t=t, hr=round(hr), speed=speed, distance=dist, altitude=alt, cadence=170 + rng.gauss(0, 3),
                           temperature=temp + 4))
        if dist - lap_dist >= 1000:
            laps.append(Lap(start_s=lap_start, duration_s=t - lap_start, distance_m=dist - lap_dist,
                            avg_speed=(dist - lap_dist) / max(1, t - lap_start)))
            lap_start, lap_dist = t, dist
    if kind == "intervals":  # structured laps: 3 min on / 3 min off
        laps = []
        t0 = 0.2 * n * STEP
        laps.append(Lap(0, t0, None, None, recs[int(t0 / STEP) - 1].distance / t0))
        k = 0
        while t0 + 180 < 0.85 * n * STEP:
            seg = [r for r in recs if t0 <= r.t < t0 + 180]
            laps.append(Lap(t0, 180, seg[-1].distance - seg[0].distance, None, (seg[-1].distance - seg[0].distance) / 180))
            t0 += 180
            k += 1
    hrs = [r.hr for r in recs]
    return ParsedActivity(
        activity_id=f"demo-{uid}-{start:%Y%m%d%H%M}", start_time=start, sport="running", raw_sport="running",
        sub_sport="generic", name={"easy": "Easy Run", "long": "Long Run", "tempo": "Tempo Run",
                                   "intervals": "Intervals 3' on/off"}[kind],
        duration_s=n * STEP, distance_m=dist, avg_hr=sum(hrs) / len(hrs), max_hr=max(hrs),
        ascent_m=320 * (minutes / 60) if hilly else 20, avg_temp_c=round(temp, 1), records=recs, laps=laps,
        weather=_weather(start, n * STEP, temp), track=[(0, 52.4, 9.7)],
    )


def _weather(start: datetime, duration_s: float, temp: float) -> dict:
    """Made-up hourly weather shaped like Open-Meteo's (the demo never asks it). No random numbers, so
    the rest of the made-up data stays the same."""
    hours = []
    for h in range(int(duration_s // 3600) + 2):
        t = (start.replace(minute=0) + timedelta(hours=h))
        dew = temp - 7 + 2 * math.sin(start.toordinal() / 3)
        wind_deg = (start.toordinal() * 47) % 360
        hours.append({"t": t.strftime("%H:%M"), "lat": 52.4, "lon": 9.7, "temp_c": round(temp + 0.4 * h, 1), "dew_point_c": round(dew, 1),
                      "humidity": round(100 * math.exp(17.6 * dew / (243 + dew) - 17.6 * temp / (243 + temp))),
                      "feels_like_c": round(temp + 0.4 * h - 1, 1), "wind_kmh": round(8 + 6 * abs(math.sin(start.toordinal())), 1),
                      "wind_deg": wind_deg})
    avg = lambda k: round(sum(x[k] for x in hours) / len(hours), 1)  # noqa: E731
    return {"temp_c": avg("temp_c"), "dew_point_c": avg("dew_point_c"), "humidity": round(avg("humidity")),
            "feels_like_c": avg("feels_like_c"), "wind_kmh": avg("wind_kmh"), "wind_deg": hours[0]["wind_deg"],
            "wind_dir": open_meteo.compass(hours[0]["wind_deg"]), "source": "Open-Meteo", "hourly": hours}


def _ride(rng, uid, start, ftp, user) -> ParsedActivity:
    minutes = rng.uniform(45, 75)
    n = int(minutes * 60 / STEP)
    recs = []
    ef = ftp / 150  # W per beat
    kind = rng.choice(["easy", "easy", "tempo", "intervals"])
    for i in range(n):
        t = i * STEP
        frac = i / n
        if kind == "easy":
            p = 0.65 * ftp
        elif kind == "tempo":
            p = 0.85 * ftp if 0.15 < frac < 0.85 else 0.55 * ftp
        else:
            p = (1.1 * ftp if int(t // 240) % 2 == 0 else 0.5 * ftp) if 0.15 < frac < 0.85 else 0.55 * ftp
        p *= 1 + rng.gauss(0, 0.05)
        hr = user.rest_hr + (p / ef - user.rest_hr) * min(1, 0.6 + t / 600) * (1 + 0.04 * frac) + rng.gauss(0, 1.5)
        recs.append(Record(t=t, hr=round(hr), power=max(0, p), cadence=88 + rng.gauss(0, 3), speed=p / 30))
    hrs = [r.hr for r in recs]
    outdoor = kind == "easy"  # endurance rides outside (with weather along the route), the hard ones on Zwift
    temp = 12 + 10 * math.sin((start.timetuple().tm_yday - 100) / 365 * 2 * math.pi)
    return ParsedActivity(
        activity_id=f"demo-{uid}-{start:%Y%m%d%H%M}", start_time=start, sport="cycling", raw_sport="cycling",
        sub_sport="road_biking" if outdoor else "indoor_cycling",
        name={"easy": "Endurance Ride", "tempo": "Sweet Spot", "intervals": "VO2 4x4"}[kind],
        duration_s=n * STEP, distance_m=sum(r.speed * STEP for r in recs), avg_hr=sum(hrs) / len(hrs),
        max_hr=max(hrs), indoor=not outdoor, records=recs,
        avg_temp_c=round(temp, 1) if outdoor else None,
        weather=_weather(start, n * STEP, temp) if outdoor else None,
        track=[(0, 52.4, 9.7), (1800, 52.3, 9.5)] if outdoor else [],
    )


def _swim(rng, uid, start, pace100, user) -> ParsedActivity:
    lengths, recs = [], []
    t = 0.0
    for i in range(rng.randint(40, 72)):
        d = pace100 / 4 * (1 + rng.gauss(0, 0.03))
        lengths.append(SwimLength(duration_s=d, strokes=int(17 + rng.gauss(0, 1) + (pace100 - 110) / 10),
                                  stroke_type="freestyle"))
        t += d
        if i % 4 == 3:
            lengths.append(SwimLength(duration_s=20, active=False))
            t += 20
    for i in range(int(t / STEP)):
        recs.append(Record(t=i * STEP, hr=round(125 + rng.gauss(0, 4))))
    active = [ln for ln in lengths if ln.active]
    return ParsedActivity(
        activity_id=f"demo-{uid}-{start:%Y%m%d%H%M}", start_time=start, sport="swimming", raw_sport="swimming",
        sub_sport="lap_swimming", name="Pool Swim", duration_s=sum(ln.duration_s for ln in active),
        distance_m=len(active) * 25, avg_hr=125, indoor=True, pool_length_m=25, records=recs, lengths=lengths,
    )


EXERCISES = [("bench_press.0", "Bench Press", 60), ("squat.4", "Squat", 80), ("deadlift.0", "Deadlift", 100),
             ("shoulder_press.1", "Shoulder Press", 35), ("row.2", "Row", 55)]


def _gym(rng, uid, start, strength: float, user) -> ParsedActivity:
    sets, labels = [], {}
    for key, label, base in rng.sample(EXERCISES, 3):
        labels[key] = label
        w = round(base * strength / 2.5) * 2.5
        for _ in range(3):
            sets.append(ExerciseSet(key, rng.choice([5, 5, 6, 8]), w))
    n = int(55 * 60 / STEP)
    recs = [Record(t=i * STEP, hr=round(105 + 25 * abs(math.sin(i / 40)) + rng.gauss(0, 3))) for i in range(n)]
    return ParsedActivity(
        activity_id=f"demo-{uid}-{start:%Y%m%d%H%M}", start_time=start, sport="strength", raw_sport="training",
        sub_sport="strength_training", name="Strength", duration_s=n * STEP, avg_hr=118, indoor=True,
        records=recs, sets=sets, exercise_labels=labels,
    )


def _other(rng, uid, start, user) -> ParsedActivity:
    n = int(rng.uniform(60, 150) * 60 / STEP)
    recs = [Record(t=i * STEP, hr=round(100 + rng.gauss(0, 6))) for i in range(n)]
    return ParsedActivity(
        activity_id=f"demo-{uid}-{start:%Y%m%d%H%M}", start_time=start, sport="other", raw_sport="hiking",
        name="Hike", duration_s=n * STEP, avg_hr=100, records=recs,
    )


def _pace(lo: str, hi: str) -> dict:
    s = lambda p: int(p.split(":")[0]) * 60 + int(p.split(":")[1])
    return {"type": "pace", "low_s_per_km": s(lo), "high_s_per_km": s(hi)}


def _demo_coach(conn: sqlite3.Connection, user_id: str, ui: int, now: datetime) -> None:
    """Stand-in for garmin_coach.update(): a Garmin Coach plan and Training Readiness."""
    conn.execute("DELETE FROM planned_workouts WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM readiness_days WHERE user_id = ?", (user_id,))
    easy = _pace("6:10", "6:50")
    plan = {"name": "Half Marathon Plan with Garmin Run Coach", "weeks": 12, "week": 4, "end": None}
    workouts = [
        ("Threshold", "LACTATE_THRESHOLD", "3x10:00@5:05/km", [
            {"kind": "warmup", "duration_s": 900, "target": easy},
            *[x for _ in range(3) for x in ({"kind": "interval", "duration_s": 600, "target": _pace("4:55", "5:15")},
                                           {"kind": "recovery", "duration_s": 180, "target": None})][:-1],
            {"kind": "cooldown", "duration_s": 540, "target": easy}]),
        ("Base", "AEROBIC_BASE", "40:00@6:20/km", [{"kind": "interval", "duration_s": 2400, "target": easy}]),
        ("VO2max", "VO2MAX", "5x3:00@4:30/km", [
            {"kind": "warmup", "duration_s": 600, "target": easy},
            *[x for _ in range(5) for x in ({"kind": "interval", "duration_s": 180, "target": _pace("4:20", "4:40")},
                                           {"kind": "recovery", "duration_s": 120, "target": None})],
            {"kind": "cooldown", "duration_s": 600, "target": easy}]),
        ("Rest", None, None, None),
        ("Long run", "LONG_RUN", "1:30:00@6:15/km", [{"kind": "interval", "duration_s": 5400, "target": easy}]),
    ]
    # from Monday on (the plan strip shows the past days of the week too) to 6 days ahead
    for d in range(-now.date().weekday(), 6):
        title, phrase, desc, steps = workouts[(d + ui) % len(workouts)]
        if steps is None:
            continue
        day = (now.date() + timedelta(days=d)).isoformat()
        data = {"title": title, "sport": "running", "phrase": phrase, "description": desc, "steps": steps,
                "est_duration_s": sum(s["duration_s"] for s in steps), "est_distance_m": None,
                "source": "garmin_coach", "plan": plan}
        db.upsert(conn, "planned_workouts", {"user_id": user_id, "day": day, "key": f"demo-{d}", "title": title,
                                             "sport": "running", "data": data, "fetched_at": now.isoformat()})
    if ui == 0:  # the second person shows the "no readiness from Garmin today" state
        r = {"day": now.date().isoformat(), "score": 76, "level": "HIGH", "feedback": "WELL_RESTED",
             "time": now.replace(hour=7, minute=10).isoformat(), "recovery_min": 0,
             "factors": {"sleepScore": 91, "recoveryTime": 100, "acwr": 80, "hrv": 100, "stressHistory": 70, "sleepHistory": 75}}
        db.upsert(conn, "readiness_days", {"user_id": user_id, "day": r["day"], "score": r["score"], "level": r["level"],
                                           "data": r, "fetched_at": now.isoformat()})


def generate(conn: sqlite3.Connection, cfg: AppConfig, days: int = 150, seed: int = 7) -> dict:
    rng = random.Random(seed)
    now = datetime.now().replace(second=0, microsecond=0)
    counts = {}
    demo_profiles = [{"sex": "male", "max_hr": 190.0, "rest_hr": 48.0, "lthr": 172.0},
                     {"sex": "female", "max_hr": 185.0, "rest_hr": 55.0, "lthr": 166.0}]
    for ui, user in enumerate(cfg.users):
        # Stand-in for what profile.refresh() reads from Garmin on a real account.
        for field, value in demo_profiles[ui % 2].items():
            conn.execute("INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?)",
                         (user.id, field, json.dumps(value), "demo data", now.isoformat()))
        user = profile.resolve(conn, user)
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user.id,))
        conn.execute("DELETE FROM verdicts WHERE user_id = ?", (user.id,))
        conn.execute("DELETE FROM health_days WHERE user_id = ?", (user.id,))
        conn.execute("DELETE FROM baseline_exclusions WHERE user_id = ?", (user.id,))
        improving = ui == 0
        n = 0
        for d in range(days, -1, -1):
            day = (now - timedelta(days=d)).date()
            prog = (days - d) / days
            fitness = (1.40 + (0.12 if improving else 0.02) * prog) * (1 + rng.gauss(0, 0.015))
            temp = 12 + 10 * math.sin((day.timetuple().tm_yday - 100) / 365 * 2 * math.pi) + rng.gauss(0, 3)
            wd = day.weekday()
            plan = {0: "gym", 1: "run:intervals", 2: "run:easy", 3: "ride" if improving else "run:easy",
                    4: "swim", 5: "run:long", 6: "other" if rng.random() < 0.3 else None}
            if ui == 1:
                plan = {1: "run:easy", 3: "run:tempo", 5: "run:long", 6: "gym"}
            item = plan.get(wd)
            if d == 0:
                item = "run:easy"  # a fresh run that just finished → wall takeover
                start = now - timedelta(minutes=55 + ui * 12)
            else:
                start = datetime.combine(day, datetime.min.time()) + timedelta(hours=7 if ui == 0 else 18,
                                                                                 minutes=rng.randint(0, 50))
            if not item or (d > 0 and rng.random() < 0.12):
                continue
            if item.startswith("run"):
                act = _run(rng, user.id, start, fitness, item.split(":")[1], user, temp, showcase=d == 0 and improving)
                if d == 0 and improving:
                    act.rpe, act.feel = 3, 75
            elif item == "ride":
                act = _ride(rng, user.id, start, 230 + 25 * prog, user)
            elif item == "swim":
                act = _swim(rng, user.id, start, 118 - 8 * prog, user)
            elif item == "gym":
                act = _gym(rng, user.id, start, 1 + 0.15 * prog + rng.gauss(0, 0.02), user)
            else:
                act = _other(rng, user.id, start, user)
            if act.rpe is None and rng.random() < 0.7:
                act.rpe = rng.choice([3, 4, 5, 6, 7])
                act.feel = rng.choice([25, 50, 50, 75, 75, 100])
            if d == 0 or rng.random() < 0.9:
                pipeline.store_activity(conn, user, act)
                n += 1
        # health
        hdays = []
        for d in range(days, -1, -1):
            day = date.today() - timedelta(days=d)
            prog = (days - d) / days
            sleep = rng.gauss(430, 40)
            hdays.append({
                "day": day.isoformat(),
                "rhr": round(user.rest_hr + 4 - (3 * prog if improving else 0) + rng.gauss(0, 1.5)),
                "hrv_last_night": round(52 + (8 * prog if improving else 0) + rng.gauss(0, 6)),
                "hrv_weekly": round(52 + (8 * prog if improving else 0)),
                "hrv_baseline_low": 45, "hrv_baseline_high": 65, "hrv_status": "BALANCED",
                "sleep_total_min": sleep, "sleep_deep_min": sleep * 0.18, "sleep_rem_min": sleep * 0.22,
                "sleep_light_min": sleep * 0.55, "sleep_awake_min": sleep * 0.05,
                "sleep_score": max(40, min(98, round(60 + (sleep - 380) / 3 + rng.gauss(0, 5)))),
                "stress_avg": round(rng.gauss(30, 7)), "bb_max": round(rng.gauss(80, 10)),
                "bb_min": round(rng.gauss(20, 6)), "steps": round(rng.gauss(9500, 2500)),
                "vo2max": round(49 + (3 * prog if improving else 0.5 * prog), 1) if d % 7 == 0 else None,
            })
        pipeline.store_health(conn, user.id, hdays)
        pipeline.evaluate_all(conn, user.id)
        pipeline.refresh_heat(conn, user.id)  # made-up runs raise HR in the heat: their heat response is learned
        _demo_coach(conn, user.id, ui, now)
        db.upsert(conn, "sync_status", {"user_id": user.id, "last_attempt": now.isoformat(),
                                        "last_success": now.isoformat(), "last_error": None})
        conn.commit()
        counts[user.id] = n
    return counts
