"""Executable memory consolidation for J.A.R.V.I.S.

This module keeps the original 3-tier memory store, but also adds
blueprint-aligned executable memories that can bias planning and execution.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from core.task_contracts import PlanStep

MEMORY_DIR = ".jarvis/memory"


class MemoryTier(Enum):
    """Memory tier levels."""

    SHORT_TERM = "short"
    MEDIUM_TERM = "medium"
    LONG_TERM = "long"


@dataclass
class MemoryEntry:
    """A classic tiered memory entry."""

    id: str
    content: str
    tier: str
    created_at: str
    last_accessed: str
    access_count: int
    importance: float
    promoted_from: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutableMemory:
    """A memory that can change how the system executes future work."""

    memory_id: str
    type: str
    trigger_conditions: List[str]
    recommended_action: str
    confidence: float
    source: str
    ttl_hours: int
    created_at: str
    last_validated_at: str | None = None
    success_count: int = 0
    failure_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.ttl_hours <= 0:
            return False
        current = now or datetime.now()
        created = datetime.fromisoformat(self.created_at)
        return current > created + timedelta(hours=self.ttl_hours)


class MemoryConsolidation:
    """3-tier memory with automatic consolidation and executable biases."""

    EXECUTABLE_TYPE_PRIORITY = {
        "failure_avoidance_memory": 4,
        "tool_reliability_memory": 3,
        "strategy_memory": 2,
        "user_execution_preference_memory": 1,
    }

    def __init__(self, memory_dir: str = MEMORY_DIR):
        self.memory_dir = memory_dir
        self.memory_file = os.path.join(self.memory_dir, "consolidated_memory.json")
        self.memories: Dict[str, MemoryEntry] = {}
        self.executable_memories: Dict[str, ExecutableMemory] = {}

        self.promotion_thresholds = {
            "short_to_medium": {"access_count": 3, "days": 7},
            "medium_to_long": {"access_count": 5, "days": 30},
        }

        self._load_memories()

    def _load_memories(self) -> None:
        os.makedirs(self.memory_dir, exist_ok=True)
        if not os.path.exists(self.memory_file):
            return

        with open(self.memory_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        for mem in data.get("memories", []):
            self.memories[mem["id"]] = MemoryEntry(**mem)

        for mem in data.get("executable_memories", []):
            self.executable_memories[mem["memory_id"]] = ExecutableMemory(**mem)

    def _save_memories(self) -> None:
        with open(self.memory_file, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "memories": [memory.to_dict() for memory in self.memories.values()],
                    "executable_memories": [
                        memory.to_dict() for memory in self.executable_memories.values()
                    ],
                    "last_updated": datetime.now().isoformat(),
                },
                handle,
                indent=2,
            )

    def add_memory(
        self, content: str, tier: str = "short", importance: float = 50.0
    ) -> str:
        import uuid

        entry_id = f"mem_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        self.memories[entry_id] = MemoryEntry(
            id=entry_id,
            content=content,
            tier=tier,
            created_at=now,
            last_accessed=now,
            access_count=1,
            importance=importance,
        )
        self._save_memories()
        self._check_promotion(entry_id)
        return entry_id

    def add_executable_memory(
        self,
        memory_type: str,
        trigger_conditions: List[str],
        recommended_action: str,
        confidence: float,
        source: str,
        ttl_hours: int = 168,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        import uuid

        memory_id = f"exec_{uuid.uuid4().hex[:8]}"
        self.executable_memories[memory_id] = ExecutableMemory(
            memory_id=memory_id,
            type=memory_type,
            trigger_conditions=list(trigger_conditions),
            recommended_action=recommended_action,
            confidence=max(0.0, min(1.0, confidence)),
            source=source,
            ttl_hours=ttl_hours,
            created_at=datetime.now().isoformat(),
            metadata=dict(metadata or {}),
        )
        self._save_memories()
        return memory_id

    def access_memory(self, memory_id: str) -> Optional[MemoryEntry]:
        memory = self.memories.get(memory_id)
        if not memory:
            return None

        memory.last_accessed = datetime.now().isoformat()
        memory.access_count += 1
        self._save_memories()
        self._check_promotion(memory_id)
        return memory

    def search_memories(self, query: str, tier: str = None) -> List[MemoryEntry]:
        query_lower = query.lower()
        results = []
        for memory in self.memories.values():
            if tier and memory.tier != tier:
                continue
            if query_lower in memory.content.lower():
                results.append(memory)

        results.sort(key=lambda item: (item.importance, item.access_count), reverse=True)
        return results[:10]

    def get_execution_biases(self, task_ctx: Dict[str, Any]) -> List[ExecutableMemory]:
        """Return active executable memories relevant to the current task."""
        biases: List[ExecutableMemory] = []
        haystack = self._task_ctx_haystack(task_ctx)
        current = datetime.now()

        for memory in self.executable_memories.values():
            if memory.is_expired(current):
                continue
            if any(trigger.lower() in haystack for trigger in memory.trigger_conditions):
                biases.append(memory)

        biases.sort(
            key=lambda memory: (
                self.EXECUTABLE_TYPE_PRIORITY.get(memory.type, 0),
                memory.confidence,
                memory.last_validated_at or memory.created_at,
            ),
            reverse=True,
        )
        return biases

    def apply_memory_biases_to_plan(
        self, plan: List[PlanStep], memories: List[ExecutableMemory]
    ) -> List[PlanStep]:
        """Mutate a plan according to active executable memories."""
        for memory in memories:
            preferred_tools = self._extract_action_tools(memory.recommended_action, "prefer")
            avoided_tools = self._extract_action_tools(memory.recommended_action, "avoid")
            verification_boost = "verify" in memory.recommended_action.lower()

            for step in plan:
                step_text = " ".join([step.title, step.description, *step.tool_candidates]).lower()
                touches_tools = bool(
                    set(preferred_tools + avoided_tools) & set(step.tool_candidates)
                )
                touches_triggers = any(
                    trigger.lower() in step_text
                    or trigger.lower() in memory.recommended_action.lower()
                    for trigger in memory.trigger_conditions
                )
                if not (touches_tools or touches_triggers or verification_boost):
                    continue

                if preferred_tools:
                    ordered = [tool for tool in step.tool_candidates if tool in preferred_tools]
                    ordered += [
                        tool for tool in step.tool_candidates if tool not in preferred_tools
                    ]
                    if ordered:
                        step.tool_candidates = ordered

                if avoided_tools:
                    safe_tools = [
                        tool for tool in step.tool_candidates if tool not in avoided_tools
                    ]
                    unsafe_tools = [
                        tool for tool in step.tool_candidates if tool in avoided_tools
                    ]
                    if safe_tools:
                        step.tool_candidates = safe_tools + unsafe_tools

                if verification_boost:
                    step.max_retries = max(step.max_retries, 3)
                    if "memory_bias_applied" not in step.success_criteria.observable_signals:
                        step.success_criteria.observable_signals.append(
                            "memory_bias_applied"
                        )

                note = f"Memory bias: {memory.type} -> {memory.recommended_action}"
                if note not in step.description:
                    step.description = f"{step.description} [{note}]"

        return plan

    def validate_memory_effectiveness(
        self, memory_id: str, outcome: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        """Adjust executable memory confidence based on observed outcome."""
        memory = self.executable_memories.get(memory_id)
        if memory is None:
            return None

        success = bool(outcome.get("success") or outcome.get("verified"))
        if success:
            memory.success_count += 1
            memory.confidence = min(1.0, memory.confidence + 0.05)
        else:
            memory.failure_count += 1
            memory.confidence = max(0.05, memory.confidence - 0.1)

        memory.last_validated_at = datetime.now().isoformat()
        self._save_memories()
        return memory.to_dict()

    def confirm_memory(self, memory_id: str, importance: float = None) -> None:
        memory = self.memories.get(memory_id)
        if not memory:
            return
        if importance is not None:
            memory.importance = min(100.0, importance + 20)
        else:
            memory.importance = min(100.0, memory.importance + 30)
        self._save_memories()
        self._check_promotion(memory_id)

    def get_tier_counts(self) -> Dict[str, int]:
        counts = {"short": 0, "medium": 0, "long": 0}
        for memory in self.memories.values():
            counts[memory.tier] = counts.get(memory.tier, 0) + 1
        return counts

    def get_status(self) -> Dict[str, Any]:
        executable_counts: Dict[str, int] = {}
        active_biases = 0
        now = datetime.now()
        for memory in self.executable_memories.values():
            executable_counts[memory.type] = executable_counts.get(memory.type, 0) + 1
            if not memory.is_expired(now):
                active_biases += 1

        return {
            "active": True,
            "total_memories": len(self.memories),
            "tier_counts": self.get_tier_counts(),
            "promotion_thresholds": self.promotion_thresholds,
            "executable_memories_total": len(self.executable_memories),
            "executable_memory_types": executable_counts,
            "active_execution_biases": active_biases,
        }

    def get_tier_memories(self, tier: str, limit: int = 5) -> List[Dict[str, Any]]:
        memories = [memory for memory in self.memories.values() if memory.tier == tier]
        memories.sort(key=lambda item: item.last_accessed, reverse=True)
        return [
            {
                "id": memory.id,
                "content": memory.content[:100],
                "access_count": memory.access_count,
            }
            for memory in memories[:limit]
        ]

    def _task_ctx_haystack(self, task_ctx: Dict[str, Any]) -> str:
        parts: List[str] = []
        for key, value in task_ctx.items():
            if isinstance(value, str):
                parts.append(value.lower())
            elif isinstance(value, (list, tuple, set)):
                parts.extend(str(item).lower() for item in value)
            elif isinstance(value, dict):
                parts.extend(str(item).lower() for item in value.values())
        return " ".join(parts)

    def _extract_action_tools(self, text: str, verb: str) -> List[str]:
        pattern = rf"{verb}\s+([a-zA-Z0-9_]+)"
        return [match.lower() for match in re.findall(pattern, text.lower())]

    def _check_promotion(self, memory_id: str) -> None:
        memory = self.memories.get(memory_id)
        if not memory:
            return

        now = datetime.now()
        created = datetime.fromisoformat(memory.created_at)
        days_old = (now - created).days

        if memory.tier == MemoryTier.SHORT_TERM.value:
            if (
                memory.access_count
                >= self.promotion_thresholds["short_to_medium"]["access_count"]
                and days_old >= self.promotion_thresholds["short_to_medium"]["days"]
            ):
                self._promote(memory_id, MemoryTier.MEDIUM_TERM.value)

        elif memory.tier == MemoryTier.MEDIUM_TERM.value:
            if (
                memory.access_count
                >= self.promotion_thresholds["medium_to_long"]["access_count"]
                and days_old >= self.promotion_thresholds["medium_to_long"]["days"]
            ):
                self._promote(memory_id, MemoryTier.LONG_TERM.value)

    def _promote(self, memory_id: str, new_tier: str) -> None:
        memory = self.memories.get(memory_id)
        if not memory:
            return
        old_tier = memory.tier
        memory.tier = new_tier
        memory.promoted_from = old_tier
        self._save_memories()


_memory_consolidation: MemoryConsolidation | None = None


def get_memory_consolidation() -> MemoryConsolidation:
    global _memory_consolidation
    if _memory_consolidation is None:
        _memory_consolidation = MemoryConsolidation()
    return _memory_consolidation


if __name__ == "__main__":
    memory = get_memory_consolidation()
    print(memory.get_status())
