"""Sport-specific improvement models."""
from __future__ import annotations

from ..analytics import load as load_model
from .base import MIN_SIMILAR, MetricSpec, SportModel


def fmt_pace_km(speed: float) -> str:
    if not speed or speed <= 0:
        return "—"
    s = 1000 / speed
    return f"{int(s // 60)}:{int(round(s % 60)):02d} /km"


def fmt_pace_100(sec: float) -> str:
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d} /100m"


def fmt_num(dp: int, unit: str = ""):
    return lambda v: f"{v:.{dp}f}{unit}"


class RunningModel(SportModel):
    sport = "running"
    primary = "ef_adj"
    metrics = [
        MetricSpec("ef_adj", "Aerobic efficiency", +1, 0.45, fmt_num(2, " m/beat")),
        MetricSpec("speed_at_ref_hr", "Pace at fixed HR", +1, 0.35, fmt_pace_km),
        MetricSpec("decoupling", "HR drift", -1, 0.20, fmt_num(1, " %"), mode="abs", noise=1.5),
    ]

    def is_similar(self, session, other):
        # treadmill and outdoor pace are not comparable
        return super().is_similar(session, other) and bool(other.get("indoor")) == bool(session.get("indoor"))


class CyclingModel(SportModel):
    sport = "cycling"
    primary = "ef"
    metrics = [
        MetricSpec("ef", "Power per heartbeat", +1, 0.5, fmt_num(2, " W/beat")),
        MetricSpec("decoupling", "Power:HR drift", -1, 0.2, fmt_num(1, " %"), mode="abs", noise=1.5),
        MetricSpec("p300", "Best 5-min power", +1, 0.3, fmt_num(0, " W"), noise=0.02,
                   get=lambda f: (f.get("power_curve") or {}).get("300")),
    ]

    def load_only_reason(self, session):
        if not session.get("has_power"):
            return "No power data — outdoor ride speed is dominated by wind and terrain, so only load is counted (low confidence)."
        return None

    def is_similar(self, session, other):
        return super().is_similar(session, other) and bool(other.get("has_power"))

    def extra_reasons(self, session, same_sport):
        curve = (session.get("features") or {}).get("power_curve") or {}
        out = []
        labels = {"5": "5-s", "60": "1-min", "300": "5-min", "1200": "20-min"}
        for d, label in labels.items():
            v = curve.get(d)
            prev = [((s.get("features") or {}).get("power_curve") or {}).get(d) for s in same_sport]
            prev = [p for p in prev if p]
            if v and len(prev) >= MIN_SIMILAR and v > max(prev):
                out.append(f"New all-time {label} power best: {v:.0f} W (previous {max(prev):.0f} W)")
        return out


class SwimmingModel(SportModel):
    sport = "swimming"
    primary = "pace_100m_s"
    metrics = [
        MetricSpec("pace_100m_s", "Pace per 100 m", -1, 0.6, fmt_pace_100),
        MetricSpec("swolf", "SWOLF", -1, 0.4, fmt_num(0), mode="abs", noise=1.0),
    ]

    def is_similar(self, session, other):
        a = (session.get("features") or {}).get("main_stroke")
        b = (other.get("features") or {}).get("main_stroke")
        return (super().is_similar(session, other) and a == b
                and bool(other.get("indoor")) == bool(session.get("indoor")))


class StrengthModel(SportModel):
    """Per exercise: estimated 1RM vs the best of the previous 3 sessions containing that exercise."""
    sport = "strength"
    STRONGER, WEAKER = 0.02, -0.03

    def evaluate(self, session, history, health, health_base):
        same = sorted((h for h in history if h["sport"] == "strength"), key=lambda h: h["start_time"], reverse=True)
        trend = load_model.impact_of(session, history + [session])
        context = self.context_notes(session, health, health_base, trend)
        exercises = (session.get("features") or {}).get("exercises") or {}
        if not exercises:
            return self._result(session, "load_only", "low", None,
                                f"Logged — training load {session.get('load') or 0:.0f}",
                                ["No sets with reps and weight were logged on the watch for this session."],
                                [], context, trend, [])
        deltas, used_ids = [], set()
        for ex, cur in sorted(exercises.items()):
            prev = []
            for h in same:
                p = ((h.get("features") or {}).get("exercises") or {}).get(ex)
                if p and p.get("e1rm"):
                    prev.append(p["e1rm"])
                    used_ids.add(h["id"])
                if len(prev) == 3:
                    break
            row = {"key": ex, "label": cur.get("label") or ex.replace("_", " ").title(), "value": cur.get("e1rm"),
                   "baseline": max(prev) if prev else None, "delta": None, "delta_pct": None, "z": None,
                   "weight": 1.0, "better": 1, "n": len(prev),
                   "value_fmt": f"{cur['e1rm']:.1f} kg e1RM" if cur.get("e1rm") else "—",
                   "baseline_fmt": f"{max(prev):.1f} kg" if prev else "—",
                   "sets": cur.get("sets"), "volume": cur.get("volume"),
                   "all_time_best": max((((h.get("features") or {}).get("exercises") or {}).get(ex, {}).get("e1rm") or 0)
                                        for h in same) if same else None}
            if cur.get("e1rm") and prev:
                rel = (cur["e1rm"] - max(prev)) / max(prev)
                row["delta"] = round(cur["e1rm"] - max(prev), 1)
                row["delta_pct"] = round(rel * 100, 1)
                row["delta_fmt"] = f"{'+' if rel > 0 else '−' if rel < 0 else '±'}{abs(rel * 100):.1f}%"
                row["z"] = 1.0 if rel >= self.STRONGER else -1.0 if rel <= self.WEAKER else 0.0
            deltas.append(row)
        judged = [d for d in deltas if d["z"] is not None]
        if not judged:
            return self._result(session, "not_comparable", "low", None,
                                "Not comparable yet — first time logging these exercises",
                                ["Log the same exercises a few more times to track strength progression."],
                                deltas, context, trend, [])
        up = sum(1 for d in judged if d["z"] > 0)
        down = sum(1 for d in judged if d["z"] < 0)
        score = (up - down) / len(judged)
        verdict = "better" if score >= 0.34 else "worse" if score <= -0.34 else "in_line"
        headline = {"better": "Stronger than your recent sessions", "worse": "Weaker than your recent sessions",
                    "in_line": "Strength held"}[verdict]
        reasons = []
        for d in sorted(judged, key=lambda d: -abs(d["delta_pct"] or 0))[:3]:
            word = "up" if d["delta_pct"] > 0 else "down" if d["delta_pct"] < 0 else "equal"
            reasons.append(f"{d['label']}: {d['value_fmt']}, {word} {abs(d['delta_pct']):.1f}% vs best of last {d['n']}")
        for d in deltas:
            if d["value"] and d.get("all_time_best") and d["value"] > d["all_time_best"]:
                reasons.append(f"New personal record: {d['label']} {d['value']:.1f} kg e1RM")
        confidence = "high" if len(judged) >= 3 else "medium"
        return self._result(session, verdict, confidence, score, headline, reasons, deltas, context, trend,
                            sorted(used_ids))


class GenericModel(SportModel):
    sport = "other"

    def load_only_reason(self, session):
        return "No sport-specific performance model — counted towards training load and recovery."


MODELS: dict[str, SportModel] = {
    "running": RunningModel(), "cycling": CyclingModel(), "swimming": SwimmingModel(),
    "strength": StrengthModel(), "other": GenericModel(),
}


def model_for(sport: str) -> SportModel:
    return MODELS.get(sport, MODELS["other"])
