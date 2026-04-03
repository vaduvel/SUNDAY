"""
J.A.R.V.I.S. Verifier Engine
==============================

Verifică dacă rezultatul pasului este real, nu doar declarat.

Based on JARVIS V2 Blueprint Section 4.4
"""

from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass
from enum import Enum
import logging

from core.task_contracts import (
    PlanStep,
    ExecutionResult,
    VerificationResult,
    VerificationConfidence,
    FailureCode,
)
from core.post_action_observer import SemanticSnapshot

logger = logging.getLogger(__name__)


class VerificationMethod(str, Enum):
    """Metode de verificare"""

    EXACT_MATCH = "exact_match"
    CONTAINS = "contains"
    SEMANTIC = "semantic"
    ARTIFACT_EXISTS = "artifact_exists"
    SIGNAL_DETECTED = "signal_detected"
    STATE_CHANGED = "state_changed"


@dataclass
class VerificationContext:
    """Context pentru verificare"""

    execution_result: ExecutionResult
    observed_state: SemanticSnapshot
    expected_criteria: Dict[str, Any]


class VerifierEngine:
    """
    Engine pentru verificarea rezultatelor.

    Responsabil pentru:
    - compararea rezultatului real cu criteriul de succes
    - detectarea mismatch-ului
    - marcarea pașilor ca verified / failed / uncertain
    """

    def __init__(self):
        self.verification_history = []
        self.hallucination_detector_enabled = True

    def verify_step(
        self,
        step: PlanStep,
        result: ExecutionResult,
        observed_state: SemanticSnapshot | None,
    ) -> VerificationResult:
        """
        Verifică un pas.

        Args:
            step: PlanStep care a fost executat
            result: Rezultatul execuției
            observed_state: Starea observată

        Returns:
            VerificationResult cu verificarea
        """
        criteria = step.success_criteria
        method = criteria.verification_method

        verified = False
        confidence = VerificationConfidence.LOW
        evidence = []
        mismatch_reason = None
        observed_state = observed_state or SemanticSnapshot(
            timestamp=getattr(result, "end_time", None) or result.start_time,
            session_id="unknown",
            step_id=step.id,
        )

        # Check execution status first
        if result.status.value == "FAIL":
            return VerificationResult(
                step_id=step.id,
                verified=False,
                confidence=VerificationConfidence.HIGH,
                evidence=["Execution failed"],
                mismatch_reason=f"Execution status: {result.status.value}",
                recommended_action="retry",
            )

        # Verify based on method
        if method == "exact_match":
            verified, evidence, mismatch_reason = self._verify_exact_match(
                criteria, result, observed_state
            )
        elif method == "contains":
            verified, evidence, mismatch_reason = self._verify_contains(
                criteria, result, observed_state
            )
        elif method == "semantic":
            verified, evidence, mismatch_reason = self._verify_semantic(
                criteria, result, observed_state
            )
        elif method == "artifact_exists":
            verified, evidence, mismatch_reason = self._verify_artifact(
                criteria, result, observed_state
            )
        elif method == "signal_detected":
            verified, evidence, mismatch_reason = self._verify_signal_detected(
                criteria, result, observed_state
            )
        elif method == "state_changed":
            verified, evidence, mismatch_reason = self._verify_state_changed(
                criteria, result, observed_state
            )
        else:  # default
            verified, evidence, mismatch_reason = self._verify_default(
                criteria, result, observed_state
            )

        # Check for hallucinated success
        if verified and self.hallucination_detector_enabled:
            hallucination_check = self._check_hallucination(result, observed_state)
            if hallucination_check["likely_hallucination"]:
                verified = False
                mismatch_reason = (
                    f"Hallucination detected: {hallucination_check['reason']}"
                )
                evidence.extend(hallucination_check["evidence"])

        # Determine confidence based on evidence count
        if len(evidence) >= 3:
            confidence = VerificationConfidence.HIGH
        elif len(evidence) >= 1:
            confidence = VerificationConfidence.MEDIUM
        else:
            confidence = VerificationConfidence.LOW

        # Determine recommended action
        if verified:
            action = "continue"
        elif getattr(result, "retry_count", step.retry_count) < step.max_retries:
            action = "retry"
        else:
            action = "replan"

        verification = VerificationResult(
            step_id=step.id,
            verified=verified,
            confidence=confidence,
            evidence=evidence,
            mismatch_reason=mismatch_reason,
            expected=criteria.description,
            observed=self._summarize_observed(observed_state),
            recommended_action=action,
        )

        # Store in history
        self.verification_history.append(verification)

        logger.info(
            f"{'✅' if verified else '❌'} [VERIFIER] {step.id}: {verification.recommended_action}"
        )

        return verification

    def _verify_exact_match(
        self, criteria, result: ExecutionResult, observed: SemanticSnapshot
    ) -> tuple[bool, list, Optional[str]]:
        """Verificare exact match"""
        evidence = []
        mismatch = None

        # Check observable signals
        for signal in criteria.observable_signals:
            if signal in observed.signals:
                evidence.append(f"Signal detected: {signal}")

        # Check artifacts
        for artifact in criteria.required_artifacts:
            if artifact in observed.files_created or artifact in observed.artifacts:
                evidence.append(f"Artifact found: {artifact}")

        # Check result
        if result.status.value == "SUCCESS":
            evidence.append("Execution succeeded")

        verified = len(evidence) > 0 and result.status.value == "SUCCESS"

        if not verified and not evidence:
            mismatch = "No matching signals or artifacts found"

        return verified, evidence, mismatch

    def _verify_contains(
        self, criteria, result: ExecutionResult, observed: SemanticSnapshot
    ) -> tuple[bool, list, Optional[str]]:
        """Verificare contains (partial match)"""
        evidence = []

        # Check if result contains expected content
        if result.raw_output:
            output_str = str(result.raw_output).lower()
            search_terms = criteria.description.lower().split()

            matches = [term for term in search_terms if term in output_str]
            if matches:
                evidence.append(f"Contains: {', '.join(matches)}")

        # Check signals
        for signal in criteria.observable_signals:
            if signal in observed.signals:
                evidence.append(f"Signal: {signal}")

        verified = len(evidence) > 0

        return verified, evidence, None if verified else "Content not found"

    def _verify_semantic(
        self, criteria, result: ExecutionResult, observed: SemanticSnapshot
    ) -> tuple[bool, list, Optional[str]]:
        """Verificare semantică (simplified)"""
        evidence = []

        # For semantic, we check multiple signals
        # In real implementation, this would use LLM

        # Check execution success
        if result.status.value == "SUCCESS":
            evidence.append("Execution successful")

        # Check signals
        if observed.signals:
            evidence.append(f"Observed signals: {len(observed.signals)}")

        # Check result has content
        if result.raw_output:
            evidence.append("Result has content")

        # Check artifacts if required
        if criteria.required_artifacts:
            if observed.files_created or observed.artifacts:
                evidence.append("Artifacts present")

        verified = result.status.value == "SUCCESS" and len(evidence) >= 2

        return verified, evidence, None if verified else "Semantic check failed"

    def _verify_artifact(
        self, criteria, result: ExecutionResult, observed: SemanticSnapshot
    ) -> tuple[bool, list, Optional[str]]:
        """Verificare artifact exists"""
        evidence = []

        # Check required artifacts exist
        for artifact in criteria.required_artifacts:
            if artifact in observed.files_created:
                evidence.append(f"Artifact exists: {artifact}")
            elif artifact in result.artifacts:
                evidence.append(f"Artifact in result: {artifact}")

        verified = (
            len(evidence) >= len(criteria.required_artifacts)
            if criteria.required_artifacts
            else (result.status.value == "SUCCESS")
        )

        if not verified:
            mismatch = f"Required artifacts not found: {criteria.required_artifacts}"
        else:
            mismatch = None

        return verified, evidence, mismatch

    def _verify_signal_detected(
        self, criteria, result: ExecutionResult, observed: SemanticSnapshot
    ) -> tuple[bool, list, Optional[str]]:
        """Verify that expected signals were actually observed."""
        evidence = []
        missing = []
        for signal in criteria.observable_signals:
            if signal in observed.signals:
                evidence.append(f"Signal detected: {signal}")
            else:
                missing.append(signal)

        verified = bool(evidence) and not missing and result.status.value == "SUCCESS"
        mismatch = None if verified else f"Missing signals: {missing}" if missing else "No expected signals detected"
        return verified, evidence, mismatch

    def _verify_state_changed(
        self, criteria, result: ExecutionResult, observed: SemanticSnapshot
    ) -> tuple[bool, list, Optional[str]]:
        """Verify semantic state changes for grounded browser/desktop actions."""
        evidence = []
        if observed.browser_url:
            evidence.append(f"Browser URL: {observed.browser_url}")
        if observed.browser_dom_hash:
            evidence.append("Browser DOM changed")
        if observed.active_window:
            evidence.append(f"Active window: {observed.active_window}")
        if observed.mouse_position is not None:
            evidence.append(f"Mouse position: {observed.mouse_position}")
        if observed.signals:
            evidence.extend([f"Signal: {signal}" for signal in observed.signals[:4]])

        verified = result.status.value == "SUCCESS" and len(evidence) >= 2
        mismatch = None if verified else "Observed state change was insufficient"
        return verified, evidence, mismatch

    def _verify_default(
        self, criteria, result: ExecutionResult, observed: SemanticSnapshot
    ) -> tuple[bool, list, Optional[str]]:
        """Verificare default"""
        evidence = []

        if result.status.value == "SUCCESS":
            evidence.append("Execution succeeded")

        if observed.signals:
            evidence.append(f"Signals: {', '.join(observed.signals[:3])}")

        if result.artifacts:
            evidence.append(f"Artifacts: {len(result.artifacts)}")

        verified = result.status.value == "SUCCESS"

        return verified, evidence, None if verified else "Verification failed"

    def _check_hallucination(
        self, result: ExecutionResult, observed: SemanticSnapshot
    ) -> Dict[str, Any]:
        """Detectează succes fabricat"""

        # Check: execution said success but no signals observed
        if result.status.value == "SUCCESS" and not observed.signals:
            return {
                "likely_hallucination": True,
                "reason": "Execution reported success but no observable signals",
                "evidence": ["no_signals", "success_claimed"],
            }

        # Check: no artifacts when expected
        # (would need context from criteria)

        return {"likely_hallucination": False, "reason": None, "evidence": []}

    def _summarize_observed(self, observed: SemanticSnapshot) -> str:
        """Summarize observed state for logging"""
        parts = []

        if observed.browser_url:
            parts.append(f"url:{observed.browser_url}")
        if observed.active_window:
            parts.append(f"window:{observed.active_window}")
        if observed.files_created:
            parts.append(f"files:{len(observed.files_created)}")
        if observed.signals:
            parts.append(f"signals:{len(observed.signals)}")

        return ", ".join(parts) if parts else "no_state"

    def verify_artifacts(self, step: PlanStep, artifacts: list) -> VerificationResult:
        """Verify artifacts exist"""
        required = step.success_criteria.required_artifacts

        found = [a for a in artifacts if a in required]

        verified = len(found) >= len(required) if required else True

        return VerificationResult(
            step_id=step.id,
            verified=verified,
            confidence=VerificationConfidence.HIGH
            if verified
            else VerificationConfidence.LOW,
            evidence=[f"Found: {', '.join(found)}"] if found else [],
            mismatch_reason=None
            if verified
            else f"Missing: {set(required) - set(found)}",
            recommended_action="continue" if verified else "retry",
        )

    def classify_verification_failure(
        self, result: ExecutionResult, observed: SemanticSnapshot | None
    ) -> str:
        """Clasifică tipul de eșec al verificării"""
        observed = observed or SemanticSnapshot(
            timestamp=getattr(result, "end_time", None) or result.start_time,
            session_id="unknown",
            step_id=result.step_id,
        )

        if result.status.value == "FAIL":
            if result.error_code in {
                FailureCode.TOOL_NOT_AVAILABLE.value,
                FailureCode.TOOL_ARGUMENT_INVALID.value,
                FailureCode.TOOL_TIMEOUT.value,
                FailureCode.TOOL_RUNTIME_ERROR.value,
            }:
                return result.error_code
            return FailureCode.VERIFICATION_FAIL.value

        if result.status.value == "SUCCESS" and not observed.signals:
            return FailureCode.HALLUCINATED_SUCCESS.value

        if not observed.signals:
            return FailureCode.OBSERVATION_FAIL.value

        return FailureCode.UNKNOWN.value


# ==================== GLOBAL INSTANCE ====================

_verifier_engine: Optional[VerifierEngine] = None


def get_verifier_engine() -> VerifierEngine:
    """Get or create global verifier engine"""
    global _verifier_engine
    if _verifier_engine is None:
        _verifier_engine = VerifierEngine()
    return _verifier_engine


# ==================== TEST ====================

if __name__ == "__main__":
    from core.task_contracts import PlanStep, ExecutionResult, SuccessCriteria
    from core.post_action_observer import SemanticSnapshot
    from datetime import datetime

    print("=== VERIFIER ENGINE TEST ===\n")

    verifier = get_verifier_engine()

    # Create test step
    step = PlanStep(
        id="test_step",
        title="Test step",
        description="Test step",
        tool_candidates=["search_tool"],
        success_criteria=SuccessCriteria(
            description="Results found",
            observable_signals=["search_completed"],
            required_artifacts=["results.json"],
        ),
    )

    # Create test execution result
    result = ExecutionResult(
        step_id=step.id,
        tool_name="search_tool",
        raw_output={"results": ["item1", "item2"]},
        artifacts=["results.json"],
        status="SUCCESS",
    )
    result.mark_complete(True)

    # Create observed state
    observed = SemanticSnapshot(
        timestamp=datetime.now(),
        session_id="test",
        step_id=step.id,
        signals=["search_completed", "page_loaded"],
        files_created=["results.json"],
    )

    # Verify
    verification = verifier.verify_step(step, result, observed)

    print(f"Verified: {verification.verified}")
    print(f"Confidence: {verification.confidence.value}")
    print(f"Evidence: {verification.evidence}")
    print(f"Action: {verification.recommended_action}")

    print("\n✅ Verifier test complete!")
