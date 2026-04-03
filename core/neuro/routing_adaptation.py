"""Routing Adapter — BindsNET-inspired reinforcement-flavored tool routing.

Learns which tool/executor wins in which context.
Updates scores only from VERIFIED mission outcomes.

Inspired by: BindsNET (biologically-inspired ML + RL)
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


# ── Score record per (context_class, tool) ───────────────────────

@dataclass
class RouteScore:
    tool: str
    context_class: str
    wins: int = 0
    losses: int = 0
    total: int = 0
    last_used: float = field(default_factory=time.time)

    @property
    def win_rate(self) -> float:
        if self.total == 0:
            return 0.5   # optimistic prior
        return self.wins / self.total

    @property
    def confidence(self) -> float:
        """Wilson score lower bound — penalizes low sample count."""
        n = self.total
        if n == 0:
            return 0.3
        p = self.win_rate
        z = 1.645   # 95% confidence
        denom = 1 + z**2 / n
        centre = p + z**2 / (2 * n)
        margin = z * (p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5
        return max(0.0, min(1.0, (centre - margin) / denom))

    def as_dict(self) -> dict:
        return {
            "tool": self.tool,
            "context_class": self.context_class,
            "win_rate": round(self.win_rate, 3),
            "confidence": round(self.confidence, 3),
            "total": self.total,
        }


# ── Context classifier ────────────────────────────────────────────

CONTEXT_KEYWORDS: dict[str, list[str]] = {
    "web_research":   ["search", "browse", "web", "url", "scrape", "fetch"],
    "code_execution": ["code", "python", "script", "run", "execute", "test", "build"],
    "file_ops":       ["file", "read", "write", "directory", "path", "disk"],
    "desktop_control":["click", "mouse", "keyboard", "window", "app", "desktop"],
    "memory_ops":     ["remember", "recall", "memory", "history", "learn"],
    "research":       ["research", "analyze", "synthesize", "report", "summarize"],
    "planning":       ["plan", "task", "mission", "goal", "step", "schedule"],
}


def classify_context(mission_text: str) -> str:
    text = mission_text.lower()
    scores: dict[str, int] = defaultdict(int)
    for ctx, keywords in CONTEXT_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[ctx] += 1
    if not scores:
        return "general"
    return max(scores, key=lambda k: scores[k])


# ── Main class ───────────────────────────────────────────────────

class RoutingAdapter:
    """
    Adaptive tool router that learns from outcomes.

    Usage:
        router = RoutingAdapter()

        # get best tool for this context
        best = router.best_route("web_research", ["browser_agent", "playwright", "search_tool"])

        # after mission verified:
        router.reward("web_research", "browser_agent", success=True)
        router.reward("web_research", "playwright", success=False)
    """

    KNOWN_TOOLS = [
        "browser_agent",
        "browser_navigator",
        "stagehand_browser",
        "search_tool",
        "file_manager",
        "coding_agent",
        "desktop_control",
        "computer_use_agent",
        "research_agent",
        "memory_tool",
    ]

    def __init__(self, path: str = ".agent/neuro/routing.json"):
        self.path = path
        # scores[(context_class, tool)] = RouteScore
        self.scores: dict[str, RouteScore] = {}
        self._load()

    # ── public API ───────────────────────────────────────────────

    def best_route(
        self,
        context_class: str,
        candidates: list[str] | None = None,
    ) -> str:
        """Return the tool with highest confidence for this context."""
        tools = candidates or self.KNOWN_TOOLS
        scored = []
        for tool in tools:
            key = self._key(context_class, tool)
            score = self.scores.get(key)
            if score:
                scored.append((tool, score.confidence))
            else:
                scored.append((tool, 0.3))   # optimistic prior for unseen

        scored.sort(key=lambda x: -x[1])
        return scored[0][0] if scored else tools[0]

    def rank_routes(
        self,
        context_class: str,
        candidates: list[str] | None = None,
    ) -> list[dict]:
        """Return all tools ranked by confidence for this context."""
        tools = candidates or self.KNOWN_TOOLS
        results = []
        for tool in tools:
            key = self._key(context_class, tool)
            score = self.scores.get(key)
            if score:
                results.append(score.as_dict())
            else:
                results.append({
                    "tool": tool,
                    "context_class": context_class,
                    "win_rate": 0.5,
                    "confidence": 0.3,
                    "total": 0,
                })
        results.sort(key=lambda x: -x["confidence"])
        return results

    def reward(self, context_class: str, tool: str, success: bool) -> None:
        """Update scores after a VERIFIED outcome."""
        key = self._key(context_class, tool)
        if key not in self.scores:
            self.scores[key] = RouteScore(tool=tool, context_class=context_class)
        s = self.scores[key]
        s.total += 1
        s.last_used = time.time()
        if success:
            s.wins += 1
        else:
            s.losses += 1
        self._save()

    def reward_from_result(
        self,
        mission_text: str,
        tool_used: str,
        success: bool,
    ) -> None:
        """Classify context automatically then reward."""
        ctx = classify_context(mission_text)
        self.reward(ctx, tool_used, success)

    def summary(self) -> list[dict]:
        return sorted(
            [s.as_dict() for s in self.scores.values()],
            key=lambda x: -x["confidence"],
        )

    # ── persistence ──────────────────────────────────────────────

    def _key(self, context_class: str, tool: str) -> str:
        return f"{context_class}::{tool}"

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        data = {}
        for k, s in self.scores.items():
            data[k] = {
                "tool": s.tool,
                "context_class": s.context_class,
                "wins": s.wins,
                "losses": s.losses,
                "total": s.total,
                "last_used": s.last_used,
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
            for k, v in data.items():
                self.scores[k] = RouteScore(
                    tool=v["tool"],
                    context_class=v["context_class"],
                    wins=v["wins"],
                    losses=v["losses"],
                    total=v["total"],
                    last_used=v.get("last_used", time.time()),
                )
        except (json.JSONDecodeError, KeyError):
            pass
