"""🧠 JARVIS Meta-Cognition Engine

Gives JARVIS the ability to THINK, not just execute.

Features:
- Meta-cognition loop: think before acting
- Self-reflection: analyze past actions
- Reasoning chains: step-by-step thinking
- Error analysis: learn from mistakes
- Strategy planning: choose best approach
- Curiosity: ask questions, explore

This transforms JARVIS from a "tool executor" to a "thinking agent".
"""

import asyncio
import logging
import time
import json
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ThoughtType(Enum):
    """Types of thoughts JARVIS can have."""

    REASONING = "reasoning"  # Step-by-step logic
    REFLECTION = "reflection"  # Analyzing past actions
    PLANNING = "planning"  # Planning future actions
    QUESTION = "question"  # Asking clarifying questions
    HYPOTHESIS = "hypothesis"  # Forming assumptions
    EVALUATION = "evaluation"  # Judging options
    CORRECTION = "correction"  # Fixing mistakes
    CURIOSITY = "curiosity"  # Exploring new ideas


@dataclass
class Thought:
    """A single thought in JARVIS's mind."""

    id: str
    thought_type: ThoughtType
    content: str
    confidence: float  # 0-1, how confident JARVIS is
    evidence: List[str] = field(default_factory=list)  # Supporting evidence
    alternatives: List[str] = field(default_factory=list)  # Alternative thoughts
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    parent_id: Optional[str] = None  # For reasoning chains


@dataclass
class ReasoningChain:
    """A chain of thoughts leading to a conclusion."""

    id: str
    thoughts: List[Thought]
    conclusion: str = ""
    reasoning_depth: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Reflection:
    """A reflection on past actions."""

    id: str
    action: str
    result: str
    what_worked: List[str] = field(default_factory=list)
    what_didnt_work: List[str] = field(default_factory=list)
    lessons_learned: List[str] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class MetaCognition:
    """
    JARVIS's thinking engine.

    Transforms JARVIS from "tool executor" to "thinking agent".
    """

    def __init__(self, llm_executor: Optional[Callable] = None):
        self.llm_executor = llm_executor
        self.thoughts: List[Thought] = []
        self.reasoning_chains: List[ReasoningChain] = []
        self.reflections: List[Reflection] = []
        self._thought_counter = 0

        # Thinking config
        self.thinking_enabled = True  # Meta-cognition enabled
        self.reflect_after_action = True  # Self-reflection enabled
        self.max_reasoning_depth = 5
        self.curiosity_enabled = True

    # ═══════════════════════════════════════════════════════════
    # THINKING PRIMITIVES
    # ═══════════════════════════════════════════════════════════════

    async def think(self, prompt: str, context: Dict = None) -> Thought:
        """
        Main thinking method - generates a thought.

        This is where JARVIS "thinks" about something.
        """
        # If we have an LLM, use it for deeper thinking
        if callable(self.llm_executor) and context:
            thought_content = await self._llm_think(prompt, context)
        else:
            # Rule-based fallback
            thought_content = self._rule_think(prompt)

        thought = Thought(
            id=self._generate_id(),
            thought_type=ThoughtType.REASONING,
            content=thought_content,
            confidence=0.7,
            evidence=self._extract_evidence(prompt),
            alternatives=self._generate_alternatives(prompt),
        )

        self.thoughts.append(thought)
        return thought

    async def think_before_action(self, task: str) -> Dict[str, Any]:
        """
        Meta-cognition: Think BEFORE executing a task.

        Returns:
        - Best approach
        - Potential pitfalls
        - Alternative strategies
        """
        logger.info(f"🧠 [META] Thinking about: {task[:50]}...")

        # Generate reasoning chain
        chain = await self._build_reasoning_chain(task)

        # Ask: what's the best approach?
        approach = await self._evaluate_approaches(task, chain)

        # Ask: what could go wrong?
        pitfalls = await self._identify_pitfalls(task)

        # Ask: any alternative strategies?
        alternatives = await self._generate_strategies(task)

        return {
            "reasoning_chain": chain,
            "best_approach": approach,
            "potential_pitfalls": pitfalls,
            "alternative_strategies": alternatives,
            "confidence": 0.8 if chain.reasoning_depth >= 3 else 0.6,
        }

    async def reflect_on_action(self, action: str, result: Any) -> Reflection:
        """
        Self-reflection: Analyze what happened after an action.

        This is how JARVIS learns from experience!
        """
        logger.info(f"🔍 [REFLECT] Analyzing: {action[:30]}...")

        if callable(self.llm_executor):
            reflection = await self._llm_reflect(action, result)
        else:
            reflection = self._rule_reflect(action, result)

        self.reflections.append(reflection)

        # Store lessons for future use
        await self._store_lessons(reflection)

        return reflection

    # ═══════════════════════════════════════════════════════════
    # REASONING CHAINS
    # ═══════════════════════════════════════════════════════════

    async def _build_reasoning_chain(self, task: str) -> ReasoningChain:
        """Build a reasoning chain for a task."""
        chain = ReasoningChain(id=self._generate_id(), thoughts=[])

        # Step 1: Understand the task
        thought1 = await self.think(f"What is this task really about? {task}")
        thought1.thought_type = ThoughtType.REASONING
        chain.thoughts.append(thought1)

        # Step 2: Break it down
        thought2 = await self.think(f"What are the components of this task? {task}")
        thought2.thought_type = ThoughtType.REASONING
        chain.thoughts.append(thought2)

        # Step 3: Consider approaches
        thought3 = await self.think(f"What approaches could work?")
        thought3.thought_type = ThoughtType.EVALUATION
        chain.thoughts.append(thought3)

        # Step 4: Form hypothesis
        thought4 = await self.think(f"What's the most likely to succeed?")
        thought4.thought_type = ThoughtType.HYPOTHESIS
        chain.thoughts.append(thought4)

        chain.reasoning_depth = len(chain.thoughts)

        return chain

    async def _evaluate_approaches(self, task: str, chain: ReasoningChain) -> str:
        """Evaluate and choose best approach."""
        if callable(self.llm_executor):
            prompt = f"""Given this task: {task}

And this reasoning: {chain.thoughts[-1].content}

What is the BEST approach? Consider:
1. Efficiency
2. Reliability
3. Safety

Return the best approach in 1-2 sentences."""

            result = await self.llm_executor(prompt, "You are a helpful assistant.")
            return result.content if hasattr(result, "content") else str(result)

        return "Execute step-by-step, starting with simplest approach."

    async def _identify_pitfalls(self, task: str) -> List[str]:
        """Identify potential pitfalls."""
        if callable(self.llm_executor):
            prompt = f"""What could go wrong with this task: {task}

List 3-5 potential pitfalls or failure modes."""

            result = await self.llm_executor(prompt, "You are a helpful assistant.")
            return [line.strip() for line in result.content.split("\n") if line.strip()]

        return ["Unexpected errors", "Wrong assumptions", "Missing context"]

    async def _generate_strategies(self, task: str) -> List[str]:
        """Generate alternative strategies."""
        if callable(self.llm_executor):
            prompt = f"""For task: {task}

What are 3 DIFFERENT ways to approach it?"""

            result = await self.llm_executor(prompt, "You are a helpful assistant.")
            return [line.strip() for line in result.content.split("\n") if line.strip()]

        return ["Direct approach", "Break into smaller tasks", "Ask for clarification"]

    # ═══════════════════════════════════════════════════════════
    # LLM-POWERED THINKING (when available)
    # ═══════════════════════════════════════════════════════════

    async def _llm_think(self, prompt: str, context: Dict) -> str:
        """Use LLM for deeper thinking."""
        if not callable(self.llm_executor):
            return "No LLM available for thinking."

        system_prompt = """You are JARVIS's thinking engine. 
Think deeply and provide insightful analysis.
Consider multiple perspectives, question assumptions, 
and provide well-reasoned conclusions."""

        full_prompt = f"{system_prompt}\n\n{prompt}"

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

            result = await self.llm_executor(full_prompt, "Think about this:")
            return result.content if hasattr(result, "content") else str(result)
        except Exception as e:
            logger.warning(f"LLM thinking failed: {e}")
            return f"Thinking about: {prompt[:100]}..."

    async def _llm_reflect(self, action: str, result: Any) -> Reflection:
        """Use LLM for deeper reflection."""
        if not callable(self.llm_executor):
            return self._rule_reflect(action, result)

        prompt = f"""Analyze this action and result:

Action: {action}
Result: {result}

Provide:
1. What worked (1-2 things)
2. What didn't work (1-2 things)  
3. Lessons learned (1-2 things)
4. How to improve (1-2 suggestions)"""

        try:
            response = await self.llm_executor(prompt, "Analyze this:")
            content = (
                response.content if hasattr(response, "content") else str(response)
            )

            # Parse response
            lines = content.split("\n")

            return Reflection(
                id=self._generate_id(),
                action=action,
                result=str(result)[:200],
                what_worked=lines[:2] if len(lines) > 0 else [],
                what_didnt_work=lines[2:4] if len(lines) > 2 else [],
                lessons_learned=lines[4:6] if len(lines) > 4 else [],
                improvement_suggestions=lines[6:8] if len(lines) > 6 else [],
            )
        except Exception as e:
            logger.warning(f"LLM reflection failed: {e}")
            return self._rule_reflect(action, result)

    # ═══════════════════════════════════════════════════════════
    # RULE-BASED FALLBACK (when no LLM)
    # ═══════════════════════════════════════════════════════════════

    def _rule_think(self, prompt: str) -> str:
        """Rule-based thinking fallback."""
        return f"Analyzing: {prompt[:100]}..."

    def _rule_reflect(self, action: str, result: Any) -> Reflection:
        """Rule-based reflection fallback."""
        success = (
            "error" not in str(result).lower() and "fail" not in str(result).lower()
        )

        return Reflection(
            id=self._generate_id(),
            action=action,
            result=str(result)[:200],
            what_worked=["Completed without errors"] if success else [],
            what_didnt_work=["Errors encountered"] if not success else [],
            lessons_learned=["Continue monitoring results"],
            improvement_suggestions=["Add more error handling"]
            if not success
            else ["Keep current approach"],
        )

    def _extract_evidence(self, prompt: str) -> List[str]:
        """Extract evidence from prompt."""
        return [f"Analyzing: {prompt[:50]}"]

    def _generate_alternatives(self, prompt: str) -> List[str]:
        """Generate alternative approaches."""
        return ["Alternative 1", "Alternative 2", "Alternative 3"]

    async def _store_lessons(self, reflection: Reflection):
        """Store lessons for future reference."""
        # This could integrate with skills engine
        logger.info(f"💾 [LEARN] Stored lesson: {reflection.lessons_learned[:1]}")

    # ═══════════════════════════════════════════════════════════
    # UTILITY METHODS
    # ═══════════════════════════════════════════════════════════

    def _generate_id(self) -> str:
        """Generate unique thought ID."""
        self._thought_counter += 1
        return f"thought_{self._thought_counter}_{int(time.time())}"

    def get_recent_thoughts(self, limit: int = 10) -> List[Thought]:
        """Get recent thoughts."""
        return self.thoughts[-limit:]

    def get_recent_reflections(self, limit: int = 10) -> List[Reflection]:
        """Get recent reflections."""
        return self.reflections[-limit:]

    def get_thinking_stats(self) -> Dict[str, Any]:
        """Get thinking statistics."""
        thought_types = {}
        for thought in self.thoughts:
            ttype = thought.thought_type.value
            thought_types[ttype] = thought_types.get(ttype, 0) + 1

        return {
            "total_thoughts": len(self.thoughts),
            "total_reflections": len(self.reflections),
            "thought_types": thought_types,
            "avg_confidence": sum(t.confidence for t in self.thoughts)
            / max(len(self.thoughts), 1),
        }

    def clear(self):
        """Clear thinking history."""
        self.thoughts.clear()
        self.reflections.clear()
        self.reasoning_chains.clear()


# Integration with JarvisEngine
class JarvisMetaCognition:
    """Wrapper to integrate meta-cognition with JARVIS."""

    def __init__(self, meta: MetaCognition, llm_executor: Callable):
        self.meta = meta
        self.llm_executor = llm_executor

    async def think_and_execute(
        self, task: str, executor_func: Callable
    ) -> Dict[str, Any]:
        """
        Think BEFORE executing, then execute, then reflect.

        Complete meta-cognition loop!
        """
        # Phase 1: Think
        logger.info(f"🧠 [THINK] Analyzing task: {task[:50]}...")
        thinking_result = await self.meta.think_before_action(task)

        # Phase 2: Execute
        logger.info(f"⚡ [EXECUTE] Running task...")
        try:
            result = await executor_func()
            success = True
        except Exception as e:
            result = str(e)
            success = False

        # Phase 3: Reflect
        logger.info(f"🔍 [REFLECT] Analyzing result...")
        reflection = await self.meta.reflect_on_action(task, result)

        return {
            "thinking": thinking_result,
            "result": result,
            "success": success,
            "reflection": {
                "worked": reflection.what_worked,
                "didnt_work": reflection.what_didnt_work,
                "lessons": reflection.lessons_learned,
            },
        }


# Standalone test
if __name__ == "__main__":

    async def test():
        meta = MetaCognition()

        # Test thinking
        print("=== Thinking ===")
        thought = await meta.think("How to solve this problem?")
        print(f"Thought: {thought.content}")

        # Test meta-cognition
        print("\n=== Think Before Action ===")
        result = await meta.think_before_action("Fix this bug in the code")
        print(f"Best approach: {result['best_approach']}")
        print(f"Pitfalls: {result['potential_pitfalls']}")

        # Test reflection
        print("\n=== Reflect on Action ===")
        reflection = await meta.reflect_on_action("Wrote code", "Works but slow")
        print(f"Lessons: {reflection.lessons_learned}")

        # Stats
        print("\n=== Stats ===")
        print(meta.get_thinking_stats())

    asyncio.run(test())
