"""Belief State + Active Inference Planner — pymdp-inspired.

Jarvis maintains internal hypotheses about task state + uncertainty.
Chooses actions that REDUCE uncertainty, not just chase immediate reward.
Pure Python, no external deps.

Inspired by: pymdp (infer-actively/pymdp)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any


# ── Hypothesis about task state ──────────────────────────────────

@dataclass
class Hypothesis:
    label: str              # e.g. "task_complete", "blocked", "partial_success"
    confidence: float       # 0.0 → 1.0
    evidence: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence[-5:],   # last 5 evidence items
        }


# ── Belief State ─────────────────────────────────────────────────

class BeliefState:
    """
    Tracks what Jarvis believes about the current task state.

    Core idea from Active Inference / pymdp:
      - maintain a distribution over hidden states
      - update beliefs from observations
      - choose actions that minimize expected free energy (= reduce uncertainty)

    Usage:
        belief = BeliefState()
        belief.update_from_observation({"status": "tool_error", "tool": "browser"})
        print(belief.entropy())          # how uncertain we are
        print(belief.best_hypothesis())  # most likely state
    """

    DEFAULT_HYPOTHESES = [
        "task_in_progress",
        "task_complete",
        "task_blocked",
        "partial_success",
        "tool_failure",
        "needs_clarification",
        "context_missing",
    ]

    OBSERVATION_SIGNALS = {
        # observation key:value → (hypothesis_label, delta_confidence)
        ("status", "success"):          [("task_complete", +0.4), ("task_in_progress", -0.2)],
        ("status", "failure"):          [("task_blocked", +0.3), ("tool_failure", +0.2)],
        ("status", "partial"):          [("partial_success", +0.3), ("task_in_progress", +0.1)],
        ("status", "tool_error"):       [("tool_failure", +0.4), ("task_blocked", +0.2)],
        ("status", "running"):          [("task_in_progress", +0.2)],
        ("status", "timeout"):          [("task_blocked", +0.4), ("tool_failure", +0.2)],
        ("clarification_needed", True): [("needs_clarification", +0.5)],
        ("context_empty", True):        [("context_missing", +0.4)],
        ("retry_count_high", True):     [("task_blocked", +0.3), ("tool_failure", +0.2)],
        ("verification_passed", True):  [("task_complete", +0.5), ("partial_success", -0.2)],
        ("verification_failed", True):  [("task_complete", -0.4), ("partial_success", +0.3)],
    }

    def __init__(self):
        self.hypotheses: dict[str, Hypothesis] = {
            label: Hypothesis(label=label, confidence=1.0 / len(self.DEFAULT_HYPOTHESES))
            for label in self.DEFAULT_HYPOTHESES
        }
        self.observation_log: list[dict] = []
        self.step: int = 0

    # ── public API ───────────────────────────────────────────────

    def update_from_observation(self, obs: dict[str, Any]) -> None:
        """Update beliefs based on a new observation dict."""
        self.step += 1
        self.observation_log.append({"step": self.step, "obs": obs})

        for (key, val), updates in self.OBSERVATION_SIGNALS.items():
            if obs.get(key) == val:
                for label, delta in updates:
                    if label in self.hypotheses:
                        h = self.hypotheses[label]
                        h.confidence = max(0.0, min(1.0, h.confidence + delta))
                        h.evidence.append(f"step{self.step}:{key}={val}")
                        h.updated_at = time.time()

        self._normalize()

    def entropy(self) -> float:
        """Shannon entropy of belief distribution. High = uncertain."""
        confs = [h.confidence for h in self.hypotheses.values() if h.confidence > 0]
        if not confs:
            return 1.0
        return -sum(p * math.log(p + 1e-9) for p in confs)

    def best_hypothesis(self) -> dict:
        """Return the most confident hypothesis."""
        best = max(self.hypotheses.values(), key=lambda h: h.confidence)
        return best.as_dict()

    def is_uncertain(self, threshold: float = 1.5) -> bool:
        """True if belief entropy is above threshold (Jarvis should clarify)."""
        return self.entropy() > threshold

    def is_done(self) -> bool:
        """True if task_complete hypothesis dominates."""
        return self.hypotheses["task_complete"].confidence > 0.6

    def is_blocked(self) -> bool:
        """True if blocked or tool_failure dominates."""
        return (
            self.hypotheses["task_blocked"].confidence > 0.5
            or self.hypotheses["tool_failure"].confidence > 0.5
        )

    def snapshot(self) -> dict:
        """Full belief snapshot for logging / serialization."""
        return {
            "step": self.step,
            "entropy": round(self.entropy(), 3),
            "hypotheses": {
                label: round(h.confidence, 3)
                for label, h in sorted(
                    self.hypotheses.items(), key=lambda x: -x[1].confidence
                )
            },
            "best": self.best_hypothesis(),
            "is_uncertain": self.is_uncertain(),
            "is_done": self.is_done(),
            "is_blocked": self.is_blocked(),
        }

    def reset(self) -> None:
        """Reset for a new mission."""
        uniform = 1.0 / len(self.DEFAULT_HYPOTHESES)
        for h in self.hypotheses.values():
            h.confidence = uniform
            h.evidence.clear()
        self.observation_log.clear()
        self.step = 0

    # ── internal ─────────────────────────────────────────────────

    def _normalize(self) -> None:
        total = sum(h.confidence for h in self.hypotheses.values())
        if total > 0:
            for h in self.hypotheses.values():
                h.confidence /= total


# ── Active Inference Planner ──────────────────────────────────────

class ActiveInferencePlanner:
    """
    Ranks candidate actions by expected free energy.

    Lower EFE = better action (reduces uncertainty + achieves goal).

    Usage:
        planner = ActiveInferencePlanner()
        belief = BeliefState()
        ranked = planner.rank_actions(belief, [
            {"name": "retry_tool", "risk": 0.2},
            {"name": "ask_clarification", "risk": 0.05},
            {"name": "switch_tool", "risk": 0.3},
        ])
    """

    def rank_actions(
        self,
        belief: BeliefState,
        actions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Score each action by EFE proxy:
          EFE ≈ risk + uncertainty_if_taken - expected_info_gain

        Lower score = prefer this action.
        """
        scored = []
        current_entropy = belief.entropy()

        for action in actions:
            risk = float(action.get("risk", 0.2))
            # info gain: clarification/verification actions reduce entropy more
            name = action.get("name", "")
            if any(k in name for k in ("clarif", "verify", "check", "confirm")):
                info_gain = 0.4
            elif any(k in name for k in ("retry", "switch", "repair")):
                info_gain = 0.2
            else:
                info_gain = 0.1

            residual_entropy = max(0.0, current_entropy - info_gain)
            efe = risk + residual_entropy - info_gain

            scored.append({
                **action,
                "efe_score": round(efe, 3),
                "info_gain": round(info_gain, 3),
                "residual_entropy": round(residual_entropy, 3),
            })

        # sort ascending — lowest EFE preferred
        scored.sort(key=lambda x: x["efe_score"])
        return scored
