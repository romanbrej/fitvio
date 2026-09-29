"""Shared verdict machinery: similar-session baseline, robust comparison, reasons.

A sport model declares which metrics matter and how to find comparable sessions;
this base class does the statistics and produces the verdict dict stored in `verdicts`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Callable

from ..analytics import load as load_model
from ..analytics import physio

MIN_SIMILAR = 3
WINDOWS_DAYS = (56, 84, 120)
SCORE_THRESHOLD = 0.6


@dataclass
class MetricSpec:
    key: str
    label: str
    better: int                  # +1 higher is better, -1 lower is better
    weight: float
    fmt: Callable[[float], str]
    mode: str = "rel"            # rel: compare in %, abs: compare in the metric's own unit
    noise: float = 0.015         # minimum spread (fraction for rel, units for abs)
    get: Callable[[dict], float | None] | None = None

    def value(self, session: dict) -> float | None:
        f = session.get("features") or {}
        return self.get(f) if self.get else f.get(self.key)


SPORT_NOUN = {"running": "runs", "cycling": "rides", "swimming": "swims", "strength": "gym sessions", "other": "sessions"}


class SportModel:
    sport = "other"
    metrics: list[MetricSpec] = []
    primary: str | None = None  # metric key used for the 6-week trend

    # --- hooks -----------------------------------------------------------
    def load_only_reason(self, session: dict) -> str | None:
        """Return a reason if this session can only be judged by load (no performance model)."""
        return None

    def is_similar(self, session: dict, other: dict) -> bool:
        if other["session_type"] != session["session_type"]:
            return False
        if session.get("duration_s") and other.get("duration_s"):
            ratio = other["duration_s"] / session["duration_s"]
            if not 0.5 <= ratio <= 2.0:
                return False
        return True

    def trend_eligible(self, session: dict) -> bool:
        return session["session_type"] not in {"intervals", "race"}

    # --- main ------------------------------------------------------------
    def evaluate(self, session: dict, history: list[dict], health: dict | None, health_base: dict | None) -> dict:
        """history: all sessions of this user (any sport) that started before `session`."""
        same_sport = [h for h in history if h["sport"] == session["sport"]]
        trend = load_model.impact_of(session, history + [session])
        trend.update(self.efficiency_trend(session, same_sport))
        context = self.context_notes(session, health, health_base, trend)

        lo = self.load_only_reason(session)
        if lo:
            return self._result(session, "load_only", "low", None, f"Logged — training load {session.get('load') or 0:.0f}",
                                [lo], [], context, trend, [])

        similar = self.find_similar(session, same_sport)
        if len(similar) < MIN_SIMILAR:
            noun = f"{session['session_type']} {SPORT_NOUN[self.sport]}"
            return self._result(session, "not_comparable", "low", None,
                                f"Not comparable yet — {len(similar)} similar {noun} so far",
                                [f"Need at least {MIN_SIMILAR} similar {noun} in the last {WINDOWS_DAYS[-1]} days to judge."],
                                [], context, trend, [s["id"] for s in similar])

        deltas = self.compare(session, similar)
        used = [d for d in deltas if d["z"] is not None]
        if not used:
            return self._result(session, "not_comparable", "low", None, "Not enough data in this session to compare",
                                ["The key metrics could not be computed (missing HR, pace or power data)."],
                                deltas, context, trend, [s["id"] for s in similar])
        wsum = sum(d["weight"] for d in used)
        score = sum(d["weight"] * d["z"] for d in used) / wsum
        verdict = "better" if score > SCORE_THRESHOLD else "worse" if score < -SCORE_THRESHOLD else "in_line"
        confidence = "high" if len(similar) >= 6 and wsum >= 0.7 else "medium"
        noun = f"{session['session_type']} {SPORT_NOUN[self.sport]}"
        headline = {"better": f"Better than your recent {noun}",
                    "worse": f"Below your recent {noun}",
                    "in_line": f"In line with your recent {noun}"}[verdict]
        reasons = self.reasons(deltas, len(similar), noun)
        reasons += self.extra_reasons(session, same_sport)
        return self._result(session, verdict, confidence, score, headline, reasons, deltas, context, trend,
                            [s["id"] for s in similar])

    def find_similar(self, session: dict, same_sport: list[dict]) -> list[dict]:
        start = datetime.fromisoformat(session["start_time"])
        cands = [h for h in same_sport if self.is_similar(session, h)]
        for days in WINDOWS_DAYS:
            lo = start - timedelta(days=days)
            win = [h for h in cands if lo <= datetime.fromisoformat(h["start_time"]) < start]
            if len(win) >= MIN_SIMILAR:
                return sorted(win, key=lambda h: h["start_time"], reverse=True)[:12]
        return [h for h in cands if datetime.fromisoformat(h["start_time"]) < start]

    def compare(self, session: dict, similar: list[dict]) -> list[dict]:
        out = []
        for m in self.metrics:
            v = m.value(session)
            base_vals = [x for x in (m.value(s) for s in similar) if x is not None]
            row = {"key": m.key, "label": m.label, "value": v, "baseline": None, "delta": None,
                   "delta_pct": None, "z": None, "weight": m.weight, "better": m.better, "n": len(base_vals),
                   "value_fmt": m.fmt(v) if v is not None else "—", "baseline_fmt": "—"}
            if v is not None and len(base_vals) >= MIN_SIMILAR:
                med = median(base_vals)
                spread_raw = 1.4826 * physio.mad(base_vals)
                if m.mode == "rel" and med:
                    delta = (v - med) / abs(med)
                    spread = max(m.noise, spread_raw / abs(med))
                else:
                    delta = v - med
                    spread = max(m.noise, spread_raw)
                z = max(-3.0, min(3.0, m.better * delta / spread))
                pct = round((v - med) / abs(med) * 100, 1) if med else None
                if m.mode == "rel" and pct is not None:
                    dfmt = f"{'+' if pct > 0 else '−' if pct < 0 else '±'}{abs(pct):.1f}%"
                else:
                    dfmt = f"{'+' if v > med else '−' if v < med else '±'}{m.fmt(abs(v - med))}"
                row.update({"baseline": med, "delta": v - med, "z": round(z, 2), "baseline_fmt": m.fmt(med),
                            "delta_pct": pct, "delta_fmt": dfmt})
            out.append(row)
        return out

    def reasons(self, deltas: list[dict], n: int, noun: str) -> list[str]:
        ranked = sorted((d for d in deltas if d["z"] is not None), key=lambda d: -abs(d["z"] * d["weight"]))
        out = []
        for d in ranked[:3]:
            if abs(d["z"]) < SCORE_THRESHOLD:
                out.append(f"{d['label']} in line with your {n} similar {noun} ({d['value_fmt']} vs {d['baseline_fmt']})")
                continue
            word = "better" if d["z"] > 0 else "worse"
            if d["delta_pct"] is not None and self._metric(d["key"]).mode == "rel":
                size = f"{abs(d['delta_pct']):.1f}%"
            else:
                size = self._metric(d["key"]).fmt(abs(d["delta"]))
            out.append(f"{d['label']} {size} {word} than your {n} similar {noun} ({d['value_fmt']} vs {d['baseline_fmt']})")
        return out

    def extra_reasons(self, session: dict, same_sport: list[dict]) -> list[str]:
        return []

    def efficiency_trend(self, session: dict, same_sport: list[dict]) -> dict:
        if not self.primary:
            return {}
        m = self._metric(self.primary)
        start = datetime.fromisoformat(session["start_time"])
        lo = start - timedelta(days=42)
        pts = []
        for s in same_sport + [session]:
            t = datetime.fromisoformat(s["start_time"])
            v = m.value(s)
            if lo <= t <= start and v is not None and self.trend_eligible(s):
                pts.append(((t - lo).total_seconds() / 86400, v, s["start_time"][:10]))
        pts.sort()
        slope = physio.linear_slope([p[0] for p in pts], [p[1] for p in pts]) if len(pts) >= 4 else None
        mean = sum(p[1] for p in pts) / len(pts) if pts else None
        pct_week = slope * 7 / abs(mean) * 100 * m.better if slope is not None and mean else None
        return {"trend_metric": m.label, "trend_pct_per_week": round(pct_week, 2) if pct_week is not None else None,
                "trend_points": [{"day": p[2], "value": round(p[1], 4)} for p in pts]}

    def context_notes(self, session: dict, health: dict | None, health_base: dict | None, trend: dict) -> list[dict]:
        notes = []
        f = session.get("features") or {}
        heat, w = f.get("heat_adj_pct") or 0, f.get("weather") or {}
        if heat > 0 and w.get("temp_c") is not None:
            text = f"Warm & humid: {w['temp_c']:.0f} °C"
            if w.get("dew_point_c") is not None:
                text += f", dew point {w['dew_point_c']:.0f} °C"
            if w.get("station"):
                text += f" ({w['station']})"
            text += f" — efficiency adjusted +{heat:.1f} %"
            if f.get("heat_acclimation") is not None:
                text += f"; heat acclimation {f['heat_acclimation']:.0f} %"
            notes.append({"kind": "heat", "text": text})
        if session.get("ascent_m") and session.get("distance_m") and self.sport == "running":
            per_km = session["ascent_m"] / (session["distance_m"] / 1000)
            if per_km >= 15:
                notes.append({"kind": "hills", "text": f"Hilly: {session['ascent_m']:.0f} m climbing, pace grade-adjusted"})
        if health:
            sl = health.get("sleep_total_min")
            if sl and sl < 360:
                notes.append({"kind": "sleep", "text": f"Short sleep last night: {int(sl // 60)}h{int(sl % 60):02d}"})
            hrv, low = health.get("hrv_last_night"), health.get("hrv_baseline_low")
            if hrv and low and hrv < low:
                notes.append({"kind": "hrv", "text": f"HRV below your baseline ({hrv:.0f} ms < {low:.0f} ms)"})
            rhr = health.get("rhr")
            if rhr and health_base and health_base.get("rhr") and rhr >= health_base["rhr"] + 5:
                notes.append({"kind": "rhr", "text": f"Resting HR elevated ({rhr:.0f} vs {health_base['rhr']:.0f} usual)"})
        if trend.get("form_today") is not None and trend["form_today"] < -20:
            notes.append({"kind": "fatigue", "text": f"Carrying fatigue: form {trend['form_today']:.0f}"})
        if session.get("rpe"):
            notes.append({"kind": "rpe", "text": f"You rated effort {session['rpe']:.0f}/10"})
        return notes

    def _metric(self, key: str) -> MetricSpec:
        return next(m for m in self.metrics if m.key == key)

    @staticmethod
    def _result(session, verdict, confidence, score, headline, reasons, deltas, context, trend, baseline_ids) -> dict:
        return {
            "session_id": session["id"], "user_id": session["user_id"], "verdict": verdict,
            "confidence": confidence, "score": round(score, 2) if score is not None else None,
            "headline": headline, "reasons": reasons, "deltas": deltas, "context": context,
            "trend": trend, "baseline_ids": baseline_ids,
        }
