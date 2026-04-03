"""ULTRAPLAN deep planning mode for complex missions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class UltraPlanStep:
    """One actionable step in a deep plan."""

    phase: str
    title: str
    objective: str
    outputs: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)


class UltraPlanner:
    """Generates deep implementation plans with explicit checkpoints."""

    COMPLEXITY_KEYWORDS = {
        "multi": 2,
        "integrate": 2,
        "import": 2,
        "agent": 1,
        "schema": 1,
        "mcp": 1,
        "memory": 1,
        "planning": 1,
        "coordinator": 2,
        "knowledge": 1,
        "graph": 1,
    }

    def classify(self, task: str) -> Dict[str, Any]:
        task_lower = task.lower()
        score = 1
        for keyword, weight in self.COMPLEXITY_KEYWORDS.items():
            if keyword in task_lower:
                score += weight

        mode = "ultraplan" if score >= 5 else "default"
        if any(token in task_lower for token in ["coordinate", "multi-agent", "fleet"]):
            mode = "coordinator"

        return {"score": score, "recommended_mode": mode}

    def build_plan(
        self,
        task: str,
        *,
        context: str = "",
        constraints: List[str] | None = None,
    ) -> Dict[str, Any]:
        classification = self.classify(task)
        constraints = constraints or []

        steps = [
            UltraPlanStep(
                phase="P0 Discovery",
                title="Map current state",
                objective="Locate existing implementations, integration points, and hidden constraints.",
                outputs=["inventory of touched modules", "integration risks", "missing dependencies"],
                risks=["editing the wrong abstraction layer", "duplicating already-shipped functionality"],
            ),
            UltraPlanStep(
                phase="P1 Core",
                title="Implement stable primitives",
                objective="Add the minimum reliable building blocks first: schemas, state models, and utility helpers.",
                outputs=["validated primitives", "backwards-compatible interfaces"],
                risks=["API drift", "partial feature wiring"],
            ),
            UltraPlanStep(
                phase="P2 Integration",
                title="Wire runtime paths",
                objective="Expose the new capability through engine, MCP, and user-facing orchestration paths.",
                outputs=["registered tools", "runtime integration", "context updates"],
                risks=["unreachable features", "runtime regressions"],
            ),
            UltraPlanStep(
                phase="P3 Verification",
                title="Validate behavior",
                objective="Run compile/tests/smoke checks and inspect failure surfaces.",
                outputs=["compile pass", "smoke results", "remaining gaps"],
                risks=["silent validation gaps", "false confidence from shallow checks"],
            ),
        ]

        return {
            "mode": classification["recommended_mode"],
            "complexity_score": classification["score"],
            "task": task,
            "context": context[:800],
            "constraints": constraints,
            "success_criteria": [
                "Feature is reachable from the engine/runtime path.",
                "Tool schemas reject malformed input.",
                "State is persisted or discoverable where needed.",
                "Verification covers the changed code paths.",
            ],
            "steps": [
                {
                    "phase": step.phase,
                    "title": step.title,
                    "objective": step.objective,
                    "outputs": step.outputs,
                    "risks": step.risks,
                }
                for step in steps
            ],
        }
