"""JARVIS Neuro Brain — 7 cognitive layers.

Inspired by:
  NuPIC    → TemporalMemory
  pymdp    → BeliefState, ActiveInferencePlanner
  Nengo-SPA→ SemanticBinder
  SpikingJelly → EventGate
  BindsNET → RoutingAdapter
  Lava     → AsyncTriggerGraph
  Hyperon  → MetaReasoner

No external neuro deps required. Pure Python, serializable, testable.
Usage: from core.neuro import get_neuro_brain
"""

from .temporal_memory import TemporalMemory
from .belief_state import BeliefState
from .event_gate import EventGate
from .routing_adaptation import RoutingAdapter
from .meta_reasoner import MetaReasoner
from .async_trigger_graph import AsyncTriggerGraph
from .semantic_binding import SemanticBinder

import os
import json
import logging

logger = logging.getLogger(__name__)

_neuro_brain: "NeuroBrain | None" = None


class NeuroBrain:
    """Unified access point for all 7 neuro cognitive layers."""

    def __init__(self, vault_path: str = ".agent/neuro"):
        os.makedirs(vault_path, exist_ok=True)
        self.vault = vault_path
        self.temporal = TemporalMemory(os.path.join(vault_path, "temporal.json"))
        self.belief = BeliefState()
        self.event_gate = EventGate()
        self.router = RoutingAdapter(os.path.join(vault_path, "routing.json"))
        self.meta = MetaReasoner(os.path.join(vault_path, "rules.json"))
        self.trigger_graph = AsyncTriggerGraph()
        self.binder = SemanticBinder()
        self.mode = os.getenv("JARVIS_NEURO_BRAIN", "on")  # off | shadow | on
        logger.info(f"[NeuroBrain] Initialized — mode={self.mode}")

    @property
    def active(self) -> bool:
        return self.mode == "on"

    @property
    def shadow(self) -> bool:
        return self.mode in ("on", "shadow")

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "temporal_events": self.temporal.event_count,
            "belief_entropy": round(self.belief.entropy(), 3),
            "rules": len(self.meta.rules),
            "routes_tracked": len(self.router.scores),
        }


def get_neuro_brain(vault_path: str = ".agent/neuro") -> NeuroBrain:
    global _neuro_brain
    if _neuro_brain is None:
        _neuro_brain = NeuroBrain(vault_path)
    return _neuro_brain
