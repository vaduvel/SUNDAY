"""
J.A.R.V.I.S. VERIFIER SYSTEM
============================

Verificator separat pentru JARVIS - post-action verification.

Funcționalități:
- Verifică output-ul după fiecare tool call
- Compară "crezut" vs "observat"
- Loghează diferențele
- Decide dacă să continue sau să retry
- Classification eșecuri
"""

import time
import asyncio
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class VerificationStatus(Enum):
    """Status verificare"""

    PASSED = "passed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    NEEDS_RETRY = "needs_retry"
    NEEDS_APPROVAL = "needs_approval"


class FailureType(Enum):
    """Tipuri de eșec"""

    NONE = "none"
    OUTPUT_MISMATCH = "output_mismatch"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    INVALID_STATE = "invalid_state"
    UNEXPECTED = "unexpected"


@dataclass
class VerificationResult:
    """Rezultat verificare"""

    status: VerificationStatus
    failure_type: FailureType
    expected: str  # Ce credeam că o să se întâmple
    observed: str  # Ce am observat efectiv
    difference: Optional[str]  # Diferența dintre expected și observed
    suggestion: Optional[str]  # Sugestie pentru recovery
    timestamp: float = field(default_factory=time.time)


@dataclass
class ActionRecord:
    """Înregistrare acțiune pentru verificare"""

    action_type: str
    params: Dict[str, Any]
    expected_result: str
    actual_result: Any
    success: bool
    timestamp: float = field(default_factory=time.time)


class Verifier:
    """
    Verificator pentru JARVIS - verifică după fiecare acțiune importantă.

    Flow:
    1. Înainte de acțiune: capture expected state
    2. După acțiune: capture actual state
    3. Compare: expected vs observed
    4. Decide: continue/retry/approval/fail
    """

    def __init__(self):
        self.action_history: List[ActionRecord] = []
        self.verification_history: List[VerificationResult] = []

        # Verificatori specifici pe tip
        self.verifiers: Dict[str, Callable] = {
            "file_write": self._verify_file_write,
            "file_read": self._verify_file_read,
            "search": self._verify_search,
            "computer_screenshot": self._verify_screenshot,
            "computer_mouse_click": self._verify_mouse_click,
            "computer_keyboard_type": self._verify_keyboard,
            "terminal": self._verify_terminal,
            "launch": self._verify_app_launch,
            "browser": self._verify_browser,
        }

        # Pattern-uri de recovery
        self.recovery_patterns = {
            FailureType.OUTPUT_MISMATCH: "Retry cu parametri diferiți sau fallback",
            FailureType.TOOL_ERROR: "Încearcă tool alternativ",
            FailureType.TIMEOUT: "Reduce complexitatea sau crește timeout",
            FailureType.PERMISSION_DENIED: "Cere aprobare sau folosește alternativă",
            FailureType.INVALID_STATE: "Resetează starea și reîncearcă",
        }

    def verify_action(
        self,
        action_type: str,
        params: Dict[str, Any],
        expected: str,
        actual_result: Any,
    ) -> VerificationResult:
        """
        Verifică o acțiune - compară expected vs actual.

        Args:
            action_type: Tipul acțiunii (file_write, search, etc.)
            params: Parametrii acțiunii
            expected: Ce ne așteptăm să se întâmple
            actual_result: Rezultatul actual

        Returns:
            VerificationResult cu status și sugestii
        """

        # Record the action
        record = ActionRecord(
            action_type=action_type,
            params=params,
            expected_result=expected,
            actual_result=actual_result,
            success=self._is_success(action_type, actual_result),
        )
        self.action_history.append(record)

        # Get specific verifier or use default
        verifier = self.verifiers.get(action_type, self._default_verifier)

        try:
            result = verifier(expected, actual_result, params)
            self.verification_history.append(result)
            return result
        except Exception as e:
            # Fallback to uncertain if verifier fails
            return VerificationResult(
                status=VerificationStatus.UNCERTAIN,
                failure_type=FailureType.UNEXPECTED,
                expected=expected,
                observed=str(actual_result),
                difference=f"Verifier error: {str(e)}",
                suggestion="Manual verification needed",
            )

    def _is_success(self, action_type: str, result: Any) -> bool:
        """Determină dacă rezultatul e considerat success"""
        if isinstance(result, dict):
            if result.get("success") is not None:
                return result.get("success", False)
            # For terminal - check returncode
            if "returncode" in result:
                return result.get("returncode") == 0
        return result is not None and result != ""

    # ==================== SPECIFIC VERIFIERS ====================

    def _verify_file_write(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Verifică scriere fișier"""
        if not self._is_success("file_write", actual):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                failure_type=FailureType.TOOL_ERROR,
                expected=expected,
                observed=str(actual),
                difference="File write failed",
                suggestion="Check file permissions or path",
            )

        # Verify file exists
        filename = params.get("filename") or params.get("path", "")
        if filename:
            try:
                import os

                if not os.path.exists(filename):
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        failure_type=FailureType.INVALID_STATE,
                        expected=expected,
                        observed="File not created",
                        difference=f"Expected {filename} to exist",
                        suggestion="Check write permissions",
                    )
            except Exception as e:
                pass

        return VerificationResult(
            status=VerificationStatus.PASSED,
            failure_type=FailureType.NONE,
            expected=expected,
            observed=str(actual),
            difference=None,
            suggestion=None,
        )

    def _verify_file_read(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Verifică citire fișier"""
        if not self._is_success("file_read", actual):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                failure_type=FailureType.TOOL_ERROR,
                expected=expected,
                observed=str(actual),
                difference="File read failed",
                suggestion="Check file exists and permissions",
            )

        # Check if actual has content
        if isinstance(actual, str) and len(actual) > 0:
            return VerificationResult(
                status=VerificationStatus.PASSED,
                failure_type=FailureType.NONE,
                expected=expected,
                observed=f"Read {len(actual)} chars",
                difference=None,
                suggestion=None,
            )

        return VerificationResult(
            status=VerificationStatus.FAILED,
            failure_type=FailureType.OUTPUT_MISMATCH,
            expected=expected,
            observed="Empty or no content",
            difference="Expected content but got empty",
            suggestion="Check file path or encoding",
        )

    def _verify_search(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Verifică search results"""
        if not self._is_success("search", actual):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                failure_type=FailureType.TOOL_ERROR,
                expected=expected,
                observed=str(actual),
                difference="Search failed",
                suggestion="Check internet connection or try different query",
            )

        # Check if we got results
        if isinstance(actual, (list, str)) and len(str(actual)) > 10:
            return VerificationResult(
                status=VerificationStatus.PASSED,
                failure_type=FailureType.NONE,
                expected=expected,
                observed=f"Got search results",
                difference=None,
                suggestion=None,
            )

        return VerificationResult(
            status=VerificationStatus.FAILED,
            failure_type=FailureType.OUTPUT_MISMATCH,
            expected=expected,
            observed="No results",
            difference="Expected results but got none",
            suggestion="Try different search terms",
        )

    def _verify_screenshot(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Verifică screenshot"""
        if not self._is_success("screenshot", actual):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                failure_type=FailureType.TOOL_ERROR,
                expected=expected,
                observed=str(actual),
                difference="Screenshot failed",
                suggestion="Check screen recording permission",
            )

        # Check if file path exists
        if isinstance(actual, dict) and actual.get("path"):
            import os

            if os.path.exists(actual["path"]):
                return VerificationResult(
                    status=VerificationStatus.PASSED,
                    failure_type=FailureType.NONE,
                    expected=expected,
                    observed=f"Screenshot saved: {actual['path']}",
                    difference=None,
                    suggestion=None,
                )

        return VerificationResult(
            status=VerificationStatus.UNCERTAIN,
            failure_type=FailureType.INVALID_STATE,
            expected=expected,
            observed=str(actual),
            difference="Screenshot unclear",
            suggestion="Verify manually",
        )

    def _verify_mouse_click(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Verifică mouse click"""
        if not self._is_success("mouse_click", actual):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                failure_type=FailureType.TOOL_ERROR,
                expected=expected,
                observed=str(actual),
                difference="Click failed",
                suggestion="Check element exists or try different coordinates",
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            failure_type=FailureType.NONE,
            expected=expected,
            observed="Click executed",
            difference=None,
            suggestion=None,
        )

    def _verify_keyboard(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Verifică keyboard input"""
        if not self._is_success("keyboard", actual):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                failure_type=FailureType.TOOL_ERROR,
                expected=expected,
                observed=str(actual),
                difference="Keyboard input failed",
                suggestion="Check app is in focus",
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            failure_type=FailureType.NONE,
            expected=expected,
            observed="Keyboard input sent",
            difference=None,
            suggestion=None,
        )

    def _verify_terminal(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Verifică command terminal"""
        if not self._is_success("terminal", actual):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                failure_type=FailureType.TOOL_ERROR,
                expected=expected,
                observed=str(actual),
                difference="Terminal command failed",
                suggestion="Check command syntax",
            )

        # Check return code
        if isinstance(actual, dict):
            retcode = actual.get("returncode", 0)
            if retcode != 0:
                stderr = actual.get("stderr", "")
                return VerificationResult(
                    status=VerificationStatus.FAILED,
                    failure_type=FailureType.OUTPUT_MISMATCH,
                    expected=expected,
                    observed=f"Exit code: {retcode}",
                    difference=f"Command failed: {stderr[:100]}",
                    suggestion="Check command or fix error",
                )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            failure_type=FailureType.NONE,
            expected=expected,
            observed="Command executed",
            difference=None,
            suggestion=None,
        )

    def _verify_app_launch(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Verifică launch app"""
        if not self._is_success("launch", actual):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                failure_type=FailureType.TOOL_ERROR,
                expected=expected,
                observed=str(actual),
                difference="App launch failed",
                suggestion="Check app exists",
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            failure_type=FailureType.NONE,
            expected=expected,
            observed="App launched",
            difference=None,
            suggestion=None,
        )

    def _verify_browser(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Verifică browser action"""
        if not self._is_success("browser", actual):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                failure_type=FailureType.TOOL_ERROR,
                expected=expected,
                observed=str(actual),
                difference="Browser action failed",
                suggestion="Check browser or internet",
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            failure_type=FailureType.NONE,
            expected=expected,
            observed="Browser action completed",
            difference=None,
            suggestion=None,
        )

    def _default_verifier(
        self, expected: str, actual: Any, params: Dict
    ) -> VerificationResult:
        """Default verifier pentru acțiuni necunoscute"""
        if self._is_success("default", actual):
            return VerificationResult(
                status=VerificationStatus.PASSED,
                failure_type=FailureType.NONE,
                expected=expected,
                observed=str(actual)[:200],
                difference=None,
                suggestion=None,
            )

        return VerificationResult(
            status=VerificationStatus.FAILED,
            failure_type=FailureType.UNEXPECTED,
            expected=expected,
            observed=str(actual)[:200],
            difference="Unknown action failed",
            suggestion="Manual verification needed",
        )

    # ==================== RECOVERY LOGIC ====================

    def should_retry(self, result: VerificationResult) -> bool:
        """Determină dacă trebuie retry"""
        return result.status in [
            VerificationStatus.FAILED,
            VerificationStatus.NEEDS_RETRY,
        ]

    def get_recovery_action(self, result: VerificationResult) -> Optional[str]:
        """Get recovery suggestion based on failure type"""
        if result.failure_type == FailureType.NONE:
            return None

        return self.recovery_patterns.get(
            result.failure_type, "Manual intervention needed"
        )

    def needs_approval(
        self, result: VerificationResult, risk_level: str = "low"
    ) -> bool:
        """Determină dacă e nevoie de aprobare umană"""
        if result.status == VerificationStatus.NEEDS_APPROVAL:
            return True

        # High risk actions always need approval
        high_risk_actions = ["delete", "sudo", "format", "shutdown"]

        if risk_level == "high":
            for action in self.action_history[-3:]:
                if any(
                    risk in action.action_type.lower() for risk in high_risk_actions
                ):
                    return True

        return False

    # ==================== STATS ====================

    def get_verification_stats(self) -> Dict[str, Any]:
        """Get verification statistics"""
        total = len(self.verification_history)
        if total == 0:
            return {"total": 0, "passed": 0, "failed": 0}

        passed = sum(
            1
            for v in self.verification_history
            if v.status == VerificationStatus.PASSED
        )
        failed = sum(
            1
            for v in self.verification_history
            if v.status == VerificationStatus.FAILED
        )

        failure_types = {}
        for v in self.verification_history:
            ft = v.failure_type.value
            failure_types[ft] = failure_types.get(ft, 0) + 1

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total * 100,
            "failure_types": failure_types,
            "retry_suggestions": sum(
                1
                for v in self.verification_history
                if v.suggestion and "retry" in v.suggestion.lower()
            ),
        }


# ==================== GLOBAL INSTANCE ====================

_verifier: Optional[Verifier] = None


def get_verifier() -> Verifier:
    """Get or create global verifier"""
    global _verifier
    if _verifier is None:
        _verifier = Verifier()
    return _verifier


# ==================== TEST ====================

if __name__ == "__main__":
    verifier = get_verifier()

    # Test file write verification
    result = verifier.verify_action(
        action_type="file_write",
        params={"filename": "test.txt"},
        expected="File created successfully",
        actual={"success": True},
    )
    print(f"Verification: {result.status.value} - {result.failure_type.value}")

    # Get stats
    print(f"Stats: {verifier.get_verification_stats()}")
