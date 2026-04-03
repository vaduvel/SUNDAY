"""
J.A.R.V.I.S. Risk Tier System
==============================

Sistem de aprobare pe 4 nivele de risc:
- SAFE: Read-only, search, info retrieval
- LOW: File creation, app launching, minor operations
- HIGH: File deletion, terminal commands, system changes (needs approval)
- NEVER: Destructive ops, sudo, format, shutdown (blocked)

Aprobare UX: pentru HIGH risk, userul vede:
- Ce vrea să facă
- De ce
- Ce risc există
- Ce se întâmplă dacă nu face nimic
- Ce opțiuni are
"""

from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import time
import logging

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Nivel de risc"""

    SAFE = "safe"  # Read-only, search
    LOW = "low"  # Minor write operations
    HIGH = "high"  # Needs approval
    NEVER = "never"  # Blocked


class ApprovalState(Enum):
    """Stare aprobare"""

    AUTO_APPROVED = "auto_approved"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


@dataclass
class RiskAction:
    """Acțiune cu risc"""

    action_type: str
    params: Dict[str, Any]
    risk_level: RiskLevel
    description: str
    reason: str
    what_if_denied: str = ""
    timestamp: float = field(default_factory=time.time)
    approval_state: ApprovalState = ApprovalState.PENDING


@dataclass
class ApprovalRequest:
    """Cerere de aprobare pentru UI"""

    request_id: str
    action_description: str
    reason: str
    risk_level: str
    what_if_denied: str
    options: List[str]  # ["approve", "reject", "modify"]
    timestamp: float = field(default_factory=time.time)
    timeout_seconds: int = 60


class RiskTierSystem:
    """
    Sistem de risk tiers pentru JARVIS.

    Flow:
    1. Înainte de orice acțiune, determină risk level
    2. Dacă SAFE - execută automat
    3. Dacă LOW - execută cu log
    4. Dacă HIGH - cere aprobare
    5. Dacă NEVER - blochează

    Aprobare UX:
    - Afișează ce vrea să facă
    - De ce
    - Ce risc
    - Ce opțiuni are userul
    """

    def __init__(self):
        self.pending_requests: Dict[str, ApprovalRequest] = {}
        self.action_log: List[RiskAction] = []

        # Risk classification rules
        self.risk_rules: Dict[str, RiskLevel] = {
            # SAFE - read-only
            "search": RiskLevel.SAFE,
            "read_file": RiskLevel.SAFE,
            "get_status": RiskLevel.SAFE,
            "screenshot": RiskLevel.SAFE,
            "get_mouse_position": RiskLevel.SAFE,
            "memory_search": RiskLevel.SAFE,
            # LOW - minor writes
            "write_file": RiskLevel.LOW,
            "create_folder": RiskLevel.LOW,
            "launch_app": RiskLevel.LOW,
            "mouse_move": RiskLevel.LOW,
            "mouse_click": RiskLevel.LOW,
            "keyboard_type": RiskLevel.LOW,
            "browser": RiskLevel.LOW,
            # HIGH - needs approval
            "delete_file": RiskLevel.HIGH,
            "delete_folder": RiskLevel.HIGH,
            "terminal": RiskLevel.HIGH,
            "run_command": RiskLevel.HIGH,
            "download": RiskLevel.HIGH,
            "upload": RiskLevel.HIGH,
            "open_url": RiskLevel.HIGH,
            # NEVER - blocked
            "sudo": RiskLevel.NEVER,
            "format": RiskLevel.NEVER,
            "shutdown": RiskLevel.NEVER,
            "restart": RiskLevel.NEVER,
            "rm_rf": RiskLevel.NEVER,
            "exec_eval": RiskLevel.NEVER,
        }

        # Keywords that trigger HIGH/NEVER
        self.danger_keywords = {
            RiskLevel.HIGH: [
                "delete",
                "remove",
                "rm ",
                "wget",
                "curl",
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
                "transfer",
                "wire",
                "credit card",
                "debit card",
                "iban",
                "bank",
                "wallet",
            ],
            RiskLevel.NEVER: [
                "sudo",
                "format",
                "shutdown",
                "reboot",
                "rm -rf",
                "eval",
                "exec",
            ],
        }

        # Callbacks
        self.on_approval_needed: Optional[Callable] = None
        self.on_action_blocked: Optional[Callable] = None

    def classify_risk(self, action_type: str, params: Dict[str, Any]) -> RiskLevel:
        """
        Clasifică riscul unei acțiuni.

        Args:
            action_type: Tipul acțiunii (ex: "delete_file")
            params: Parametrii acțiunii

        Returns:
            RiskLevel: SAFE, LOW, HIGH, sau NEVER
        """
        # Check explicit rules first
        base_risk = self.risk_rules.get(action_type, RiskLevel.LOW)

        # Check params for danger keywords
        params_str = str(params).lower()

        # Check for NEVER risk keywords
        for keyword in self.danger_keywords[RiskLevel.NEVER]:
            if keyword in params_str:
                return RiskLevel.NEVER

        # Check for HIGH risk keywords
        for keyword in self.danger_keywords[RiskLevel.HIGH]:
            if keyword in params_str and base_risk != RiskLevel.NEVER:
                return RiskLevel.HIGH

        # Escalate financial/commercial actions to HIGH approval even if action type looks harmless
        for keyword in self.danger_keywords[RiskLevel.HIGH]:
            if keyword in params_str and base_risk == RiskLevel.LOW:
                return RiskLevel.HIGH

        # Check for never actions in action_type
        action_lower = action_type.lower()
        for keyword in self.danger_keywords[RiskLevel.NEVER]:
            if keyword in action_lower:
                return RiskLevel.NEVER

        return base_risk

    def check_action(
        self,
        action_type: str,
        params: Dict[str, Any],
        description: str = "",
        reason: str = "",
    ) -> tuple[RiskLevel, Optional[ApprovalRequest]]:
        """
        Verifică o acțiune și determină dacă necesită aprobare.

        Args:
            action_type: Tipul acțiunii
            params: Parametrii
            description: Descriere pentru UI
            reason: De ce face acțiunea

        Returns:
            (RiskLevel, ApprovalRequest sau None)
        """
        risk_level = self.classify_risk(action_type, params)

        # Create risk action log
        risk_action = RiskAction(
            action_type=action_type,
            params=self._sanitize_params(params),
            risk_level=risk_level,
            description=description or f"Action: {action_type}",
            reason=reason or "User requested",
        )
        self.action_log.append(risk_action)

        # Handle based on risk level
        if risk_level == RiskLevel.SAFE:
            risk_action.approval_state = ApprovalState.AUTO_APPROVED
            return risk_level, None

        elif risk_level == RiskLevel.LOW:
            risk_action.approval_state = ApprovalState.AUTO_APPROVED
            logger.info(f"⚠️ [RISK] LOW risk action: {action_type}")
            return risk_level, None

        elif risk_level == RiskLevel.HIGH:
            # Create approval request
            request = ApprovalRequest(
                request_id=f"req_{int(time.time())}",
                action_description=description or f"Execute: {action_type}",
                reason=reason or "User requested",
                risk_level="HIGH",
                what_if_denied="Acțiunea nu va fi executată. Poți cere o alternativă.",
                options=["approve", "reject", "modify"],
                timeout_seconds=60,
            )
            self.pending_requests[request.request_id] = request
            risk_action.approval_state = ApprovalState.PENDING

            # Call callback if set
            if self.on_approval_needed:
                self.on_approval_needed(request)

            return risk_level, request

        elif risk_level == RiskLevel.NEVER:
            risk_action.approval_state = ApprovalState.REJECTED
            logger.warning(f"🚫 [RISK] BLOCKED: {action_type}")

            # Call callback if set
            if self.on_action_blocked:
                self.on_action_blocked(action_type, params, "Blocked by risk system")

            return risk_level, None

    def approve_request(
        self, request_id: str, approved: bool, modified_params: Optional[Dict] = None
    ) -> bool:
        """
        Aprobă sau respinge o cerere.

        Args:
            request_id: ID-ul cererii
            approved: True = aprobat, False = respins
            modified_params: Parametri modificați (dacă user a modificat)

        Returns:
            bool: True dacă aprobarea a fost procesată
        """
        if request_id not in self.pending_requests:
            return False

        request = self.pending_requests[request_id]

        # Update action log
        for action in reversed(self.action_log):
            if action.approval_state == ApprovalState.PENDING:
                action.approval_state = (
                    ApprovalState.APPROVED if approved else ApprovalState.REJECTED
                )
                if modified_params:
                    action.params.update(modified_params)
                break

        # Remove from pending
        del self.pending_requests[request_id]

        return True

    def get_approval_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get pending approval request"""
        return self.pending_requests.get(request_id)

    def _sanitize_params(self, params: Dict) -> Dict:
        """Sanitize params - remove sensitive data"""
        sanitized = {}
        sensitive_keys = ["password", "api_key", "token", "secret"]

        for k, v in params.items():
            if any(s in k.lower() for s in sensitive_keys):
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = v

        return sanitized

    def get_stats(self) -> Dict[str, Any]:
        """Get risk system statistics"""
        total = len(self.action_log)
        if total == 0:
            return {"total": 0, "by_level": {}, "pending": 0}

        by_level = {"safe": 0, "low": 0, "high": 0, "never": 0}

        for action in self.action_log:
            by_level[action.risk_level.value] += 1

        return {
            "total_actions": total,
            "by_level": by_level,
            "pending_approvals": len(self.pending_requests),
            "auto_approved": sum(
                1
                for a in self.action_log
                if a.approval_state == ApprovalState.AUTO_APPROVED
            ),
            "required_approval": sum(
                1 for a in self.action_log if a.approval_state == ApprovalState.PENDING
            ),
            "blocked": sum(
                1 for a in self.action_log if a.risk_level == RiskLevel.NEVER
            ),
        }

    def format_approval_message(self, request: ApprovalRequest) -> str:
        """Formatează mesaj de aprobare pentru user"""
        return f"""
╔════════════════════════════════════════════════════════════╗
║           ⚠️ APPROVAL REQUIRED - HIGH RISK ACTION           ║
╠════════════════════════════════════════════════════════════╣
║                                                            ║
║  📋 {request.action_description}
║                                                            ║
║  💡 Reason: {request.reason}
║                                                            ║
║  ⚠️  Risk Level: {request.risk_level}
║                                                            ║
║  ℹ️  What if denied: {request.what_if_denied}
║                                                            ║
║  ⏱️  Timeout: {request.timeout_seconds}s
║                                                            ║
╠════════════════════════════════════════════════════════════╣
║  Opțiuni:                                                  ║
║    • [approve] - Execută acțiunea                          ║
║    • [reject] - Anulează                                   ║
║    • [modify] - Modifică parametrii                        ║
╚════════════════════════════════════════════════════════════╝
"""


# ==================== GLOBAL INSTANCE ====================

_risk_system: Optional[RiskTierSystem] = None


def get_risk_system() -> RiskTierSystem:
    """Get or create global risk system"""
    global _risk_system
    if _risk_system is None:
        _risk_system = RiskTierSystem()
    return _risk_system


# ==================== TEST ====================

if __name__ == "__main__":
    risk = get_risk_system()

    # Test various actions
    tests = [
        ("search", {"query": "AI"}, "Search for AI"),
        ("write_file", {"filename": "test.txt"}, "Create test file"),
        ("delete_file", {"path": "/tmp/file.txt"}, "Delete temporary file"),
        ("terminal", {"command": "ls -la"}, "List files"),
        ("sudo", {"command": "rm -rf /"}, "Format disk"),
    ]

    print("=== RISK CLASSIFICATION TEST ===\n")

    for action, params, desc in tests:
        risk_level, request = risk.check_action(action, params, desc)

        status = (
            "✅"
            if risk_level in [RiskLevel.SAFE, RiskLevel.LOW]
            else "⚠️"
            if risk_level == RiskLevel.HIGH
            else "🚫"
        )

        print(f"{status} {action}: {risk_level.value}")

        if request:
            print(risk.format_approval_message(request))

    print("\n=== STATS ===")
    print(risk.get_stats())
