import math
from datetime import date, datetime, timedelta

import pytest

from healthdash.activity import Lap, ParsedActivity, Record, normalize_sport
from healthdash.analytics import load, physio
from healthdash.analytics.features import compute_features
from healthdash.config import UserConfig

USER = UserConfig(id="u", name="Test User", max_hr=190, rest_hr=50)


def steady_records(minutes=40, speed=3.0, hr=140, step=1.0, altitude=None, drift=0.0, power=None):
    out, dist = [], 0.0
    n = int(minutes * 60 / step)
    for i in range(n):
        dist += speed * step
        out.append(Record(t=i * step, hr=hr * (1 + drift * i / n), speed=speed, distance=dist,
                          altitude=altitude(dist) if altitude else 100.0, power=power))
    return out


def test_minetti_flat_and_uphill():
    assert physio.minetti_cost(0) == pytest.approx(3.6)
    assert physio.minetti_cost(0.1) > physio.minetti_cost(0)
    # downhill is cheaper, but steep downhill costs again
    assert physio.minetti_cost(-0.1) < physio.minetti_cost(0)


def test_gap_uphill_is_faster_than_actual():
    recs = steady_records(altitude=lambda d: d * 0.08)  # constant 8 % climb
    gap = physio.grade_adjusted_speeds(recs)
    assert gap[-1] > recs[-1].speed * 1.3


def test_efficiency_and_no_decoupling_on_steady_run():
    recs = steady_records(speed=3.0, hr=150)
    ef = physio.efficiency_factor(recs)
    assert ef == pytest.approx(3.0 * 60 / 150, rel=1e-3)
    assert physio.decoupling(recs) == pytest.approx(0.0, abs=0.01)


def test_decoupling_detects_hr_drift():
    recs = steady_records(speed=3.0, hr=140, drift=0.10)
    assert physio.decoupling(recs) > 3


def test_speed_at_hr_needs_coverage():
    recs = steady_records(hr=140)
    assert physio.speed_at_hr(recs, [r.speed for r in recs], 140) == pytest.approx(3.0)
    assert physio.speed_at_hr(recs, [r.speed for r in recs], 175) is None  # never extrapolate


def test_normalized_power_constant():
    p = [200.0] * 600
    assert physio.normalized_power(p) == pytest.approx(200.0)
    assert physio.power_curve(p)["300"] == pytest.approx(200.0)


def test_normalized_power_above_average_for_variable_effort():
    p = ([300.0] * 60 + [100.0] * 60) * 10
    assert physio.normalized_power(p) > sum(p) / len(p)


def test_epley():
    assert physio.epley_1rm(100, 1) == 100
    assert physio.epley_1rm(100, 5) == pytest.approx(116.67, rel=1e-3)
    assert physio.epley_1rm(None, 5) is None


def test_trimp_increases_with_hr():
    easy = physio.trimp(steady_records(hr=130), 50, 190)
    hard = physio.trimp(steady_records(hr=170), 50, 190)
    assert hard > easy * 1.5


def test_pmc_converges_to_constant_load():
    loads = {date(2026, 1, 1) + timedelta(days=i): 100.0 for i in range(300)}
    series = load.pmc(loads, date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=299))
    assert series[-1]["fitness"] == pytest.approx(100, abs=1)
    assert series[-1]["fatigue"] == pytest.approx(100, abs=0.5)


def test_normalize_sport():
    assert normalize_sport("running", "treadmill") == ("running", True)
    assert normalize_sport("cycling", "indoor_cycling") == ("cycling", True)
    assert normalize_sport("training", "strength_training") == ("strength", True)
    assert normalize_sport("swimming", "lap_swimming") == ("swimming", True)
    assert normalize_sport("hiking", "generic")[0] == "other"


def run_activity(hr, minutes=45, name="Run", speed=3.0):
    return ParsedActivity(activity_id="x", start_time=datetime(2026, 9, 1, 7), sport="running", name=name,
                          duration_s=minutes * 60, distance_m=speed * minutes * 60,
                          records=steady_records(minutes=minutes, hr=hr, speed=speed))


def test_session_classification_uses_hr_reserve():
    # 62 % HRR = 50 + 0.62*140 ≈ 137 bpm → easy
    assert compute_features(run_activity(137), USER)["session_type"] == "easy"
    assert compute_features(run_activity(137, minutes=90), USER)["session_type"] == "long"
    assert compute_features(run_activity(170), USER)["session_type"] == "tempo"
    assert compute_features(run_activity(170, name="Parkrun"), USER)["session_type"] == "race"


LTHR_USER = UserConfig(id="u", name="Test User", max_hr=194, rest_hr=50, lthr=176)


def test_workout_name_decides_the_type():
    # a "Basis" run at 155 bpm is tempo by HR reserve, but it was meant (and run) as an easy run
    assert compute_features(run_activity(155, name="City - Basis"), USER)["session_type"] == "easy"
    assert compute_features(run_activity(155, minutes=90, name="Basis"), USER)["session_type"] == "long"
    assert compute_features(run_activity(170, name="City - Schwelle"), USER)["session_type"] == "tempo"
    assert compute_features(run_activity(137, name="City - Tempo"), USER)["session_type"] == "tempo"
    assert compute_features(run_activity(170, name="City - VO2max"), USER)["session_type"] == "intervals"
    assert compute_features(run_activity(170, name="6x800"), USER)["session_type"] == "intervals"
    assert compute_features(run_activity(140, name="Langer Lauf"), USER)["session_type"] == "long"
    # place names that merely contain a keyword don't count
    assert compute_features(run_activity(137, name="Langenhagen Running"), USER)["session_type"] == "easy"


def test_hr_fallback_uses_lthr():
    # 155 bpm = 88 % of LTHR 176 → easy (HR reserve alone would call it tempo)
    assert compute_features(run_activity(155), LTHR_USER)["session_type"] == "easy"
    assert compute_features(run_activity(165), LTHR_USER)["session_type"] == "tempo"


def interval_activity(name="City - VO2max", work_speed=4.5):
    """10' warm-up, 5 × (3' fast / 3' jog), 10' cool-down, as a Garmin structured workout lays out laps."""
    laps, recs, t, dist = [], [], 0, 0.0
    plan = [(600, 2.8, 140)] + [(180, work_speed, 172), (180, 2.5, 145)] * 5 + [(600, 2.7, 138)]
    for dur, v, hr in plan:
        laps.append(Lap(start_s=t, duration_s=dur, distance_m=v * dur, avg_hr=hr, avg_speed=v))
        for i in range(dur):
            dist += v
            recs.append(Record(t=t + i, hr=hr, speed=v, distance=dist, altitude=100.0))
        t += dur
    return ParsedActivity(activity_id=name, start_time=datetime(2026, 9, 1, 7), sport="running", name=name,
                          duration_s=t, distance_m=dist, records=recs, laps=laps)


def test_interval_reps_judge_only_the_work():
    f = compute_features(interval_activity(), USER)
    assert f["session_type"] == "intervals"
    feats = f["features"]
    assert feats["rep_count"] == 5
    assert feats["work_speed"] == pytest.approx(4.5)
    assert feats["work_hr"] == pytest.approx(172)
    assert feats["hr_recovery"] == pytest.approx(27)
    assert feats["workout_key"] == "vo2max"


def test_intervals_use_rep_metrics_and_same_workout():
    from healthdash.models.sports import model_for

    def session(i, name, speed, day):
        f = compute_features(interval_activity(name, speed), USER)
        return {"id": f"s{i}", "user_id": "u", "sport": "running", "session_type": f["session_type"],
                "start_time": f"2026-09-{day:02d}T07:00:00", "duration_s": 5400, "indoor": 0,
                "features": f["features"], "load": f["load"]}

    history = [session(i, "City - VO2max", 4.4, 1 + i) for i in range(3)]
    history += [session(10 + i, "City - 400er", 5.5, 5 + i) for i in range(3)]  # different workout, faster reps
    today = session(99, "City - VO2max", 4.5, 20)
    v = model_for("running").evaluate(today, history, None, None)
    assert {d["key"] for d in v["deltas"]} == {"work_speed", "work_ef", "hr_recovery"}
    assert set(v["baseline_ids"]) == {"s0", "s1", "s2"}   # VO2max vs VO2max, not vs the 400s
    assert v["verdict"] == "better"
