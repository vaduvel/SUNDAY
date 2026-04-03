"""Event Gate — SpikingJelly/SNN-inspired salience filter.

Not every event deserves a full replan.
Only HIGH-SALIENCE events trigger expensive reasoning.

Key insight from Spiking Neural Networks:
  neurons fire only when input crosses a threshold.
  Same here: Jarvis replans only when an event is salient enough.

Inspired by: SpikingJelly, snnTorch
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# ── Salience rules ────────────────────────────────────────────────

# (field, value_or_callable) → salience score contribution
SALIENCE_RULES: list[tuple] = [
    # Failures and errors → very salient
    ("status", "failure",      0.7),
    ("status", "tool_error",   0.8),
    ("status", "timeout",      0.6),
    ("status", "blocked",      0.7),

    # Risk escalation → very salient
    ("risk_level", "high",     0.8),
    ("risk_level", "critical", 1.0),

    # Anomaly detected → salient
    ("anomaly_score", None,    None),   # handled dynamically

    # Successful completion → moderate (still worth noting)
    ("status", "success",      0.3),
    ("status", "partial",      0.4),

    # Routine updates → low salience
    ("status", "running",      0.05),
    ("status", "progress",     0.05),
]

# anomaly_score threshold → extra salience
ANOMALY_THRESHOLD = 0.6

# Default fire threshold
DEFAULT_THRESHOLD = 0.45


@dataclass
class GateDecision:
    should_fire: bool
    salience: float
    reasons: list[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "should_fire": self.should_fire,
            "salience": round(self.salience, 3),
            "reasons": self.reasons,
        }


class EventGate:
    """
    Decides whether an event is salient enough to trigger replanning.

    Usage:
        gate = EventGate()
        decision = gate.evaluate({"status": "failure", "tool": "browser"})
        if decision.should_fire:
            replan()
    """

    def __init__(self, threshold: float = DEFAULT_THRESHOLD):
        self.threshold = threshold
        self._recent_fires: list[float] = []   # timestamps of recent fires
        self._cooldown_sec = 2.0               # min seconds between fires
        self.total_events = 0
        self.total_fires = 0

    # ── public API ───────────────────────────────────────────────

    def evaluate(self, event: dict[str, Any]) -> GateDecision:
        """Score event salience and decide whether to fire."""
        self.total_events += 1
        salience, reasons = self._score(event)

        # cooldown: prevent rapid-fire replanning
        now = time.time()
        in_cooldown = (
            self._recent_fires
            and (now - self._recent_fires[-1]) < self._cooldown_sec
        )

        if in_cooldown and salience < 0.85:
            # only break cooldown for very high salience
            return GateDecision(
                should_fire=False,
                salience=salience,
                reasons=reasons + ["cooldown_suppressed"],
            )

        should_fire = salience >= self.threshold
        if should_fire:
            self._recent_fires.append(now)
            self._recent_fires = self._recent_fires[-20:]  # keep last 20
            self.total_fires += 1

        return GateDecision(should_fire=should_fire, salience=salience, reasons=reasons)

    def should_fire(self, event: dict[str, Any]) -> bool:
        """Simple boolean check."""
        return self.evaluate(event).should_fire

    def salience(self, event: dict[str, Any]) -> float:
        """Return raw salience score 0.0–1.0."""
        score, _ = self._score(event)
        return score

    def fire_rate(self) -> float:
        """Fraction of events that triggered replanning."""
        if self.total_events == 0:
            return 0.0
        return self.total_fires / self.total_events

    def stats(self) -> dict:
        return {
            "threshold": self.threshold,
            "total_events": self.total_events,
            "total_fires": self.total_fires,
            "fire_rate": round(self.fire_rate(), 3),
        }

    # ── scoring ──────────────────────────────────────────────────

    def _score(self, event: dict[str, Any]) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        for rule in SALIENCE_RULES:
            field_name, expected_val, contribution = rule

            if field_name == "anomaly_score":
                # dynamic: use the actual anomaly_score value
                anomaly = float(event.get("anomaly_score", 0.0))
                if anomaly >= ANOMALY_THRESHOLD:
                    extra = (anomaly - ANOMALY_THRESHOLD) * 1.5
                    score += min(0.5, extra)
                    reasons.append(f"anomaly={anomaly:.2f}")
                continue

            if event.get(field_name) == expected_val:
                score += contribution
                reasons.append(f"{field_name}={expected_val}")

        # extra boost from explicit retry_count
        retry = int(event.get("retry_count", 0))
        if retry >= 2:
            boost = min(0.3, retry * 0.1)
            score += boost
            reasons.append(f"retry_count={retry}")

        # clamp to [0, 1]
        score = min(1.0, max(0.0, score))
        return round(score, 3), reasons
