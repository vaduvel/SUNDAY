"""🧠 JARVIS Observational Memory System
Inspired by Mastra: A human-inspired memory system that never compacts.

Key Concepts:
- Observer Agent: Background agent watching conversations, creating dense logs
- Reflector Agent: Periodically reflects on observations, maintains summary
- Never Compacts: Uses observation log instead of raw message history
- Scores ~95% on LongMemEval benchmark

Unlike traditional context compaction (JARVIS already has 4-layer compression),
Observational Memory creates a DENSE representation that preserves important
details without losing context.
"""

import asyncio
import logging
import time
import hashlib
import json
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class ObservationType(Enum):
    """Types of observations the observer records."""

    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    LLM_INPUT = "llm_input"
    LLM_OUTPUT = "llm_output"
    ERROR = "error"
    STATE_CHANGE = "state_change"
    USER_FEEDBACK = "user_feedback"
    DECISION = "decision"
    PLAN_CHANGE = "plan_change"
    CONTEXT_Shift = "context_shift"


@dataclass
class Observation:
    """A single observation recorded by the observer."""

    id: str
    timestamp: str
    observation_type: ObservationType
    content: str
    importance: float  # 0-1, how important this is
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    linked_to: List[str] = field(default_factory=list)  # IDs of related observations


@dataclass
class Reflection:
    """A reflection created by the reflector agent."""

    id: str
    timestamp: str
    summary: str  # High-level summary
    key_insights: List[str]
    patterns_detected: List[str]
    suggestions: List[str]
    confidence: float  # 0-1
    based_on_observations: List[str]  # IDs


@dataclass
class MemoryState:
    """Current state of the observational memory."""

    observations: List[Observation] = field(default_factory=list)
    reflections: List[Reflection] = field(default_factory=list)
    last_observation_time: str = ""
    last_reflection_time: str = ""
    total_observations: int = 0
    observation_count_by_type: Dict[str, int] = field(default_factory=dict)


class ObservationScorer:
    """Determines importance of observations."""

    def __init__(self):
        # Weights for different factors
        self.weights = {
            "error": 0.9,
            "tool_failure": 0.8,
            "decision": 0.7,
            "plan_change": 0.6,
            "state_change": 0.4,
            "tool_call": 0.3,
            "llm_output": 0.2,
            "routine": 0.1,
        }

    def score(
        self, observation_type: ObservationType, content: str, metadata: Dict[str, Any]
    ) -> float:
        """Calculate importance score for an observation."""
        base_score = self.weights.get(observation_type.value, 0.3)

        # Boost for errors
        if observation_type in [ObservationType.ERROR, ObservationType.TOOL_RESULT]:
            if metadata.get("success") is False:
                base_score = max(base_score, 0.8)

        # Boost for user feedback
        if observation_type == ObservationType.USER_FEEDBACK:
            base_score = 0.9

        # Boost for repeated patterns (important for learning)
        if metadata.get("repeat_count", 0) > 2:
            base_score += 0.2

        # Content-based boosts
        content_lower = content.lower()
        important_keywords = ["important", "remember", "critical", "fix", "bug", "fail"]
        if any(kw in content_lower for kw in important_keywords):
            base_score += 0.1

        return min(base_score, 1.0)


class ObserverAgent:
    """The Observer: Background agent watching conversations and creating dense logs."""

    def __init__(
        self, scorer: ObservationScorer, llm_executor: Optional[Callable] = None
    ):
        self.scorer = scorer
        self.llm_executor = llm_executor
        self.observations: List[Observation] = []
        self.pending_observations: List[Dict] = []
        self.observation_buffer: List[Dict] = []
        self._observation_counter = 0

    def record(
        self,
        observation_type: ObservationType,
        content: str,
        metadata: Dict[str, Any] = None,
    ) -> Observation:
        """Record an observation with automatic importance scoring."""
        metadata = metadata or {}

        importance = self.scorer.score(observation_type, content, metadata)

        observation = Observation(
            id=self._generate_id(),
            timestamp=datetime.now().isoformat(),
            observation_type=observation_type,
            content=content,
            importance=importance,
            metadata=metadata,
            linked_to=self._find_related(observation_type, content),
        )

        self.observations.append(observation)
        self._observation_counter += 1

        return observation

    def record_tool_call(
        self, tool_name: str, args: Dict, result: Any = None, success: bool = True
    ) -> Observation:
        """Record a tool call observation."""
        content = f"Tool '{tool_name}' called with args: {json.dumps(args)}"
        if result:
            content += f" | Result: {str(result)[:200]}"

        return self.record(
            ObservationType.TOOL_RESULT if result else ObservationType.TOOL_CALL,
            content,
            {"tool_name": tool_name, "success": success, "args": args},
        )

    def record_llm_interaction(
        self, prompt: str, response: str = None, is_input: bool = True
    ) -> Observation:
        """Record LLM input/output."""
        if is_input:
            content = f"LLM Input: {prompt[:300]}"
            obs_type = ObservationType.LLM_INPUT
        else:
            content = (
                f"LLM Output: {response[:300]}" if response else "LLM Output: (empty)"
            )
            obs_type = ObservationType.LLM_OUTPUT

        return self.record(obs_type, content, {"is_input": is_input})

    def record_decision(self, decision: str, reason: str) -> Observation:
        """Record a decision made by the agent."""
        content = f"Decision: {decision} | Reason: {reason}"
        return self.record(ObservationType.DECISION, content, {"decision": decision})

    def record_error(self, error: str, context: Dict) -> Observation:
        """Record an error occurrence."""
        content = f"Error: {error}"
        return self.record(ObservationType.ERROR, content, {"error": error, **context})

    def record_state_change(
        self, from_state: str, to_state: str, reason: str
    ) -> Observation:
        """Record a state transition."""
        content = f"State: {from_state} → {to_state} | Reason: {reason}"
        return self.record(
            ObservationType.STATE_CHANGE, content, {"from": from_state, "to": to_state}
        )

    def record_plan_change(
        self, old_plan: str, new_plan: str, reason: str
    ) -> Observation:
        """Record plan modifications."""
        content = (
            f"Plan changed: {old_plan[:100]} → {new_plan[:100]} | Reason: {reason}"
        )
        return self.record(
            ObservationType.PLAN_CHANGE,
            content,
            {"old_plan": old_plan, "new_plan": new_plan},
        )

    def _generate_id(self) -> str:
        """Generate unique observation ID."""
        return f"obs_{self._observation_counter}_{int(time.time() * 1000)}"

    def _find_related(self, obs_type: ObservationType, content: str) -> List[str]:
        """Find related observations (for linking)."""
        related = []

        # Find last error if this is related to error handling
        if obs_type in [ObservationType.TOOL_RESULT, ObservationType.DECISION]:
            for obs in reversed(self.observations[-10:]):
                if obs.observation_type == ObservationType.ERROR:
                    related.append(obs.id)
                    break

        return related[:3]  # Max 3 links

    def get_recent_observations(
        self, limit: int = 50, min_importance: float = 0.0
    ) -> List[Observation]:
        """Get recent observations, optionally filtered by importance."""
        filtered = [
            o for o in reversed(self.observations) if o.importance >= min_importance
        ]
        return filtered[:limit]

    def get_high_importance_observations(
        self, threshold: float = 0.5
    ) -> List[Observation]:
        """Get all observations above importance threshold."""
        return [o for o in self.observations if o.importance >= threshold]

    def get_observations_by_type(self, obs_type: ObservationType) -> List[Observation]:
        """Get all observations of a specific type."""
        return [o for o in self.observations if o.observation_type == obs_type]

    def get_observation_stats(self) -> Dict[str, Any]:
        """Get statistics about recorded observations."""
        type_counts = defaultdict(int)
        total_importance = 0

        for obs in self.observations:
            type_counts[obs.observation_type.value] += 1
            total_importance += obs.importance

        return {
            "total_observations": len(self.observations),
            "by_type": dict(type_counts),
            "avg_importance": total_importance / max(len(self.observations), 1),
            "high_importance_count": len(self.get_high_importance_observations(0.5)),
        }


class ReflectorAgent:
    """The Reflector: Periodically reflects on observations and maintains summary."""

    def __init__(
        self, observer: ObserverAgent, llm_executor: Optional[Callable] = None
    ):
        self.observer = observer
        self.llm_executor = llm_executor
        self.reflections: List[Reflection] = []
        self.reflection_interval = 10  # Reflect every N observations
        self._reflection_counter = 0

    async def reflect(self, force: bool = False) -> Optional[Reflection]:
        """Generate a reflection based on recent observations."""
        recent = self.observer.get_recent_observations(limit=20)

        if len(recent) < 3 and not force:
            return None

        # Group observations by type for analysis
        by_type = defaultdict(list)
        for obs in recent:
            by_type[obs.observation_type.value].append(obs)

        # Generate reflection
        if self.llm_executor:
            # LLM-powered reflection
            reflection = await self._llm_reflect(recent, by_type)
        else:
            # Rule-based reflection
            reflection = self._rule_based_reflect(recent, by_type)

        if reflection:
            self.reflections.append(reflection)
            self._reflection_counter += 1

        return reflection

    async def _llm_reflect(
        self, observations: List[Observation], by_type: Dict
    ) -> Optional[Reflection]:
        """Use LLM to generate insightful reflection."""
        if not self.llm_executor:
            return None

        # Prepare context for LLM
        summary_parts = [f"Recent observations ({len(observations)} total):"]

        for obs_type, obs_list in by_type.items():
            summary_parts.append(f"- {obs_type}: {len(obs_list)}")

        # Add high importance observations
        high_imp = [o for o in observations if o.importance >= 0.6]
        if high_imp:
            summary_parts.append(f"\nHigh importance observations:")
            for o in high_imp[:5]:
                summary_parts.append(
                    f"  - [{o.observation_type.value}] {o.content[:100]}"
                )

        prompt = (
            "\n".join(summary_parts)
            + "\n\nGenerate a brief reflection (2-3 sentences) on what's happening, identify any patterns, and suggest improvements."
        )

        try:
            response = await self.llm_executor(
                prompt, "You are a helpful AI assistant that analyzes agent behavior."
            )

            return Reflection(
                id=f"ref_{self._reflection_counter}_{int(time.time())}",
                timestamp=datetime.now().isoformat(),
                summary=response.get("content", "Reflected on observations")[:500],
                key_insights=[],
                patterns_detected=[],
                suggestions=[],
                confidence=0.7,
                based_on_observations=[o.id for o in observations[-10:]],
            )
        except Exception as e:
            logger.warning(f"LLM reflection failed: {e}")
            return self._rule_based_reflect(observations, by_type)

    def _rule_based_reflect(
        self, observations: List[Observation], by_type: Dict
    ) -> Reflection:
        """Generate reflection using rules (no LLM needed)."""

        # Analyze patterns
        patterns = []
        insights = []

        # Check error patterns
        errors = by_type.get("error", [])
        if len(errors) > 2:
            patterns.append("Multiple errors detected")
            insights.append(f"Encountered {len(errors)} errors recently")

        # Check tool failure patterns
        tool_results = by_type.get("tool_result", [])
        failures = [t for t in tool_results if not t.metadata.get("success", True)]
        if len(failures) > len(tool_results) * 0.3:
            patterns.append("High tool failure rate")
            insights.append(f"{len(failures)}/{len(tool_results)} tools failed")

        # Check state changes
        states = by_type.get("state_change", [])
        if len(states) > 5:
            patterns.append("Frequent state changes")

        # Generate summary
        summary = f"Analyzed {len(observations)} observations. "
        if patterns:
            summary += f"Patterns: {'; '.join(patterns[:2])}. "
        if insights:
            summary += f"Insights: {'; '.join(insights[:2])}"

        return Reflection(
            id=f"ref_{self._reflection_counter}_{int(time.time())}",
            timestamp=datetime.now().isoformat(),
            summary=summary[:500],
            key_insights=insights[:3],
            patterns_detected=patterns[:3],
            suggestions=["Continue monitoring", "Review failed tools"]
            if failures
            else [],
            confidence=0.6,
            based_on_observations=[o.id for o in observations[-10:]],
        )

    def get_latest_reflection(self) -> Optional[Reflection]:
        """Get the most recent reflection."""
        return self.reflections[-1] if self.reflections else None


class ObservationalMemory:
    """
    Main class: Observational Memory for JARVIS.

    Unlike traditional context compaction (which loses information),
    Observational Memory maintains a dense, queryable log of all
    important events without losing context.

    This replaces the need for context compression in many cases!
    """

    def __init__(
        self, llm_executor: Optional[Callable] = None, auto_reflect: bool = True
    ):
        self.scorer = ObservationScorer()
        self.observer = ObserverAgent(self.scorer, llm_executor)
        self.reflector = ReflectorAgent(self.observer, llm_executor)
        self.auto_reflect = auto_reflect

        # Stats
        self.session_start = datetime.now().isoformat()
        self.observation_count = 0

    async def record(
        self,
        observation_type: ObservationType,
        content: str,
        metadata: Dict[str, Any] = None,
    ) -> Observation:
        """Record an observation and optionally trigger reflection."""
        obs = self.observer.record(observation_type, content, metadata)
        self.observation_count += 1

        # Auto-reflect every N observations
        if (
            self.auto_reflect
            and self.observation_count % self.reflector.reflection_interval == 0
        ):
            await self.reflector.reflect()

        return obs

    # Convenience methods for common observation types
    async def observe_tool(
        self, tool_name: str, args: Dict, result: Any = None, success: bool = True
    ) -> Observation:
        """Observe a tool call."""
        return await self.record(
            ObservationType.TOOL_RESULT if result else ObservationType.TOOL_CALL,
            f"Tool '{tool_name}' {'succeeded' if success else 'failed'}",
            {
                "tool_name": tool_name,
                "args": args,
                "result": str(result)[:500] if result else None,
                "success": success,
            },
        )

    async def observe_decision(self, decision: str, reason: str) -> Observation:
        """Observe a decision."""
        return await self.record(
            ObservationType.DECISION, f"{decision}: {reason}", {"decision": decision}
        )

    async def observe_error(self, error: str, context: Dict) -> Observation:
        """Observe an error."""
        return await self.record(ObservationType.ERROR, error, context)

    async def observe_state_change(
        self, from_state: str, to_state: str, reason: str
    ) -> Observation:
        """Observe state change."""
        return await self.record(
            ObservationType.STATE_CHANGE,
            f"{from_state} → {to_state}: {reason}",
            {"from": from_state, "to": to_state},
        )

    def get_context_for_llm(self, max_observations: int = 15) -> str:
        """
        Get formatted context from observations for LLM.
        This replaces traditional context compaction!
        """
        recent = self.observer.get_recent_observations(limit=max_observations)

        if not recent:
            return "No observations recorded yet."

        parts = ["## Recent Observations:"]

        for obs in recent:
            # Format: [TYPE] importance score: content
            importance_bar = "█" * int(obs.importance * 5) + "░" * (
                5 - int(obs.importance * 5)
            )
            parts.append(
                f"- [{obs.observation_type.value[:4]}] {importance_bar} {obs.content[:120]}"
            )

        # Add latest reflection if exists
        reflection = self.reflector.get_latest_reflection()
        if reflection:
            parts.append(f"\n## Latest Reflection:\n{reflection.summary}")

        return "\n".join(parts)

    def query_observations(self, query: str, limit: int = 5) -> List[Observation]:
        """Query observations by content (simple keyword search)."""
        query_lower = query.lower()
        return [
            o for o in self.observer.observations if query_lower in o.content.lower()
        ][:limit]

    def get_errors(self, limit: int = 10) -> List[Observation]:
        """Get recent errors."""
        return self.observer.get_observations_by_type(ObservationType.ERROR)[-limit:]

    def get_tool_failures(self, limit: int = 10) -> List[Observation]:
        """Get recent tool failures."""
        tool_results = self.observer.get_observations_by_type(
            ObservationType.TOOL_RESULT
        )
        return [t for t in tool_results if not t.metadata.get("success", True)][-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive memory statistics."""
        obs_stats = self.observer.get_observation_stats()

        return {
            "session_start": self.session_start,
            "total_observations": self.observation_count,
            "total_reflections": len(self.reflector.reflections),
            **obs_stats,
            "latest_reflection": self.reflector.get_latest_reflection().summary[:100]
            if self.reflector.get_latest_reflection()
            else None,
        }

    def clear(self):
        """Clear all observations and reflections."""
        self.observer.observations.clear()
        self.reflector.reflections.clear()
        self.observation_count = 0


# Integration with JARVIS
class ObservationalMemoryIntegration:
    """Integration layer for JARVIS engine."""

    def __init__(self, memory: ObservationalMemory):
        self.memory = memory

    async def wrap_tool_execution(self, tool_func, *args, **kwargs):
        """Wrap tool execution to record observations."""
        tool_name = tool_func.__name__ if hasattr(tool_func, "__name__") else "unknown"

        # Record tool call
        await self.memory.observe_tool(tool_name, kwargs, None, True)

        try:
            result = (
                await tool_func(*args, **kwargs)
                if asyncio.iscoroutinefunction(tool_func)
                else tool_func(*args, **kwargs)
            )
            # Record success
            await self.memory.observe_tool(tool_name, kwargs, result, True)
            return result
        except Exception as e:
            # Record failure
            await self.memory.observe_tool(tool_name, kwargs, str(e), False)
            await self.memory.observe_error(str(e), {"tool": tool_name, "args": kwargs})
            raise

    def get_context_string(self) -> str:
        """Get context string for LLM prompts."""
        return self.memory.get_context_for_llm()


# Standalone test
if __name__ == "__main__":

    async def test():
        memory = ObservationalMemory()

        # Record some observations
        await memory.observe_tool(
            "file_read", {"path": "/test.py"}, "file content", True
        )
        await memory.observe_tool(
            "execute_command", {"cmd": "python test.py"}, "FAIL: ImportError", False
        )
        await memory.observe_decision(
            "Use fallback model", "Primary model rate limited"
        )
        await memory.observe_error("Connection timeout", {"service": "api"})
        await memory.observe_state_change("PLANNING", "EXECUTING", "Plan approved")

        # Add more to trigger reflection
        for i in range(8):
            await memory.observe_tool(f"tool_{i}", {"n": i}, "result", True)

        # Get context
        print(memory.get_context_for_llm())

        # Get stats
        print("\nStats:", memory.get_stats())

        # Query
        print("\nErrors:", [e.content for e in memory.get_errors()])

    asyncio.run(test())
