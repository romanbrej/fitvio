"""'What improved' after an activity."""
from healthdash.improvements import Weights, best_items, delta_items, fitness_item, vo2max_item


def run(day="2026-09-28", dist=10000, speed=None, sid="s"):
    return {"id": sid, "sport": "running", "start_time": f"{day}T17:00:00", "distance_m": dist,
            "features": {"ref_hr": 151, "speed_at_ref_hr_adj": speed}}


def test_fitness_tone_follows_the_weekly_direction():
    up = fitness_item({"fitness_before": 46.1, "fitness_after": 47.0, "ramp_7d": 2.1})
    assert up["value_fmt"] == "47" and up["tone"] == "improving"
    assert up["change_fmt"] == "+0.9 from this session · +2.1 this week"
    assert fitness_item({"fitness_before": 45, "fitness_after": 46.7, "ramp_7d": -2.3})["tone"] == "declining"
    assert fitness_item({"fitness_before": 45, "fitness_after": 45.5, "ramp_7d": 0.2})["tone"] == "steady"


def test_faster_at_same_hr_in_seconds_per_km():
    # usual 2.40 m/s = 6:57 /km, today 2.50 m/s = 6:40 /km
    d = {"key": "speed_at_ref_hr", "label": "Pace at fixed HR", "value": 2.5, "baseline": 2.4, "z": 1.4}
    [item] = delta_items(run(), [d], None)
    assert item["label"] == "Pace @151 bpm" and item["value_fmt"] == "6:40 /km"
    assert item["change_fmt"] == "17 s/km faster than usual" and item["tone"] == "improving"
    d.update(value=2.4, baseline=2.41, z=0.1)
    assert delta_items(run(), [d], None)[0]["change_fmt"] == "like usual"


def test_cycling_power_as_w_per_kg_with_weight_at_ride_date():
    w = Weights([{"day": "2026-07-11", "weight_kg": 85.0}], profile_kg=83.0)
    assert w.at("2026-08-01") == 85.0 and w.at("2026-01-01") == 83.0
    ride = {"id": "r", "sport": "cycling", "start_time": "2026-08-01T18:00:00", "features": {"ref_hr": 151}}
    d = {"key": "power_at_ref_hr", "label": "Power at fixed HR", "value": 178.5, "baseline": 170.0, "z": 1.0}
    [item] = delta_items(ride, [d], w.at("2026-08-01"))
    assert item["value_fmt"] == "2.10 W/kg" and item["change_fmt"] == "+0.10 W/kg vs usual"


def test_vo2max_before_and_after_the_activity_day():
    health = [{"day": "2026-09-20", "vo2max": 44.1}, {"day": "2026-09-28", "vo2max": 44.3}]
    item = vo2max_item(run(), health)
    assert item["value_fmt"] == "44.1 → 44.3" and item["tone"] == "improving"
    same = vo2max_item(run(), [{"day": "2026-09-20", "vo2max": 44.1}, {"day": "2026-09-29", "vo2max": 44.1}])
    assert same["change_fmt"] == "unchanged" and same["tone"] == "steady"
    assert vo2max_item(run(), [{"day": "2026-09-20", "vo2max": 44.1}]) is None  # not updated yet


def test_longest_and_fastest_in_90_days_are_bests():
    history = [run(f"2026-09-{d:02d}", dist=8000, speed=2.4, sid=str(d)) for d in (5, 10, 15, 20)]
    today = run(dist=14200, speed=2.6)
    labels = [i["label"] for i in best_items(today, history, ["New all-time 5-min power best: 250 W (previous 240 W)"])]
    assert labels == ["New best", "Longest run in 90 days", "Fastest at 151 bpm in 90 days"]
    assert best_items(today, history[:2], []) == []  # too little history to call it a best


def test_good_news_comes_first(monkeypatch):
    import healthdash.improvements as imp
    monkeypatch.setattr(imp, "user_sessions", lambda conn, uid: [])
    monkeypatch.setattr(imp.profile, "stored", lambda conn, uid: {})

    class Conn:
        def execute(self, *a):
            return []

    session = run()
    session.update(user_id="u", verdict={"trend": {"fitness_before": 46, "fitness_after": 47, "ramp_7d": -2},
                                         "deltas": [{"key": "speed_at_ref_hr", "label": "Pace", "value": 2.5,
                                                     "baseline": 2.4, "z": 1.2},
                                                    {"key": "decoupling", "label": "HR drift", "value": 3.0,
                                                     "baseline": 3.1, "z": 0.1}], "reasons": []})
    tones = [i["tone"] for i in imp.what_improved(Conn(), session)]
    assert tones == ["improving", "steady", "declining"]  # pace ▲, drift ●, fitness ▼


def test_gym_without_weights_has_no_lift_items():
    gym = {"id": "g", "sport": "strength", "start_time": "2026-09-10T17:00:00", "features": {}}
    assert delta_items(gym, [{"key": "10.30", "label": "10", "value": None, "baseline": None, "z": None}], None) == []
