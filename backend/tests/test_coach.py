"""Today's training (Garmin calendar), readiness, week streak, sweet spot and running cadence.

The Garmin answers in tests/fixtures/garmin are real responses (anonymized) — the endpoints are
undocumented, so the parser is pinned to what Garmin actually sends."""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from healthdash import coach, db
from healthdash.sync import garmin_coach

FIX = Path(__file__).parent / "fixtures" / "garmin"


def fixture(name):
    return json.loads((FIX / name).read_text())


# --- parsing real Garmin answers ------------------------------------------------------------

def test_parse_adaptive_workout_steps_and_pace_targets():
    w = garmin_coach.parse_workout(fixture("fbt_adaptive_workout.json"))
    assert w["title"] == "Schwelle" and w["sport"] == "running"
    assert w["phrase"] == "LACTATE_THRESHOLD"
    assert w["est_duration_s"] == 2220
    assert [s["kind"] for s in w["steps"]] == ["warmup", "interval", "cooldown"]
    assert [s["duration_s"] for s in w["steps"]] == [600, 1020, 600]
    # Garmin sends m/s (3.222–2.944) → 5:10–5:40 /km, the faster one first
    assert w["steps"][1]["target"] == {"type": "pace", "low_s_per_km": 310, "high_s_per_km": 340}


def test_repeat_groups_are_expanded():
    raw = {"workoutName": "6x800", "sportType": {"sportTypeKey": "running"}, "workoutSegments": [{"workoutSteps": [
        {"type": "ExecutableStepDTO", "stepOrder": 1, "stepType": {"stepTypeKey": "warmup"},
         "endCondition": {"conditionTypeKey": "time"}, "endConditionValue": 600},
        {"type": "RepeatGroupDTO", "stepOrder": 2, "numberOfIterations": 6, "workoutSteps": [
            {"type": "ExecutableStepDTO", "stepOrder": 1, "stepType": {"stepTypeKey": "interval"},
             "endCondition": {"conditionTypeKey": "distance"}, "endConditionValue": 800,
             "targetType": {"workoutTargetTypeKey": "heart.rate.zone"}, "targetValueOne": 160, "targetValueTwo": 170},
            {"type": "ExecutableStepDTO", "stepOrder": 2, "stepType": {"stepTypeKey": "recovery"},
             "endCondition": {"conditionTypeKey": "time"}, "endConditionValue": 120}]}]}]}
    w = garmin_coach.parse_workout(raw)
    assert len(w["steps"]) == 13
    assert w["steps"][1] == {"kind": "interval", "duration_s": None, "distance_m": 800,
                             "target": {"type": "hr", "low": 160, "high": 170}, "description": None}
    assert w["est_duration_s"] == 600 + 6 * 120  # no estimate from Garmin: the timed steps


def test_calendar_items_of_the_next_days_only():
    items = garmin_coach.planned_items(fixture("calendar_month.json"), date(2026, 10, 5))
    assert [(i["date"], i["title"]) for i in items][:2] == [("2026-10-05", "Schwelle"), ("2026-10-06", "Basis")]
    assert all(i["itemType"] == "fbtAdaptiveWorkout" for i in items)
    assert len(items) == 7


def test_readiness_takes_the_newest_entry_of_the_day():
    r = garmin_coach.parse_readiness(fixture("training_readiness.json"))
    assert (r["score"], r["level"], r["feedback"]) == (52, "MODERATE", "WELL_RESTED")  # after the workout, not 76 from waking
    assert r["factors"]["hrv"] == 100
    assert garmin_coach.parse_readiness([]) is None


def test_plan_week():
    p = garmin_coach.plan_info(fixture("training_plan.json"), date(2026, 10, 5))
    assert p == {"name": "Half Marathon Plan with Garmin Run Coach", "weeks": 12, "week": 4, "end": "2026-12-07"}


# --- fetch + store: a failure keeps the last good copy --------------------------------------

def fake_garmin(fail_on=None):
    answers = {"/calendar-service/year/2026/month/9": fixture("calendar_month.json"),
               "/metrics-service/metrics/trainingreadiness/2026-10-05": fixture("training_readiness.json")}

    def connectapi(path, **_):
        if fail_on and fail_on in path:
            raise ConnectionError("Garmin down")
        if path.startswith("/workout-service/fbt-adaptive/"):
            return fixture("fbt_adaptive_workout.json")
        if path.startswith("/trainingplan-service/"):
            return fixture("training_plan.json")
        return answers.get(path, {"calendarItems": []})
    return connectapi


def test_update_stores_workouts_and_readiness():
    conn = db.connect(":memory:")
    res = garmin_coach.update(conn, "u", fake_garmin(), today=date(2026, 10, 5))
    assert res == {"workouts": 7, "readiness": 52}
    row = db.row_to_dict(conn.execute("SELECT * FROM planned_workouts WHERE day = '2026-10-05'").fetchone())
    assert row["title"] == "Schwelle" and row["data"]["plan"]["week"] == 4
    assert row["data"]["source"] == "garmin_coach"


def test_ids_from_garmin_are_validated_before_they_go_into_a_path():
    cal = fixture("calendar_month.json")
    bad = dict(next(i for i in cal["calendarItems"] if i["itemType"] == "fbtAdaptiveWorkout"))
    bad.update(workoutUuid="../../userprofile-service/socialProfile", trainingPlanId="1/../2", workoutId=None)
    cal["calendarItems"] = [bad]
    paths = []

    def connectapi(path, **_):
        paths.append(path)
        return cal if path.startswith("/calendar-service/") else []
    conn = db.connect(":memory:")
    assert garmin_coach.update(conn, "u", connectapi, today=date(2026, 10, 5))["workouts"] == 0
    assert not any(".." in p for p in paths)


def test_later_days_reuse_todays_details_today_and_tomorrow_are_refetched():
    conn = db.connect(":memory:")
    garmin_coach.update(conn, "u", fake_garmin(), today=date(2026, 10, 5))
    calls = []
    inner = fake_garmin()

    def counting(path, **kw):
        calls.append(path)
        return inner(path, **kw)
    garmin_coach.update(conn, "u", counting, today=date(2026, 10, 5))
    assert sum(p.startswith("/workout-service/") for p in calls) == 2  # only today + tomorrow again


def test_old_planned_workouts_are_pruned():
    conn = db.connect(":memory:")
    db.upsert(conn, "planned_workouts", {"user_id": "u", "day": "2026-09-01", "key": "old", "title": "x", "sport": "running",
                                         "data": {}, "fetched_at": "2026-09-01T06:00:00"})
    garmin_coach.update(conn, "u", fake_garmin(), today=date(2026, 10, 5))
    assert conn.execute("SELECT COUNT(*) FROM planned_workouts WHERE key = 'old'").fetchone()[0] == 0


def test_no_coach_requests_during_the_rate_limit_pause(monkeypatch):
    from datetime import datetime as dt
    from healthdash.sync import activity_watch
    conn = db.connect(":memory:")
    db.set_state(conn, activity_watch.K_BACKOFF, (dt.now() + timedelta(hours=1)).isoformat(timespec="seconds"))
    monkeypatch.setattr(activity_watch, "cached_client", lambda u: pytest.fail("must not call Garmin"))
    garmin_coach.update_user(conn, type("U", (), {"id": "u"})())


def test_readiness_without_a_date_falls_back_to_today():
    rows = [{"score": 70, "level": "HIGH", "timestampLocal": "2026-10-05T07:00:00.0"}]
    assert garmin_coach.parse_readiness(rows, date(2026, 10, 5))["day"] == "2026-10-05"


def test_failed_fetch_keeps_the_last_good_copy():
    conn = db.connect(":memory:")
    garmin_coach.update(conn, "u", fake_garmin(), today=date(2026, 10, 5))
    with pytest.raises(ConnectionError):
        garmin_coach.update(conn, "u", fake_garmin(fail_on="trainingreadiness"), today=date(2026, 10, 5))
    assert conn.execute("SELECT COUNT(*) FROM planned_workouts").fetchone()[0] == 7


# --- read side --------------------------------------------------------------------------------

def sess(day, sport="running", dur=3000, load=80.0, stype="easy", name="Run", cad=None, sid=None):
    return {"id": sid or f"u:{day}:{sport}:{name}", "start_time": f"{day}T07:00:00", "sport": sport, "duration_s": dur,
            "load": load, "session_type": stype, "name": name, "features": {"avg_cadence": cad} if cad else {}}


def test_week_streak_counts_weeks_with_three_workouts():
    today = date(2026, 10, 8)  # Thursday
    days = []
    for w in range(1, 4):  # three full weeks with 3 workouts
        monday = today - timedelta(days=today.weekday() + 7 * w)
        days += [monday, monday + timedelta(days=2), monday + timedelta(days=4)]
    monday = today - timedelta(days=today.weekday() + 28)
    days += [monday, monday + timedelta(days=1)]  # only 2 → ends the streak
    days += [today - timedelta(days=3), today - timedelta(days=1)]  # this week: 2 so far
    days.append(today - timedelta(days=2))
    s = coach.week_streak([sess(d.isoformat(), dur=1800) for d in days[:-1]] + [sess(days[-1].isoformat(), dur=300)], today)
    assert s["weeks"] == 3 and s["this_week"] == 2 and s["needed"] == 1  # the 5-min one doesn't count
    s = coach.week_streak([sess(d.isoformat()) for d in days], today)
    assert s["weeks"] == 4 and s["needed"] == 0  # this week reached 3 → it counts


def test_sweet_spot_from_fitness_at_the_start_of_the_week():
    today = date(2026, 10, 8)
    series = [{"day": (today - timedelta(days=i)).isoformat(), "fitness": 60.0 if i > 3 else 99.0} for i in range(10, -1, -1)]
    ss = coach.sweet_spot(series, [sess("2026-10-06", load=120), sess("2026-09-30", load=500)], today)
    assert ss["fitness_at_start"] == 60.0  # Sunday's fitness, not today's
    assert (ss["low"], ss["high"]) == (470, 650)  # 7·60 + 45.6 … 7·60 + 228
    assert ss["load"] == 120


def test_today_workout_done_detection_prefers_garmins_name_link(tmp_path):
    conn = db.connect(":memory:")
    garmin_coach.update(conn, "u", fake_garmin(), today=date(2026, 10, 5))
    sessions = [sess("2026-10-05", name="Morning run", sid="u:1"), sess("2026-10-05", name="City - Schwelle", sid="u:2")]
    w, upcoming = coach.planned(conn, "u", sessions, date(2026, 10, 5))
    assert w["title"] == "Schwelle" and w["done"]["session_id"] == "u:2" and w["done"]["linked"]
    assert upcoming[0]["day"] == "2026-10-06" and len(upcoming) == 6 and upcoming[0]["est_load"]
    assert upcoming[0]["steps"]  # the plan page shows any day's profile and steps
    w, _ = coach.planned(conn, "u", [sess("2026-10-05", sport="cycling", sid="u:3")], date(2026, 10, 5))
    assert w["done"] is None  # a ride doesn't complete a run
    w, _ = coach.planned(conn, "u", [sess("2026-10-05", name="Lunch run", sid="u:4")], date(2026, 10, 5))
    assert w["done"]["session_id"] == "u:4" and not w["done"]["linked"]


def test_targets_hit_uses_the_time_window_of_each_work_step():
    w = {"steps": [{"kind": "warmup", "duration_s": 600, "target": None},
                   {"kind": "interval", "duration_s": 1020, "target": {"type": "pace", "low_s_per_km": 310, "high_s_per_km": 340}},
                   {"kind": "cooldown", "duration_s": 600, "target": None}]}
    t = list(range(0, 2220, 5))
    speed = [2.5 if x < 600 or x >= 1620 else 1000 / 332 for x in t]  # 5:32 /km in the work step
    assert coach._targets_hit(w, {"t": t, "speed": speed}) == {"hit": 1, "of": 1}
    slow = [2.5 if x < 600 or x >= 1620 else 1000 / 360 for x in t]
    assert coach._targets_hit(w, {"t": t, "speed": slow}) == {"hit": 0, "of": 1}
    assert coach._targets_hit(w, None) is None


def test_estimated_load_uses_own_history():
    today = date(2026, 10, 5)
    hist = [sess((today - timedelta(days=i)).isoformat(), dur=3600, load=110, stype="tempo") for i in (3, 10, 17)]
    w = {"sport": "running", "phrase": "LACTATE_THRESHOLD", "est_duration_s": 1800}
    assert coach.estimate_load(w, hist, today) == 55
    assert coach.estimate_load(w, [], today) == 60  # default 120/h


def test_running_cadence_trend_from_easy_runs_in_steps_per_minute():
    today = date(2026, 10, 5)
    runs = [sess((today - timedelta(days=i)).isoformat(), cad=89) for i in (2, 9, 16)]  # per leg → 178 spm
    runs += [sess((today - timedelta(days=i)).isoformat(), cad=172) for i in (50, 57, 64)]
    runs.append(sess((today - timedelta(days=4)).isoformat(), cad=95, stype="intervals"))  # ignored
    assert coach.running_cadence(runs, today) == {"spm": 178, "change": 6, "runs": 3}


# --- the plan week strip -------------------------------------------------------------------

def put_plan(conn, day, title="Basis", sport="running", week=4):
    data = {"title": title, "sport": sport, "phrase": "AEROBIC_BASE", "steps": [], "est_duration_s": 2700,
            "plan": {"name": "Half Marathon Plan", "weeks": 12, "week": week, "end": "2026-12-07"}}
    db.upsert(conn, "planned_workouts", {"user_id": "u", "day": day, "key": f"k-{day}", "title": title,
                                         "sport": sport, "data": data, "fetched_at": f"{day}T06:00:00"})


def test_plan_week_marks_done_missed_today_planned_and_rest():
    conn = db.connect(":memory:")
    for d, t in [("2026-10-05", "Basis"), ("2026-10-06", "Basis"), ("2026-10-07", "VO2max"),
                 ("2026-10-08", "Schwelle"), ("2026-10-10", "Langer Lauf")]:
        put_plan(conn, d, t, week=3 if d == "2026-10-05" else 4)
    sessions = [sess("2026-10-05", name="Run"),                       # done
                sess("2026-10-06", dur=300),                          # too short → missed
                sess("2026-10-07", sport="cycling"),                  # wrong sport → missed
                sess("2026-10-03")]                                   # last week: not in the window
    pw = coach.plan_week(conn, "u", sessions, date(2026, 10, 8))     # Thursday
    assert pw["start"] == "2026-10-05"
    assert [d["status"] for d in pw["days"]] == ["done", "missed", "missed", "today", "rest", "planned", "rest"]
    assert (pw["done"], pw["due"], pw["planned"]) == (1, 3, 5)
    assert pw["plan"]["week"] == 4  # the newest fetch's week number, not Monday's stale one
    assert pw["days"][0]["session_id"] == "u:2026-10-05:running:Run"
    assert pw["days"][0]["done"]["session_id"] == pw["days"][0]["session_id"] and "headline" in pw["days"][0]["done"]

    sessions.append(sess("2026-10-08", name="City - Schwelle", sid="u:linked"))
    pw = coach.plan_week(conn, "u", sessions, date(2026, 10, 8))
    assert pw["days"][3]["status"] == "done" and pw["days"][3]["session_id"] == "u:linked"
    assert (pw["done"], pw["due"]) == (2, 4)


def test_plan_week_on_sunday_shows_the_coming_days():
    conn = db.connect(":memory:")
    put_plan(conn, "2026-10-13")
    pw = coach.plan_week(conn, "u", [], date(2026, 10, 11))  # Sunday
    assert pw["start"] == "2026-10-11" and pw["days"][2]["status"] == "planned"
    assert coach.plan_window(date(2026, 10, 10)) == date(2026, 10, 5)  # Saturday: still Mon–Sun


def test_plan_week_is_none_without_a_plan():
    conn = db.connect(":memory:")
    assert coach.plan_week(conn, "u", [sess("2026-10-08")], date(2026, 10, 8)) is None
    put_plan(conn, "2026-09-28")  # only last week
    assert coach.plan_week(conn, "u", [], date(2026, 10, 8)) is None
