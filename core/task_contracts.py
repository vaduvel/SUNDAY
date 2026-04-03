"""
J.A.R.V.I.S. Task Contracts
============================

Contractele interne pentru taskuri, pași și rezultate.
Definește structura standardizată pentru toate misiunile.

Based on JARVIS V2 Blueprint Section 4.1
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, List, Dict, Mapping
from enum import Enum
from datetime import datetime
import uuid


# ==================== ENUMS ====================


class TaskRisk(str, Enum):
    """Nivel de risc pentru task-uri (R0-R3)"""

    R0 = "R0"  # Read-only
    R1 = "R1"  # Low-risk local write
    R2 = "R2"  # External side effects
    R3 = "R3"  # High-risk / irreversible


class TaskStatus(str, Enum):
    """Status misiune"""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    RISK_REVIEW = "RISK_REVIEW"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    ABORTED = "ABORTED"


class ExecutionStatus(str, Enum):
    """Status execuție pas"""

    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"


class ToolResponseStatus(str, Enum):
    """Canonical tool response status aligned with the blueprint."""

    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"


class VerificationConfidence(str, Enum):
    """Nivel de încredere verificare"""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ==================== DATA CLASSES ====================


@dataclass
class SuccessCriteria:
    """Criterii de succes pentru un pas"""

    description: str
    observable_signals: List[str] = field(default_factory=list)
    required_artifacts: List[str] = field(default_factory=list)
    verification_method: str = (
        "default"  # "exact_match", "contains", "semantic", "artifact_exists"
    )


@dataclass
class PlanStep:
    """Un pas în planul de execuție"""

    id: str
    title: str
    description: str
    tool_candidates: List[str]
    success_criteria: SuccessCriteria
    risk: TaskRisk = TaskRisk.R0

    # Metadata
    estimated_duration_sec: int = 30
    max_retries: int = 2
    dependencies: List[str] = field(default_factory=list)

    # Runtime state
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0

    @staticmethod
    def create(
        title: str,
        description: str,
        tool_candidates: List[str],
        risk: TaskRisk = TaskRisk.R0,
        success_desc: str = "Success",
    ):
        """Factory method pentru creare rapidă"""
        return PlanStep(
            id=f"step_{uuid.uuid4().hex[:8]}",
            title=title,
            description=description,
            tool_candidates=tool_candidates,
            success_criteria=SuccessCriteria(description=success_desc),
            risk=risk,
        )


@dataclass
class ExecutionResult:
    """Rezultatul execuției unui pas"""

    step_id: str
    tool_name: str
    raw_output: Any

    # Standardized output
    artifacts: List[str] = field(default_factory=list)
    status: ExecutionStatus = ExecutionStatus.UNCERTAIN
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    # Timing
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    duration_sec: float = 0.0

    # Observabil
    observed_signals: List[str] = field(default_factory=list)
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def mark_complete(self, success: bool, error: str = None):
        """Mark execution as complete"""
        self.status = ExecutionStatus.SUCCESS if success else ExecutionStatus.FAIL
        self.end_time = datetime.now()
        self.duration_sec = (self.end_time - self.start_time).total_seconds()
        if error:
            self.error_message = error

    def as_tool_response(self) -> Dict[str, Any]:
        """Return a canonical tool response payload for logging or verification."""
        return normalize_tool_response(
            tool_name=self.tool_name,
            result=self.raw_output,
            error_code=self.error_code,
            error_message=self.error_message,
            observed_signals=self.observed_signals,
            artifacts=self.artifacts,
            metadata=self.metadata,
            success=self.status == ExecutionStatus.SUCCESS,
        )


@dataclass
class VerificationResult:
    """Rezultatul verificării unui pas"""

    step_id: str
    verified: bool
    confidence: VerificationConfidence

    # Evidence
    evidence: List[str] = field(default_factory=list)
    mismatch_reason: Optional[str] = None

    # Details
    expected: Optional[str] = None
    observed: Optional[str] = None

    # Recommendation
    recommended_action: Literal["continue", "retry", "replan", "escalate"] = "continue"


@dataclass
class TaskContract:
    """Contract complet pentru o misiune"""

    mission_id: str
    user_input: str

    # Plan
    steps: List[PlanStep] = field(default_factory=list)

    # Risk
    overall_risk: TaskRisk = TaskRisk.R0
    requires_approval: bool = False

    # State
    status: TaskStatus = TaskStatus.PENDING
    current_step_index: int = 0

    # Results
    execution_results: List[ExecutionResult] = field(default_factory=list)
    verification_results: List[VerificationResult] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Context
    context: Dict[str, Any] = field(default_factory=dict)

    def get_current_step(self) -> Optional[PlanStep]:
        """Get current step being executed"""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def mark_step_complete(
        self, step_id: str, result: ExecutionResult, verification: VerificationResult
    ):
        """Mark a step as complete with results"""
        self.execution_results.append(result)
        self.verification_results.append(verification)

        # Update step status
        for step in self.steps:
            if step.id == step_id:
                if verification.verified:
                    step.status = TaskStatus.VERIFIED
                else:
                    step.status = TaskStatus.FAILED
                break

    def is_complete(self) -> bool:
        """Check if mission is complete"""
        return self.status in [
            TaskStatus.SUCCESS,
            TaskStatus.FAILURE,
            TaskStatus.ABORTED,
        ]

    def success_rate(self) -> float:
        """Calculate success rate"""
        if not self.verification_results:
            return 0.0
        verified_count = sum(1 for v in self.verification_results if v.verified)
        return verified_count / len(self.verification_results)


# ==================== FAILURE TAXONOMY ====================


class FailureCode(str, Enum):
    """Taxonomia standardizată de eșecuri"""

    # Planning
    PLANNING_FAIL = "PLANNING_FAIL"
    GOAL_AMBIGUOUS = "GOAL_AMBIGUOUS"

    # Risk
    RISK_POLICY_BLOCK = "RISK_POLICY_BLOCK"
    APPROVAL_DENIED = "APPROVAL_DENIED"

    # Tool
    TOOL_NOT_AVAILABLE = "TOOL_NOT_AVAILABLE"
    TOOL_ARGUMENT_INVALID = "TOOL_ARGUMENT_INVALID"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_RUNTIME_ERROR = "TOOL_RUNTIME_ERROR"

    # Observation
    OBSERVATION_FAIL = "OBSERVATION_FAIL"
    UI_GROUNDING_FAIL = "UI_GROUNDING_FAIL"
    STATE_DRIFT = "STATE_DRIFT"

    # Verification
    VERIFICATION_FAIL = "VERIFICATION_FAIL"
    HALLUCINATED_SUCCESS = "HALLUCINATED_SUCCESS"

    # Memory
    MEMORY_MISRECALL = "MEMORY_MISRECALL"

    # Recovery
    RECOVERY_FAIL = "RECOVERY_FAIL"
    REPLAN_EXHAUSTED = "REPLAN_EXHAUSTED"

    # Unknown
    UNKNOWN = "UNKNOWN"


@dataclass
class ToolResponse:
    """Standardized tool result contract from blueprint section 6."""

    ok: bool
    tool_name: str
    status: ToolResponseStatus
    artifacts: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    observed_signals: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "artifacts": list(self.artifacts),
            "data": dict(self.data),
            "error": self.error,
            "error_code": self.error_code,
            "observed_signals": list(self.observed_signals),
            "timestamp": self.timestamp,
        }


def normalize_tool_response(
    tool_name: str,
    result: Any,
    *,
    success: Optional[bool] = None,
    status: Optional[str] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    observed_signals: Optional[List[str]] = None,
    artifacts: Optional[List[str]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize ad-hoc tool outputs into a canonical contract without changing callers."""
    payload = result if isinstance(result, Mapping) else {"value": result}
    derived_success = bool(payload.get("success", True)) if success is None else bool(success)
    derived_status = status or payload.get("status")
    if not derived_status:
        derived_status = (
            ToolResponseStatus.SUCCESS.value
            if derived_success
            else ToolResponseStatus.FAIL.value
        )

    response = ToolResponse(
        ok=derived_success,
        tool_name=tool_name,
        status=ToolResponseStatus(derived_status)
        if derived_status in {item.value for item in ToolResponseStatus}
        else ToolResponseStatus.PARTIAL,
        artifacts=list(artifacts or payload.get("artifacts", [])),
        data=dict(payload),
        error=error_message or payload.get("error"),
        error_code=error_code or payload.get("error_code"),
        observed_signals=list(
            observed_signals or payload.get("observed_signals") or payload.get("signals", [])
        ),
    )
    if metadata:
        response.data.setdefault("metadata", dict(metadata))
    return response.to_dict()


# ==================== FACTORY FUNCTIONS ====================


def create_mission(user_input: str, context: Dict = None) -> TaskContract:
    """Creează o nouă misiune cu contract"""
    return TaskContract(
        mission_id=f"mission_{uuid.uuid4().hex[:12]}",
        user_input=user_input,
        context=context or {},
    )


def create_step(
    title: str, tool: str, risk: TaskRisk = TaskRisk.R0, success_desc: str = "Success"
) -> PlanStep:
    """Helper pentru creare rapidă de pas"""
    return PlanStep.create(
        title=title,
        description=title,
        tool_candidates=[tool],
        risk=risk,
        success_desc=success_desc,
    )


# ==================== SERIALIZATION ====================


def contract_to_dict(contract: TaskContract) -> Dict:
    """Serialize contract to dict for logging/JSON"""
    return {
        "mission_id": contract.mission_id,
        "user_input": contract.user_input,
        "status": contract.status.value,
        "overall_risk": contract.overall_risk.value,
        "steps": [
            {
                "id": s.id,
                "title": s.title,
                "risk": s.risk.value,
                "status": s.status.value,
            }
            for s in contract.steps
        ],
        "verification_summary": {
            "total": len(contract.verification_results),
            "verified": sum(1 for v in contract.verification_results if v.verified),
        },
        "created_at": contract.created_at.isoformat(),
        "completed_at": contract.completed_at.isoformat()
        if contract.completed_at
        else None,
    }


# ==================== TEST ====================

if __name__ == "__main__":
    # Test contract creation
    print("=== TASK CONTRACTS TEST ===\n")

    # Create mission
    mission = create_mission(
        "Caută informații despre AI și creează un raport",
        {"user": "test", "session": "123"},
    )
    print(f"Created mission: {mission.mission_id}")

    # Add steps
    mission.steps.append(
        create_step("Search web", "search_tool", TaskRisk.R0, "Results found")
    )
    mission.steps.append(
        create_step("Analyze results", "brain", TaskRisk.R0, "Analysis complete")
    )
    mission.steps.append(
        create_step("Write report", "file_tool", TaskRisk.R1, "File saved")
    )

    print(f"Added {len(mission.steps)} steps")

    # Test execution result
    result = ExecutionResult(
        step_id=mission.steps[0].id,
        tool_name="search_tool",
        raw_output={"results": ["AI is..."]},
        artifacts=["/tmp/results.json"],
    )
    result.mark_complete(True)
    print(f"Execution result: {result.status.value}, duration: {result.duration_sec}s")

    # Test verification
    verification = VerificationResult(
        step_id=mission.steps[0].id,
        verified=True,
        confidence=VerificationConfidence.HIGH,
        evidence=["result_count > 0"],
        recommended_action="continue",
    )
    print(
        f"Verification: {verification.verified}, confidence: {verification.confidence.value}"
    )

    # Test contract serialization
    print(f"\nContract to dict: {contract_to_dict(mission)['mission_id']}")

    print("\n✅ All tests passed!")
