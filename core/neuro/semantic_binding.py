"""Semantic Binder — Nengo-SPA-inspired compositional memory.

Encodes mission context as high-dimensional vectors.
Enables compact structured working memory instead of raw prompt bloat.

Key idea from Semantic Pointer Architecture (SPA):
  - every concept = a vector
  - binding = element-wise circular convolution → creates "role + filler" memory
  - query = deconvolution → retrieve specific role from composite

We use a simplified pseudo-SPA with hash-based vectors (no heavy math deps).

Inspired by: Nengo, Nengo-SPA
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass, field
from typing import Any


# ── Vector utilities ──────────────────────────────────────────────

DIM = 256   # vector dimensionality


def _text_to_vector(text: str, dim: int = DIM) -> list[float]:
    """
    Deterministic pseudo-random unit vector from text.
    Same text → same vector. Different texts → near-orthogonal vectors.
    """
    seed = hashlib.sha256(text.lower().encode()).digest()
    values: list[float] = []
    # expand seed until we have dim floats
    block = seed
    while len(values) < dim:
        for i in range(0, len(block) - 3, 4):
            v = struct.unpack_from(">f", block, i)[0]
            if math.isfinite(v):
                values.append(v)
        block = hashlib.sha256(block).digest()
    values = values[:dim]
    # normalize to unit vector
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _add_vectors(vecs: list[list[float]]) -> list[float]:
    if not vecs:
        return [0.0] * DIM
    result = [0.0] * len(vecs[0])
    for v in vecs:
        for i, x in enumerate(v):
            result[i] += x
    # normalize
    norm = math.sqrt(sum(x * x for x in result)) or 1.0
    return [x / norm for x in result]


# ── Role-filler binding ───────────────────────────────────────────

KNOWN_ROLES = [
    "goal", "agent", "app", "tool", "risk",
    "deadline", "entity", "constraint", "evidence",
    "mission_type", "permission_mode",
]


@dataclass
class BoundMemory:
    """A composite semantic memory for one mission."""
    mission_id: str
    bindings: dict[str, list[float]] = field(default_factory=dict)  # role → vector
    raw_fillers: dict[str, str] = field(default_factory=dict)        # role → text
    composite: list[float] = field(default_factory=lambda: [0.0] * DIM)

    def as_summary(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "roles": {role: filler for role, filler in self.raw_fillers.items()},
        }


# ── Main class ───────────────────────────────────────────────────

class SemanticBinder:
    """
    Compositional mission memory using semantic vector binding.

    Usage:
        binder = SemanticBinder()

        # encode a mission context
        mem = binder.encode_mission("mission_123", {
            "goal": "find security vulnerability in auth module",
            "app": "CompliAI",
            "tool": "browser_agent",
            "risk": "high",
            "mission_type": "research",
        })

        # retrieve a specific role
        goal_text = binder.query_role(mem, "goal")

        # find similar past missions
        similar = binder.find_similar(mem, past_memories, top_k=3)
    """

    def __init__(self):
        # role vectors (stable, derived from role name)
        self._role_vectors: dict[str, list[float]] = {
            role: _text_to_vector(f"__ROLE__{role}__")
            for role in KNOWN_ROLES
        }

    # ── encoding ─────────────────────────────────────────────────

    def encode_mission(
        self,
        mission_id: str,
        context: dict[str, Any],
    ) -> BoundMemory:
        """
        Encode mission context into a compositional semantic memory.
        Each role-filler pair becomes a bound vector; all are summed.
        """
        mem = BoundMemory(mission_id=mission_id)
        bound_vectors: list[list[float]] = []

        for role in KNOWN_ROLES:
            filler = context.get(role)
            if not filler:
                continue
            filler_str = str(filler)
            mem.raw_fillers[role] = filler_str

            role_vec = self._role_vectors[role]
            filler_vec = _text_to_vector(filler_str)
            # binding = element-wise product (simplified circular convolution)
            bound = [r * f for r, f in zip(role_vec, filler_vec)]
            mem.bindings[role] = bound
            bound_vectors.append(bound)

        if bound_vectors:
            mem.composite = _add_vectors(bound_vectors)

        return mem

    def query_role(self, mem: BoundMemory, role: str) -> str:
        """
        Retrieve the filler for a given role from memory.
        Returns the raw stored text (for simplicity, no deconvolution needed).
        """
        return mem.raw_fillers.get(role, "")

    def similarity(self, a: BoundMemory, b: BoundMemory) -> float:
        """Cosine similarity between two mission memories."""
        return round(_dot(a.composite, b.composite), 4)

    def find_similar(
        self,
        query: BoundMemory,
        memories: list[BoundMemory],
        top_k: int = 3,
        min_score: float = 0.1,
    ) -> list[dict]:
        """Return top-k most similar past memories."""
        scored = []
        for mem in memories:
            if mem.mission_id == query.mission_id:
                continue
            score = self.similarity(query, mem)
            if score >= min_score:
                scored.append({
                    "mission_id": mem.mission_id,
                    "similarity": score,
                    "context": mem.as_summary()["roles"],
                })
        scored.sort(key=lambda x: -x["similarity"])
        return scored[:top_k]

    def encode_goal(self, goal_text: str) -> list[float]:
        """Encode a standalone goal string as a vector."""
        return _text_to_vector(goal_text)

    def encode_context(self, ctx: dict[str, Any]) -> list[float]:
        """Encode an arbitrary context dict as a composite vector."""
        vecs = [_text_to_vector(f"{k}:{v}") for k, v in ctx.items() if v]
        return _add_vectors(vecs) if vecs else [0.0] * DIM

    def context_similarity(self, a: dict, b: dict) -> float:
        """Compare two context dicts semantically."""
        va = self.encode_context(a)
        vb = self.encode_context(b)
        return round(_dot(va, vb), 4)

    def compact_summary(self, mem: BoundMemory, max_roles: int = 5) -> str:
        """
        Generate a compact text summary of the mission memory.
        Replaces long raw context in prompts.
        """
        parts = []
        priority_roles = ["goal", "mission_type", "app", "risk", "tool"]
        for role in priority_roles:
            if role in mem.raw_fillers:
                parts.append(f"{role}={mem.raw_fillers[role]}")
        # add remaining roles up to max
        for role, filler in mem.raw_fillers.items():
            if role not in priority_roles and len(parts) < max_roles:
                parts.append(f"{role}={filler}")
        return " | ".join(parts)
