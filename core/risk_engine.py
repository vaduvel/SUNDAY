"""
J.A.R.V.I.S. Risk Engine
========================

Clasifică riscul fiecărei acțiuni și gestionează aprobările.

Based on JARVIS V2 Blueprint Section 4.2
"""

from typing import Dict, Any, Optional, List, Literal
from dataclasses import dataclass, field
from enum import Enum
import logging
import re

from core.task_contracts import TaskRisk, PlanStep

logger = logging.getLogger(__name__)

RISK_ORDER = {
    TaskRisk.R0: 0,
    TaskRisk.R1: 1,
    TaskRisk.R2: 2,
    TaskRisk.R3: 3,
}


class ApprovalState(Enum):
    """Stare aprobare"""

    AUTO_APPROVED = "AUTO_APPROVED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"


@dataclass
class RiskAssessment:
    """Evaluare risc pentru un pas"""

    risk_level: TaskRisk
    requires_approval: bool
    approval_level: str  # "none", "user", "admin"
    reasons: List[str] = field(default_factory=list)
    block_reason: Optional[str] = None


@dataclass
class ApprovalRequest:
    """Cerere de aprobare"""

    step_id: str
    risk_level: TaskRisk
    action_description: str
    reason: str
    timestamp: float
    timeout_seconds: int = 60
    state: ApprovalState = ApprovalState.PENDING


class RiskEngine:
    """
    Engine pentru clasificarea riscului și gestionarea aprobărilor.

    Risk Levels:
    - R0: Read-only (liber)
    - R1: Low-risk local write (liber cu log)
    - R2: External side effects (aprobare scurtă)
    - R3: High-risk / irreversible (aprobare explicită)
    """

    def __init__(self):
        self.pending_approvals: Dict[str, ApprovalRequest] = {}

        # Risk classification rules
        self.tool_risk_map: Dict[str, TaskRisk] = {
            # R0 - Read-only
            "search_tool": TaskRisk.R0,
            "browser_search": TaskRisk.R0,
            "memory_search": TaskRisk.R0,
            "file_read": TaskRisk.R0,
            "get_status": TaskRisk.R0,
            "screenshot": TaskRisk.R0,
            "get_mouse_position": TaskRisk.R0,
            "browser_extract": TaskRisk.R0,
            "browser_structured_extract": TaskRisk.R0,
            "browser_subtask": TaskRisk.R0,
            "browser_status": TaskRisk.R0,
            "stagehand_extract": TaskRisk.R0,
            "stagehand_observe": TaskRisk.R0,
            "voice_status": TaskRisk.R0,
            "voice_session_status": TaskRisk.R0,
            "computer_observe_screen": TaskRisk.R0,
            "computer_assert_change": TaskRisk.R0,
            # R1 - Low-risk local write
            "file_write": TaskRisk.R1,
            "create_folder": TaskRisk.R1,
            "write_code": TaskRisk.R1,
            "launch_app": TaskRisk.R1,
            "mouse_move": TaskRisk.R1,
            "mouse_click": TaskRisk.R1,
            "voice_speak": TaskRisk.R1,
            "voice_listen": TaskRisk.R1,
            "voice_session_start": TaskRisk.R1,
            "voice_session_listen": TaskRisk.R1,
            "voice_session_stop": TaskRisk.R1,
            "voice_session_cancel": TaskRisk.R1,
            "computer_type_verified": TaskRisk.R1,
            # R2 - External side effects
            "browser_navigate": TaskRisk.R2,
            "browser_click": TaskRisk.R2,
            "browser_type": TaskRisk.R2,
            "browser_task": TaskRisk.R2,
            "stagehand_act": TaskRisk.R2,
            "computer_task": TaskRisk.R2,
            "computer_open_app": TaskRisk.R2,
            "computer_click_target": TaskRisk.R2,
            "terminal": TaskRisk.R2,
            "send_notification": TaskRisk.R2,
            # R3 - High-risk
            "delete_file": TaskRisk.R3,
            "delete_folder": TaskRisk.R3,
            "sudo": TaskRisk.R3,
            "format": TaskRisk.R3,
            "shutdown": TaskRisk.R3,
        }

        # Keywords that elevate risk
        self.risk_keywords = {
            TaskRisk.R1: ["create", "new", "write", "save"],
            TaskRisk.R2: ["send", "post", "upload", "download", "navigate"],
            TaskRisk.R3: [
                "buy",
                "purchase",
                "checkout",
                "cart",
                "order",
                "subscribe",
                "subscription",
                "billing",
                "invoice",
                "payment",
                "pay",
                "spend",
                "bank",
                "wallet",
                "credit card",
                "debit card",
                "iban",
                "wire",
                "transfer",
                "delete",
                "remove",
                "sudo",
                "format",
                "shutdown",
                "reboot",
                "rm -rf",
                "drop",
                "execute",
                "eval",
                "exec",
                "credential",
                "password",
                "key",
                "secret",
                "api_key",
            ],
        }

        # Callback for approval requests
        self.on_approval_needed = None
        self.on_action_blocked = None

    def classify_step_risk(self, step: PlanStep) -> RiskAssessment:
        """
        Clasifică riscul unui pas.

        Returns:
            RiskAssessment cu nivelul de risc și dacă necesită aprobare
        """
        reasons = []
        base_risk = TaskRisk.R0

        # Check tool candidates
        for tool in step.tool_candidates:
            tool_risk = self.tool_risk_map.get(tool, TaskRisk.R1)
            if RISK_ORDER[tool_risk] > RISK_ORDER[base_risk]:
                base_risk = tool_risk
                reasons.append(f"Tool {tool} is {tool_risk.value}")

        # Check for risk keywords in description
        desc_lower = step.description.lower()
        for risk_level, keywords in self.risk_keywords.items():
            for keyword in keywords:
                pattern = (
                    re.escape(keyword)
                    if any(char in keyword for char in " -_/")
                    else rf"\b{re.escape(keyword)}\b"
                )
                if re.search(pattern, desc_lower) and RISK_ORDER[risk_level] > RISK_ORDER[base_risk]:
                    base_risk = risk_level
                    reasons.append(f"Found keyword: {keyword}")

        # Check success criteria for dangerous operations
        criteria_lower = step.success_criteria.description.lower()
        for keyword in self.risk_keywords[TaskRisk.R3]:
            pattern = (
                re.escape(keyword)
                if any(char in keyword for char in " -_/")
                else rf"\b{re.escape(keyword)}\b"
            )
            if re.search(pattern, criteria_lower):
                base_risk = TaskRisk.R3
                reasons.append(f"Success criteria contains: {keyword}")

        # Determine approval requirements
        requires_approval = False
        approval_level = "none"

        if base_risk == TaskRisk.R0:
            approval_level = "none"
        elif base_risk == TaskRisk.R1:
            approval_level = "none"  # Auto-approved with logging
        elif base_risk == TaskRisk.R2:
            requires_approval = True
            approval_level = "user"
        elif base_risk == TaskRisk.R3:
            requires_approval = True
            approval_level = "admin"

        return RiskAssessment(
            risk_level=base_risk,
            requires_approval=requires_approval,
            approval_level=approval_level,
            reasons=reasons,
        )

    def requires_human_approval(self, step: PlanStep) -> bool:
        """Check if step requires human approval"""
        assessment = self.classify_step_risk(step)
        return assessment.requires_approval

    def check_action(self, action: str, params: Dict) -> RiskAssessment:
        """Check risk for an action (non-step version)"""
        success_desc = params.get("success_desc") or params.get("expected", action)
        temp_step = PlanStep(
            id="temp",
            title=action,
            description=params.get("description") or action,
            tool_candidates=[action],
            success_criteria=params.get("success_criteria")
            or PlanStep.create(
                title=action,
                description=params.get("description") or action,
                tool_candidates=[action],
                success_desc=success_desc,
            ).success_criteria,
        )
        return self.classify_step_risk(temp_step)

    def request_approval(self, step: PlanStep, reason: str = "") -> ApprovalRequest:
        """Request approval for a step"""
        import time

        assessment = self.classify_step_risk(step)

        request = ApprovalRequest(
            step_id=step.id,
            risk_level=assessment.risk_level,
            action_description=step.description,
            reason=reason or "; ".join(assessment.reasons),
            timestamp=time.time(),
            timeout_seconds=60,
            state=ApprovalState.PENDING,
        )

        self.pending_approvals[step.id] = request

        # Call callback if set
        if self.on_approval_needed:
            self.on_approval_needed(request)

        logger.warning(
            f"⚠️ [RISK] Approval required for {step.id} ({assessment.risk_level.value})"
        )

        return request

    def approve(self, step_id: str, approved: bool = True) -> bool:
        """Approve or reject a pending approval"""
        if step_id not in self.pending_approvals:
            return False

        request = self.pending_approvals[step_id]
        request.state = ApprovalState.APPROVED if approved else ApprovalState.REJECTED

        logger.info(
            f"{'✅' if approved else '❌'} [RISK] {'Approved' if approved else 'Rejected'} {step_id}"
        )

        return True

    def get_pending_approval(self, step_id: str) -> Optional[ApprovalRequest]:
        """Get pending approval request"""
        return self.pending_approvals.get(step_id)

    def enforce_policy(self, step: PlanStep, context: Dict) -> Dict[str, Any]:
        """
        Aplică politica de risc pentru un pas.

        Returns:
            Dict cu "allowed" (bool) și "reason" (str)
        """
        assessment = self.classify_step_risk(step)

        if assessment.risk_level == TaskRisk.R3:
            # Always block R3 without explicit approval
            return {
                "allowed": False,
                "reason": "R3 risk requires explicit admin approval",
                "risk_level": assessment.risk_level.value,
                "approval_required": True,
            }

        if assessment.requires_approval:
            # Check if we have approval
            if step.id in self.pending_approvals:
                approval = self.pending_approvals[step.id]
                if approval.state == ApprovalState.APPROVED:
                    return {
                        "allowed": True,
                        "reason": "Approved",
                        "risk_level": assessment.risk_level.value,
                        "approval_required": False,
                    }
                elif approval.state == ApprovalState.REJECTED:
                    return {
                        "allowed": False,
                        "reason": "Approval denied",
                        "risk_level": assessment.risk_level.value,
                        "approval_required": True,
                    }
                else:
                    return {
                        "allowed": False,
                        "reason": "Waiting for approval",
                        "risk_level": assessment.risk_level.value,
                        "approval_required": True,
                    }
            else:
                # Request approval
                self.request_approval(step)
                return {
                    "allowed": False,
                    "reason": "Approval requested",
                    "risk_level": assessment.risk_level.value,
                    "approval_required": True,
                }

        # R0/R1 - auto approve
        return {
            "allowed": True,
            "reason": "Auto-approved",
            "risk_level": assessment.risk_level.value,
            "approval_required": False,
        }

    def get_risk_summary(self) -> Dict[str, Any]:
        """Get summary of risk engine state"""
        return {
            "pending_approvals": len(self.pending_approvals),
            "by_state": {
                "pending": sum(
                    1
                    for a in self.pending_approvals.values()
                    if a.state == ApprovalState.PENDING
                ),
                "approved": sum(
                    1
                    for a in self.pending_approvals.values()
                    if a.state == ApprovalState.APPROVED
                ),
                "rejected": sum(
                    1
                    for a in self.pending_approvals.values()
                    if a.state == ApprovalState.REJECTED
                ),
            },
        }


# ==================== GLOBAL INSTANCE ====================

_risk_engine: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    """Get or create global risk engine"""
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine()
    return _risk_engine


# ==================== TEST ====================

if __name__ == "__main__":
    from core.task_contracts import create_step, TaskRisk

    print("=== RISK ENGINE TEST ===\n")

    engine = get_risk_engine()

    # Test various steps
    test_steps = [
        create_step("Search web", "search_tool", TaskRisk.R0, "Results found"),
        create_step("Write file", "file_write", TaskRisk.R1, "File saved"),
        create_step("Navigate browser", "browser_navigate", TaskRisk.R2, "Page loaded"),
        create_step("Delete file", "delete_file", TaskRisk.R3, "File deleted"),
        create_step("Run sudo command", "sudo", TaskRisk.R3, "Command executed"),
    ]

    for step in test_steps:
        assessment = engine.classify_step_risk(step)
        print(f"Step: {step.title}")
        print(f"  Risk: {assessment.risk_level.value}")
        print(f"  Needs approval: {assessment.requires_approval}")
        print(f"  Approval level: {assessment.approval_level}")
        print(f"  Reasons: {assessment.reasons}")
        print()

    print("✅ Risk Engine test complete!")
