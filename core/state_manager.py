"""J.A.R.V.I.S. (GALAXY NUCLEUS - STATE MANAGER AEON V2)

The Finite State Machine (FSM) for high-reliability agentic missions.
Prevents infinite loops and ensures structural transparency of the workflow.
Integrates: task_contracts, risk_engine, post_action_observer, verifier_engine, repair_engine
"""

import logging
from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from .task_contracts import (
    TaskContract,
    SuccessCriteria,
    ExecutionResult,
    VerificationResult,
    VerificationConfidence,
    FailureCode,
    TaskRisk,
)
from .risk_engine import RiskEngine
from .post_action_observer import PostActionObserver, SemanticSnapshot
from .verifier_engine import VerifierEngine, VerificationMethod
from .repair_engine import RepairEngine, RepairAction

logger = logging.getLogger(__name__)


class MissionState(Enum):
    IDLE = "IDLE"
    INTAKE = "INTAKE"
    PLANNING = "PLANNING"
    RISK_CHECK = "RISK_CHECK"
    RISK_REVIEW = "RISK_REVIEW"
    EXECUTING = "EXECUTING"
    EXECUTING_STEP = "EXECUTING_STEP"
    OBSERVING = "OBSERVING"
    VALIDATING = "VALIDATING"
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    ABORTED = "ABORTED"


class StateManager:
    """The 'Nervous System' of J.A.R.V.I.S. AEON GRADE V2."""

    def __init__(self, max_steps: int = 50):
        self.current_state = MissionState.IDLE
        self.step_count = 0
        self.max_steps = max_steps
        self.history: List[Dict[str, Any]] = []

        # V2 Engines
        self.risk_engine = RiskEngine()
        self.observer = PostActionObserver()
        self.verifier = VerifierEngine()
        self.repair_engine = RepairEngine()

        # V2 State Tracking
        self.current_contract: Optional[TaskContract] = None
        self.semantic_state: Dict[str, Any] = {}
        self.failure_history: List[Dict[str, Any]] = []
        self.retry_count = 0
        self.max_retries = 3
        self.last_snapshot: Optional[SemanticSnapshot] = None
        self.last_verification: Optional[VerificationResult] = None
        self.failure_codes: List[str] = []

        logger.info(
            f"🔄 [STATE] Manager V2 initialized. Current: {self.current_state.value}"
        )

    def transition_to(self, new_state: MissionState, context: Optional[str] = None):
        """[TRANSITION]: Explicitly move between mission phases."""
        old_state = self.current_state
        self.current_state = new_state
        self.step_count += 1

        # Infinite Loop Protection
        if self.step_count > self.max_steps:
            logger.error(
                f"🚨 [STATE] STEPCAP BREACH: {self.step_count} steps. Forcing FAILURE."
            )
            self.current_state = MissionState.FAILURE
            return

        log_entry = {
            "step": self.step_count,
            "from": old_state.value,
            "to": new_state.value,
            "context": context,
        }
        self.history.append(log_entry)

        logger.info(
            f"🔄 [STATE] Step {self.step_count}: {old_state.value} ➡️ {new_state.value} | {context or ''}"
        )

    def get_mission_report(self) -> Dict[str, Any]:
        """[REPORT]: Provides a structured diagnostic of the entire mission flow."""
        return {
            "final_state": self.current_state.value,
            "total_steps": self.step_count,
            "history": self.history,
            "failure_codes": self.failure_codes,
        }

    def reset(self):
        """[RESET]: Clears the state for a new mission."""
        self.current_state = MissionState.IDLE
        self.step_count = 0
        self.history = []
        self.current_contract = None
        self.semantic_state = {}
        self.failure_history = []
        self.retry_count = 0
        self.last_snapshot = None
        self.last_verification = None
        self.failure_codes = []
        logger.info("🔄 [STATE] Mission state reset.")

    # ═══════════════════════════════════════════════════════════════
    #  V2 INTEGRATION METHODS
    # ═══════════════════════════════════════════════════════════════

    def check_risk(self, action: str, target: str = "") -> TaskRisk:
        """[RISK]: Evaluate risk level for an action."""
        from .task_contracts import PlanStep, SuccessCriteria

        temp_step = PlanStep(
            id="risk_check",
            title=action,
            description=f"{action} {target}".strip(),
            tool_candidates=[action],
            success_criteria=SuccessCriteria(description=f"Execute {action}"),
        )
        result = self.risk_engine.classify_step_risk(temp_step)
        logger.info(f"⚠️ [RISK] {action} -> {result.risk_level.value}")
        return result.risk_level

    def enter_observing(self, step_id: str) -> None:
        """Explicit observing transition for blueprint step loop."""
        self.transition_to(MissionState.OBSERVING, f"Observing step {step_id}")

    def enter_verifying(self, step_id: str) -> None:
        """Explicit verifying transition for blueprint step loop."""
        self.transition_to(MissionState.VERIFYING, f"Verifying step {step_id}")

    def enter_waiting_approval(self, step_id: str, risk: str) -> None:
        """Transition into approval gate."""
        self.transition_to(
            MissionState.WAITING_APPROVAL,
            f"Waiting approval for {step_id} ({risk})",
        )

    def record_failure_code(self, code: str) -> None:
        """Store normalized failure codes for later metrics/evals."""
        self.failure_codes.append(code)
        logger.info(f"🚨 [STATE] Failure code recorded: {code}")

    def set_contract(self, contract: TaskContract):
        """[CONTRACT]: Set the current task contract."""
        self.current_contract = contract
        logger.info(f"📋 [CONTRACT] Task: {contract.mission_id[:20]}...")

    def observe_action(
        self,
        action: str,
        expected_state: Dict[str, Any],
        *,
        step_id: str = "current",
        session_id: str = "main",
    ) -> SemanticSnapshot:
        """[OBSERVE]: Capture semantic snapshot after action."""
        snapshot = self.observer.observe_after_action(
            step_id=step_id,
            session_id=session_id,
            action_type=action,
            action_params=expected_state,
        )
        self.last_snapshot = snapshot
        # Build semantic state from snapshot fields
        self.semantic_state = {
            "browser_url": snapshot.browser_url,
            "browser_title": snapshot.browser_title,
            "active_window": snapshot.active_window,
            "files_created": snapshot.files_created,
            "files_modified": snapshot.files_modified,
            "signals": snapshot.signals,
        }
        return snapshot

    def verify_result(self, result: ExecutionResult) -> VerificationResult:
        """[VERIFY]: Verify execution result against contract."""
        if not self.current_contract:
            logger.warning("⚠️ [VERIFY] No contract set, using default verification")
            return VerificationResult(
                step_id=result.step_id,
                verified=True,
                confidence=VerificationConfidence.MEDIUM,
                recommended_action="continue",
            )

        # Get current step if available
        current_step = None
        if self.current_contract.steps:
            idx = self.current_contract.current_step_index
            current_step = (
                self.current_contract.steps[idx]
                if idx < len(self.current_contract.steps)
                else self.current_contract.steps[0]
            )

        if not current_step:
            return VerificationResult(
                step_id=result.step_id,
                verified=True,
                confidence=VerificationConfidence.MEDIUM,
                recommended_action="continue",
            )

        verification = self.verifier.verify_step(
            current_step, result, self.last_snapshot
        )
        self.last_verification = verification
        if not verification.verified:
            self.record_failure_code(
                self.verifier.classify_verification_failure(result, self.last_snapshot)
            )
        return verification

    def attempt_repair(
        self,
        step,
        result: ExecutionResult,
        verification: Optional[VerificationResult] = None,
    ) -> RepairAction:
        """[REPAIR]: Attempt to recover from failure."""
        repair = self.repair_engine.choose_repair_action(
            step, result, verification or self.last_verification
        )
        logger.info(f"🔧 [REPAIR] {repair.action.value}: {repair.reason}")
        return repair.action

    def record_failure(self, failure: Dict[str, Any]):
        """[FAILURE]: Record a failure for pattern learning."""
        self.failure_history.append(failure)
        if failure.get("code"):
            self.record_failure_code(str(failure["code"]))
        logger.info(f"🚨 [FAILURE] Recorded: {failure.get('code', 'UNKNOWN')}")

    def can_retry(self) -> bool:
        """[RETRY]: Check if retry is allowed."""
        return self.retry_count < self.max_retries

    def increment_retry(self):
        """[RETRY]: Increment retry counter."""
        self.retry_count += 1
        logger.info(f"🔁 [RETRY] Attempt {self.retry_count}/{self.max_retries}")


# ═══════════════════════════════════════════════════════════════
#  INTEGRATION TEST
# ═══════════════════════════════════════════════════════════════

# Singleton
_state_manager = None


def get_state_manager(max_steps: int = 50) -> "StateManager":
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager(max_steps=max_steps)
    return _state_manager


if __name__ == "__main__":
    sm = StateManager(max_steps=5)
    sm.transition_to(MissionState.PLANNING, "User requested AuditFlow research")
    sm.transition_to(MissionState.RISK_CHECK, "Checking action risk")
    sm.transition_to(MissionState.EXECUTING, "Running browser search")
    sm.transition_to(MissionState.OBSERVING, "Capturing semantic state")
    sm.transition_to(MissionState.VALIDATING, "Verifying results")
    sm.transition_to(MissionState.REPAIRING, "Retrying search")
    sm.transition_to(MissionState.SUCCESS, "Mission complete")

    print(f"🏁 Final State: {sm.current_state.value}")
    print(f"📊 Steps: {sm.step_count}")
    print(f"📋 Failures: {len(sm.failure_history)}")
