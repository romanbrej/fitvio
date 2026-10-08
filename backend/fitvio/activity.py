"""Normalized activity representation, independent of where the data came from
(GarminDB + FIT file, or the demo generator)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Record:
    t: float                      # seconds since activity start
    hr: float | None = None
    speed: float | None = None    # m/s
    distance: float | None = None  # m, cumulative
    altitude: float | None = None  # m
    power: float | None = None    # W
    cadence: float | None = None
    temperature: float | None = None  # °C


@dataclass
class Lap:
    start_s: float
    duration_s: float
    distance_m: float | None = None
    avg_hr: float | None = None
    avg_speed: float | None = None
    avg_power: float | None = None


@dataclass
class SwimLength:
    duration_s: float
    strokes: int | None = None
    stroke_type: str | None = None
    active: bool = True


@dataclass
class ExerciseSet:
    exercise: str
    reps: int | None
    weight_kg: float | None
    duration_s: float | None = None  # timed sets (a 45 s plank) have no reps


@dataclass
class ParsedActivity:
    activity_id: str
    start_time: datetime
    sport: str                     # normalized: running | cycling | swimming | strength | other
    raw_sport: str | None = None
    sub_sport: str | None = None
    name: str | None = None
    duration_s: float = 0.0
    distance_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    ascent_m: float | None = None
    avg_temp_c: float | None = None
    indoor: bool = False
    rpe: float | None = None       # 1..10
    feel: float | None = None      # 0..100
    pool_length_m: float | None = None
    records: list[Record] = field(default_factory=list)
    laps: list[Lap] = field(default_factory=list)
    lengths: list[SwimLength] = field(default_factory=list)
    sets: list[ExerciseSet] = field(default_factory=list)
    exercise_labels: dict[str, str] = field(default_factory=dict)  # set key -> display name
    # Garmin's weather for the activity (station near the start, at start time) and heat acclimation %
    weather: dict | None = None
    heat_acclimation: float | None = None

    @property
    def has_power(self) -> bool:
        return sum(1 for r in self.records if r.power) > max(30, len(self.records) * 0.5)


RUN_SPORTS = {"running", "trail_running", "treadmill_running", "track_running"}
CYCLE_SPORTS = {"cycling", "indoor_cycling", "virtual_ride", "road_biking", "mountain_biking", "gravel_cycling",
                "e_bike_fitness", "virtual_activity"}
SWIM_SPORTS = {"swimming", "lap_swimming", "open_water", "open_water_swimming"}
STRENGTH_SPORTS = {"strength_training", "training", "fitness_equipment"}
INDOOR_SUBS = {"treadmill", "indoor_cycling", "virtual_activity", "virtual_ride", "indoor_running", "lap_swimming",
               "strength_training", "indoor_rowing"}


def normalize_sport(sport: str | None, sub_sport: str | None) -> tuple[str, bool]:
    """Map Garmin sport/sub_sport to our model key and an indoor flag."""
    s = (sport or "").lower()
    sub = (sub_sport or "").lower()
    indoor = sub in INDOOR_SUBS or "indoor" in sub or "virtual" in sub or "treadmill" in sub
    if s in RUN_SPORTS or sub in RUN_SPORTS:
        return "running", indoor
    if s in CYCLE_SPORTS or sub in CYCLE_SPORTS:
        return "cycling", indoor
    if s in SWIM_SPORTS or sub in SWIM_SPORTS:
        return "swimming", sub == "lap_swimming"
    if sub == "strength_training" or (s in STRENGTH_SPORTS and sub in {"strength_training", ""}):
        return "strength", True
    return "other", indoor


FIT_INVALID_TEMPS = {127, -128, 255}  # FIT "no value" markers for (s)int8 temperature fields


def plausible_temp(v) -> float | None:
    """A temperature in °C, or None for FIT 'no value' markers and physically implausible values."""
    if not isinstance(v, (int, float)) or v in FIT_INVALID_TEMPS or not -40 <= v <= 60:
        return None
    return float(v)
