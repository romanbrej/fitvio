from datetime import datetime, timedelta

import pytest

from fitvio import db, pipeline, wall
from fitvio.activity import ExerciseSet, ParsedActivity
from fitvio.config import AppConfig, UserConfig, WallConfig

from .test_analytics import steady_records

USER = UserConfig(id="u", name="Test User", max_hr=190, rest_hr=50)


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "app.db")


@pytest.fixture
def cfg(tmp_path):
    return AppConfig(users=[USER, UserConfig(id="p", name="Partner")], wall=WallConfig(), db_path=tmp_path / "app.db")


def add_run(conn, start, speed, hr=137, aid=None, user=USER):
    act = ParsedActivity(activity_id=aid or start.strftime("%Y%m%d%H%M"), start_time=start, sport="running",
                         name="Easy", duration_s=2700, distance_m=speed * 2700,
                         records=steady_records(minutes=45, hr=hr, speed=speed))
    return pipeline.store_activity(conn, user, act)


def test_not_comparable_until_three_similar(conn):
    base = datetime(2026, 8, 1, 7)
    sids = [add_run(conn, base + timedelta(days=i * 2), 3.0) for i in range(3)]
    v = pipeline.evaluate_session(conn, "u", sids[-1])
    assert v["verdict"] == "not_comparable"  # only 2 earlier runs


def test_faster_at_same_hr_is_better(conn):
    base = datetime(2026, 8, 1, 7)
    for i in range(6):
        add_run(conn, base + timedelta(days=i * 2), 3.0 + (i % 2) * 0.01)
    sid = add_run(conn, base + timedelta(days=14), 3.15)
    v = pipeline.evaluate_session(conn, "u", sid)
    assert v["verdict"] == "better"
    assert any("Aerobic efficiency" in r for r in v["reasons"])


def test_slower_at_same_hr_is_worse(conn):
    base = datetime(2026, 8, 1, 7)
    for i in range(6):
        add_run(conn, base + timedelta(days=i * 2), 3.0 + (i % 2) * 0.01)
    sid = add_run(conn, base + timedelta(days=14), 2.85)
    assert pipeline.evaluate_session(conn, "u", sid)["verdict"] == "worse"


def test_same_performance_is_in_line(conn):
    base = datetime(2026, 8, 1, 7)
    for i in range(6):
        add_run(conn, base + timedelta(days=i * 2), 3.0 + (i % 2) * 0.01)
    sid = add_run(conn, base + timedelta(days=14), 3.005)
    assert pipeline.evaluate_session(conn, "u", sid)["verdict"] == "in_line"


def test_strength_progression(conn):
    base = datetime(2026, 8, 1, 18)
    for i, w in enumerate([80, 80, 82.5, 90]):
        act = ParsedActivity(activity_id=f"g{i}", start_time=base + timedelta(days=i * 3), sport="strength",
                             duration_s=3600, records=[],
                             sets=[ExerciseSet("squat.4", 5, w)] * 3, exercise_labels={"squat.4": "Squat"})
        sid = pipeline.store_activity(conn, USER, act)
    v = pipeline.evaluate_session(conn, "u", sid)
    assert v["verdict"] == "better"
    assert any("personal record" in r.lower() for r in v["reasons"])


def test_outdoor_ride_without_power_is_load_only(conn):
    act = ParsedActivity(activity_id="r1", start_time=datetime(2026, 8, 1, 7), sport="cycling", duration_s=3600,
                         records=steady_records(minutes=60, hr=130, speed=8))
    sid = pipeline.store_activity(conn, USER, act)
    v = pipeline.evaluate_session(conn, "u", sid)
    assert v["verdict"] == "load_only" and v["confidence"] == "low"


def test_wall_takeover_rules(conn, cfg):
    now = datetime.now().replace(microsecond=0)
    old = add_run(conn, now - timedelta(days=3), 3.0, aid="old")
    fresh = add_run(conn, now - timedelta(minutes=50), 3.0, aid="fresh")
    pipeline.evaluate_all(conn, "u")
    v = wall.fresh_verdict(conn, cfg, now)
    assert v["session_id"] == fresh
    wall.mark_shown(conn, fresh, now)
    # still shown within the window
    assert wall.fresh_verdict(conn, cfg, now + timedelta(minutes=30))["session_id"] == fresh
    # gone after the window
    assert wall.fresh_verdict(conn, cfg, now + timedelta(minutes=61)) is None
    # re-evaluation (e.g. nightly recompute) must not re-trigger it
    pipeline.evaluate_all(conn, "u")
    assert wall.fresh_verdict(conn, cfg, now + timedelta(minutes=61)) is None
    assert old != fresh


def test_latest_activity_wins_across_users(conn, cfg):
    now = datetime.now().replace(microsecond=0)
    add_run(conn, now - timedelta(minutes=90), 3.0, aid="mine")
    theirs = add_run(conn, now - timedelta(minutes=20), 3.0, aid="theirs", user=cfg.users[1])
    pipeline.evaluate_all(conn, "u")
    pipeline.evaluate_all(conn, "p")
    assert wall.fresh_verdict(conn, cfg, now)["session_id"] == theirs


def test_backfilled_old_activity_never_takes_over(conn, cfg):
    now = datetime.now().replace(microsecond=0)
    add_run(conn, now - timedelta(days=2), 3.0, aid="backfill")
    pipeline.evaluate_all(conn, "u")
    assert wall.fresh_verdict(conn, cfg, now) is None
