"""Temporal Memory — HTM/NuPIC-inspired sequence learning.

Learns action sequences, predicts next steps, detects anomalies.
Pure Python, no external neuro deps. Serializable to JSON.

Inspired by: Numenta NuPIC Legacy (HTM — Hierarchical Temporal Memory)
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Any


# ── Data structures ──────────────────────────────────────────────

@dataclass
class Event:
    tool: str           # e.g. "browser_agent", "file_manager"
    action: str         # e.g. "search", "write", "execute"
    outcome: str        # "success" | "failure" | "partial"
    mission_type: str   # "code", "research", "design", ...
    ts: float = field(default_factory=time.time)

    def key(self) -> str:
        return f"{self.tool}:{self.action}:{self.outcome}"


@dataclass
class SequenceNode:
    key: str
    count: int = 0
    successors: dict[str, int] = field(default_factory=dict)   # key → count
    anomaly_baseline: float = 0.0  # rolling avg surprise

    def top_successors(self, k: int = 3) -> list[tuple[str, float]]:
        total = sum(self.successors.values()) or 1
        ranked = sorted(self.successors.items(), key=lambda x: -x[1])
        return [(k, v / total) for k, v in ranked[:k]]


# ── Main class ───────────────────────────────────────────────────

class TemporalMemory:
    """
    Lightweight HTM-inspired temporal predictor.

    Usage:
        tm = TemporalMemory()
        tm.observe({"tool": "browser_agent", "action": "search",
                    "outcome": "success", "mission_type": "research"})
        predictions = tm.predict_next({"mission_type": "research"}, top_k=3)
        score = tm.anomaly_score({"tool": "file_manager", "action": "delete",
                                  "outcome": "failure", "mission_type": "research"})
    """

    WINDOW = 3          # how many past events form a context
    DECAY = 0.95        # exponential decay for anomaly baseline
    MAX_NODES = 2000    # memory cap

    def __init__(self, path: str = ".agent/neuro/temporal.json"):
        self.path = path
        self.nodes: dict[str, SequenceNode] = {}
        self.recent: deque[str] = deque(maxlen=self.WINDOW)
        self.event_count: int = 0
        self._load()

    # ── public API ───────────────────────────────────────────────

    def observe(self, event: dict[str, Any]) -> None:
        """Record an event and update sequence statistics."""
        ev = Event(**{k: event.get(k, "unknown") for k in
                      ("tool", "action", "outcome", "mission_type")})
        key = ev.key()
        self.event_count += 1

        # update or create node
        node = self.nodes.setdefault(key, SequenceNode(key=key))
        node.count += 1

        # update predecessor → successor links
        if self.recent:
            prev_key = self.recent[-1]
            prev_node = self.nodes.setdefault(prev_key, SequenceNode(key=prev_key))
            prev_node.successors[key] = prev_node.successors.get(key, 0) + 1

        self.recent.append(key)

        # prune if needed
        if len(self.nodes) > self.MAX_NODES:
            self._prune()

        self._save()

    def predict_next(self, context: dict[str, Any], top_k: int = 3) -> list[dict]:
        """Return top_k likely next events given current context."""
        if not self.recent:
            return []

        last_key = self.recent[-1]
        node = self.nodes.get(last_key)
        if not node or not node.successors:
            return []

        results = []
        for successor_key, prob in node.top_successors(top_k):
            parts = successor_key.split(":")
            if len(parts) == 3:
                tool, action, outcome = parts
                results.append({
                    "tool": tool,
                    "action": action,
                    "expected_outcome": outcome,
                    "confidence": round(prob, 3),
                })
        return results

    def anomaly_score(self, event: dict[str, Any]) -> float:
        """
        0.0 = totally expected
        1.0 = never seen before / highly surprising
        """
        ev = Event(**{k: event.get(k, "unknown") for k in
                      ("tool", "action", "outcome", "mission_type")})
        key = ev.key()

        if not self.recent:
            return 0.5   # no history → neutral

        last_key = self.recent[-1]
        prev_node = self.nodes.get(last_key)
        if not prev_node or not prev_node.successors:
            return 0.6   # no successor data → slightly surprising

        total = sum(prev_node.successors.values())
        seen = prev_node.successors.get(key, 0)

        if total == 0:
            return 0.6

        prob = seen / total
        # surprise = -log(prob); normalize to [0,1] via sigmoid-like
        if prob == 0:
            return 1.0
        surprise = -math.log(prob + 1e-9)
        return round(min(1.0, surprise / 10.0), 3)

    def context_summary(self) -> list[str]:
        """Last N observed event keys (for debug / display)."""
        return list(self.recent)

    # ── persistence ──────────────────────────────────────────────

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        data = {
            "event_count": self.event_count,
            "recent": list(self.recent),
            "nodes": {
                k: {
                    "key": v.key,
                    "count": v.count,
                    "successors": v.successors,
                    "anomaly_baseline": v.anomaly_baseline,
                }
                for k, v in self.nodes.items()
            },
        }
        try:
            with open(self.path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            self.event_count = data.get("event_count", 0)
            self.recent = deque(data.get("recent", []), maxlen=self.WINDOW)
            for k, v in data.get("nodes", {}).items():
                self.nodes[k] = SequenceNode(
                    key=v["key"],
                    count=v["count"],
                    successors=v["successors"],
                    anomaly_baseline=v.get("anomaly_baseline", 0.0),
                )
        except (json.JSONDecodeError, KeyError):
            pass

    def _prune(self) -> None:
        """Remove least-used nodes when over cap."""
        sorted_keys = sorted(self.nodes, key=lambda k: self.nodes[k].count)
        for k in sorted_keys[: len(self.nodes) - self.MAX_NODES + 200]:
            del self.nodes[k]
