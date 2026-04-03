"""
J.A.R.V.I.S. Repair Engine
==========================

Execută recovery logic după eșecuri.

Based on JARVIS V2 Blueprint Section 4.5
"""

from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from enum import Enum
import logging

from core.task_contracts import (
    PlanStep,
    ExecutionResult,
    VerificationResult,
    FailureCode,
)
from core.post_action_observer import SemanticSnapshot

logger = logging.getLogger(__name__)


class RepairAction(str, Enum):
    """Acțiuni de repair"""

    RETRY_SAME_TOOL = "retry_same_tool"
    RETRY_FALLBACK_TOOL = "retry_fallback_tool"
    SKIP_STEP = "skip_step"
    REPLAN = "replan"
    ESCALATE = "escalate"
    ABORT = "abort"


@dataclass
class RepairResult:
    """Rezultatul operației de repair"""

    action: RepairAction
    success: bool
    new_step: Optional[PlanStep] = None
    failure_code: Optional[str] = None
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class RepairEngine:
    """
    Engine pentru recovery logic.

    Responsabil pentru:
    - retry controlat
    - schimbare de tool
    - schimbare de strategie
    - escaladare spre aprobare umană
    """

    def __init__(self):
        self.repair_history = []
        self.max_retries_per_tool = 2
        self.max_fallback_attempts = 2

    def choose_repair_action(
        self,
        step: PlanStep,
        result: ExecutionResult,
        verification: VerificationResult | None,
    ) -> RepairResult:
        """
        Alege ce acțiune de repair să execute.

        Args:
            step: Pasul care a eșuat
            result: Rezultatul execuției
            verification: Rezultatul verificării

        Returns:
            RepairResult cu acțiunea aleasă
        """

        # Case 1: Execution failed - retry or escalate
        if result.status.value == "FAIL":
            if result.error_code == "TOOL_TIMEOUT":
                # Try fallback tool
                repair = self._retry_with_fallback_tool(step, "Timeout")
                self.repair_history.append(repair)
                return repair
            elif result.error_code == "TOOL_NOT_AVAILABLE":
                if len(step.tool_candidates) > 1:
                    repair = self._retry_with_fallback_tool(
                        step, "Primary tool unavailable"
                    )
                else:
                    repair = self._escalate_to_human(step, "Tool not available")
                self.repair_history.append(repair)
                return repair
            else:
                # Retry same tool
                if step.retry_count < step.max_retries:
                    repair = self._retry_with_same_tool(step, f"Retry {step.retry_count + 1}")
                    self.repair_history.append(repair)
                    return repair
                else:
                    # Max retries exceeded - replan
                    repair = self._trigger_replan(step, "Max retries exceeded")
                    self.repair_history.append(repair)
                    return repair

        # Case 2: Verification failed - determine why
        if verification is not None and not verification.verified:
            # Check confidence
            if verification.confidence.value == "LOW":
                # Low confidence - retry with more verification
                return self._retry_with_same_tool(step, "Low confidence - verify again")

            # Check if it's a recoverable mismatch
            if verification.mismatch_reason:
                if "signal" in verification.mismatch_reason.lower():
                    # No signals - might be state issue
                    repair = self._retry_with_same_tool(step, "Retry - check signals")
                    self.repair_history.append(repair)
                    return repair
                elif "artifact" in verification.mismatch_reason.lower():
                    # Artifact missing - might be path issue
                    repair = self._retry_with_fallback_tool(step, "Artifact issue")
                    self.repair_history.append(repair)
                    return repair
                else:
                    # Unknown mismatch - replan
                    repair = self._trigger_replan(step, verification.mismatch_reason)
                    self.repair_history.append(repair)
                    return repair

            # Default: retry
            repair = self._retry_with_same_tool(step, "Verification failed")
            self.repair_history.append(repair)
            return repair

        # Case 3: Hallucination detected
        if verification is not None and (
            verification.mismatch_reason
            and "hallucination" in verification.mismatch_reason.lower()
        ):
            # Force replan
            repair = self._trigger_replan(step, "Hallucination detected")
            self.repair_history.append(repair)
            return repair

        # Default: continue
        repair = RepairResult(
            action=RepairAction.RETRY_SAME_TOOL, success=True, reason="No repair needed"
        )
        self.repair_history.append(repair)
        return repair

    def retry_with_same_tool(self, step: PlanStep, context: Dict[str, Any]) -> Dict[str, Any]:
        """Public blueprint API for retrying the current step."""
        reason = context.get("reason", "Retry requested")
        result = self._retry_with_same_tool(step, reason)
        self.repair_history.append(result)
        return self.apply_repair(result, step, context)

    def retry_with_fallback_tool(
        self, step: PlanStep, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Public blueprint API for using the next tool candidate."""
        reason = context.get("reason", "Fallback requested")
        result = self._retry_with_fallback_tool(step, reason)
        self.repair_history.append(result)
        return self.apply_repair(result, step, context)

    def escalate_to_human(self, step: PlanStep, reason: str) -> Dict[str, Any]:
        """Public blueprint API for escalation."""
        result = self._escalate_to_human(step, reason)
        self.repair_history.append(result)
        return self.apply_repair(result, step, {"reason": reason})

    def trigger_replan(self, mission_id: str, failure_context: Dict[str, Any]) -> Dict[str, Any]:
        """Public blueprint API for replanning."""
        reason = failure_context.get("reason", "Failure context requires replan")
        trigger_step = failure_context.get("step_id", mission_id)
        result = RepairResult(
            action=RepairAction.REPLAN,
            success=True,
            reason=reason,
            metadata={"mission_id": mission_id, "trigger_step": trigger_step},
        )
        self.repair_history.append(result)
        return {"ok": True, "replan": True, "mission_id": mission_id, "reason": reason}

    def _retry_with_same_tool(self, step: PlanStep, reason: str) -> RepairResult:
        """Retry cu același tool"""
        step.retry_count += 1

        logger.info(f"🔄 [REPAIR] Retrying step {step.id} (attempt {step.retry_count})")

        return RepairResult(
            action=RepairAction.RETRY_SAME_TOOL,
            success=True,
            new_step=step,
            reason=reason,
            metadata={"retry_count": step.retry_count, "tool": step.tool_candidates[0]},
        )

    def _retry_with_fallback_tool(self, step: PlanStep, reason: str) -> RepairResult:
        """Retry cu tool alternativ"""

        # Find fallback tool
        if len(step.tool_candidates) > 1:
            fallback_tool = step.tool_candidates[1]
            step.tool_candidates = [fallback_tool] + step.tool_candidates[2:]

            logger.info(
                f"🔄 [REPAIR] Using fallback tool for {step.id}: {fallback_tool}"
            )

            return RepairResult(
                action=RepairAction.RETRY_FALLBACK_TOOL,
                success=True,
                new_step=step,
                reason=reason,
                metadata={"fallback_tool": fallback_tool},
            )
        else:
            # No fallback available - replan
            return self._trigger_replan(step, "No fallback tool available")

    def _escalate_to_human(self, step: PlanStep, reason: str) -> RepairResult:
        """Escaladează spre aprobare umană"""

        logger.warning(f"⚠️ [REPAIR] Escalating {step.id} to human")

        return RepairResult(
            action=RepairAction.ESCALATE,
            success=False,
            failure_code=FailureCode.APPROVAL_DENIED.value,
            reason=reason,
            metadata={"step_id": step.id, "requires_approval": True},
        )

    def _trigger_replan(self, step: PlanStep, reason: str) -> RepairResult:
        """Declanșează replanificarea"""

        logger.warning(f"🔄 [REPAIR] Triggering replan for {step.id}: {reason}")

        return RepairResult(
            action=RepairAction.REPLAN,
            success=True,
            reason=reason,
            metadata={"trigger_step": step.id, "reason": reason},
        )

    def _skip_step(self, step: PlanStep, reason: str) -> RepairResult:
        """Skip step (for optional steps)"""

        logger.info(f"⏭️ [REPAIR] Skipping step {step.id}")

        return RepairResult(
            action=RepairAction.SKIP_STEP,
            success=True,
            reason=reason,
            metadata={"skipped_step": step.id},
        )

    def _abort_mission(self, step: PlanStep, reason: str) -> RepairResult:
        """Abandonează misiunea"""

        logger.error(f"🛑 [REPAIR] Aborting mission: {reason}")

        return RepairResult(
            action=RepairAction.ABORT,
            success=False,
            failure_code=FailureCode.RECOVERY_FAIL.value,
            reason=reason,
        )

    def apply_repair(
        self, repair_result: RepairResult, step: PlanStep, context: Dict
    ) -> Dict[str, Any]:
        """
        Aplică efectiv repararea.

        Returns:
            Dict cu "ok" și noul pas (dacă există)
        """

        if not repair_result.success:
            return {
                "ok": False,
                "failure_code": repair_result.failure_code,
                "reason": repair_result.reason,
            }

        if repair_result.action == RepairAction.RETRY_SAME_TOOL:
            return {
                "ok": True,
                "retry": True,
                "new_step": repair_result.new_step,
                "tool": repair_result.metadata.get("tool"),
            }

        elif repair_result.action == RepairAction.RETRY_FALLBACK_TOOL:
            return {
                "ok": True,
                "retry": True,
                "new_step": repair_result.new_step,
                "fallback": True,
                "tool": repair_result.metadata.get("fallback_tool"),
            }

        elif repair_result.action == RepairAction.REPLAN:
            return {"ok": True, "replan": True, "reason": repair_result.reason}

        elif repair_result.action == RepairAction.ESCALATE:
            return {
                "ok": False,
                "escalate": True,
                "reason": repair_result.reason,
                "requires_human": True,
            }

        elif repair_result.action == RepairAction.ABORT:
            return {"ok": False, "abort": True, "reason": repair_result.reason}

        return {"ok": True, "continue": True}

    def get_repair_stats(self) -> Dict[str, Any]:
        """Get repair statistics"""
        return {
            "total_repairs": len(self.repair_history),
            "by_action": self._count_actions(),
        }

    def _count_actions(self) -> Dict[str, int]:
        """Count repair actions"""
        counts = {}
        for repair in self.repair_history:
            action = repair.action.value
            counts[action] = counts.get(action, 0) + 1
        return counts


# ==================== GLOBAL INSTANCE ====================

_repair_engine: Optional[RepairEngine] = None


def get_repair_engine() -> RepairEngine:
    """Get or create global repair engine"""
    global _repair_engine
    if _repair_engine is None:
        _repair_engine = RepairEngine()
    return _repair_engine


# ==================== TEST ====================

if __name__ == "__main__":
    from core.task_contracts import PlanStep, ExecutionResult, SuccessCriteria, TaskRisk

    print("=== REPAIR ENGINE TEST ===\n")

    engine = get_repair_engine()

    # Test case 1: Tool timeout
    step1 = PlanStep.create("Search", "search_tool", TaskRisk.R0, "Results")
    step1.retry_count = 0
    step1.max_retries = 2

    result1 = ExecutionResult(
        step_id=step1.id,
        tool_name="search_tool",
        raw_output=None,
        error_code="TOOL_TIMEOUT",
    )
    result1.mark_complete(False, "Timeout")

    # No verification for timeout
    from core.task_contracts import VerificationResult, VerificationConfidence
    # Create minimal verification (pretend execution failed triggers this)

    repair1 = engine.choose_repair_action(step1, result1, None)
    print(f"Case 1 (timeout): {repair1.action.value}")

    # Test case 2: Max retries
    step2 = PlanStep.create("Search", "search_tool", TaskRisk.R0, "Results")
    step2.retry_count = 2  # Already at max
    step2.max_retries = 2

    result2 = ExecutionResult(
        step_id=step2.id, tool_name="search_tool", raw_output=None
    )
    result2.mark_complete(False, "Failed again")

    repair2 = engine.choose_repair_action(step2, result2, None)
    print(f"Case 2 (max retries): {repair2.action.value}")

    print("\n✅ Repair engine test complete!")
