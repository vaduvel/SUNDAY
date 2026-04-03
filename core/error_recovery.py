"""J.A.R.V.I.S. (GALAXY NUCLEUS - ERROR RECOVERY LADDER)

Claude Code's Error Recovery Pattern:
- Ladder of increasingly aggressive interventions
- Each triggered when previous one fails
- Circuit breakers to prevent infinite loops
"""

import logging
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of recoverable errors."""

    PROMPT_TOO_LONG = "prompt_too_long"
    MAX_OUTPUT_TOKENS = "max_output_tokens"
    MEDIA_SIZE = "media_size"
    RATE_LIMIT = "rate_limit"
    API_ERROR = "api_error"
    UNRECOVERABLE = "unrecoverable"


class RecoveryAction(Enum):
    """Actions in the escalation ladder."""

    # Level 1: Light interventions
    WITHHOLD_ERROR = "withhold_error"  # Don't surface to consumer yet
    CONTEXT_COLLAPSE = "context_collapse"  # Summarize some messages
    RETRY_SAME_MODEL = "retry_same_model"  # Try again immediately

    # Level 2: Medium interventions
    REACTIVE_COMPACT = "reactive_compact"  # Compact on-demand
    ESCALATE_OUTPUT = "escalate_output"  # 8K → 64K output
    FALLBACK_MODEL = "fallback_model"  # Use cheaper model

    # Level 3: Heavy interventions
    MULTI_TURN_RECOVERY = "multi_turn_recovery"  # Continue after output limit
    AUTOCOMPACT = "autocompact"  # Full conversation summary
    SURFACE_ERROR = "surface_error"  # Give up, show error


class ErrorRecoveryLadder:
    """
    Claude Code's error recovery ladder:
    1. Withhold recoverable errors from stream
    2. Context collapse
    3. Reactive compact (on 413)
    4. Output token escalation (8K → 64K)
    5. Multi-turn recovery (up to 3 attempts)
    6. Circuit breakers after 3 failures
    """

    # Circuit breaker limits
    MAX_AUTOCOMPACT_FAILURES = 3
    MAX_OUTPUT_RECOVERY_ATTEMPTS = 3
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self):
        self.autocompact_failures = 0
        self.output_recovery_attempts = 0
        self.consecutive_failures = 0
        self.last_error_type: Optional[ErrorCategory] = None
        self.has_reactive_compact = False  # One-shot per error type

    def classify_error(self, error: Exception) -> ErrorCategory:
        """Classify error into category."""
        error_str = str(error).lower()

        if "413" in error_str or "payload too large" in error_str:
            return ErrorCategory.PROMPT_TOO_LONG
        elif "max_tokens" in error_str or "output token" in error_str:
            return ErrorCategory.MAX_OUTPUT_TOKENS
        elif "rate limit" in error_str or "429" in error_str:
            return ErrorCategory.RATE_LIMIT
        elif "media" in error_str or "image" in error_str:
            return ErrorCategory.MEDIA_SIZE
        elif "api" in error_str or "timeout" in error_str:
            return ErrorCategory.API_ERROR
        else:
            return ErrorCategory.UNRECOVERABLE

    def should_withhold(self, error: Exception) -> bool:
        """Check if error should be withheld (not surfaced yet)."""
        category = self.classify_error(error)

        # Withhold prompt_too_long and max_output until recovery attempted
        return category in [
            ErrorCategory.PROMPT_TOO_LONG,
            ErrorCategory.MAX_OUTPUT_TOKENS,
        ]

    def get_recovery_plan(self, error: Exception) -> Dict[str, Any]:
        """
        Generate recovery plan based on error type.
        Returns action, next steps, and whether to continue.
        """
        category = self.classify_error(error)

        # Check circuit breakers first
        if category == ErrorCategory.PROMPT_TOO_LONG:
            return self._handle_prompt_too_long()
        elif category == ErrorCategory.MAX_OUTPUT_TOKENS:
            return self._handle_max_output_tokens()
        elif category == ErrorCategory.RATE_LIMIT:
            return self._handle_rate_limit()
        elif category == ErrorCategory.API_ERROR:
            return self._handle_api_error()
        else:
            return self._surface_error("Unrecoverable error")

    def _handle_prompt_too_long(self) -> Dict[str, Any]:
        """Handle context window exceeded."""
        # First attempt: reactive compact
        if not self.has_reactive_compact:
            self.has_reactive_compact = True
            return {
                "action": RecoveryAction.REACTIVE_COMPACT,
                "message": "Context exceeded, compacting...",
                "continue": True,
            }

        # Second: try autocompact
        if self.autocompact_failures < self.MAX_AUTOCOMPACT_FAILURES:
            self.autocompact_failures += 1
            return {
                "action": RecoveryAction.AUTOCOMPACT,
                "message": f"Compact failed {self.autocompact_failures}x, retrying...",
                "continue": True,
            }

        # Give up
        return self._surface_error("Context limit exceeded, recovery exhausted")

    def _handle_max_output_tokens(self) -> Dict[str, Any]:
        """Handle output token limit hit."""
        # First: escalate 8K → 64K
        if self.output_recovery_attempts == 0:
            self.output_recovery_attempts += 1
            return {
                "action": RecoveryAction.ESCALATE_OUTPUT,
                "message": "Output limit hit, escalating to 64K...",
                "continue": True,
            }

        # Second: multi-turn recovery (up to 3)
        if self.output_recovery_attempts < self.MAX_OUTPUT_RECOVERY_ATTEMPTS:
            self.output_recovery_attempts += 1
            return {
                "action": RecoveryAction.MULTI_TURN_RECOVERY,
                "message": f"Recovery attempt {self.output_recovery_attempts}/{self.MAX_OUTPUT_RECOVERY_ATTEMPTS}",
                "continue": True,
            }

        # Give up
        return self._surface_error("Output limit recovery exhausted")

    def _handle_rate_limit(self) -> Dict[str, Any]:
        """Handle rate limiting."""
        return {
            "action": RecoveryAction.FALLBACK_MODEL,
            "message": "Rate limited, using fallback model...",
            "continue": True,
        }

    def _handle_api_error(self) -> Dict[str, Any]:
        """Handle transient API errors."""
        if self.consecutive_failures < self.MAX_CONSECUTIVE_FAILURES:
            self.consecutive_failures += 1
            return {
                "action": RecoveryAction.RETRY_SAME_MODEL,
                "message": f"API error, retry {self.consecutive_failures}/{self.MAX_CONSECUTIVE_FAILURES}",
                "continue": True,
            }

        return self._surface_error("Too many API failures")

    def _surface_error(self, message: str) -> Dict[str, Any]:
        """Give up and surface the error."""
        self.consecutive_failures += 1
        return {
            "action": RecoveryAction.SURFACE_ERROR,
            "message": message,
            "continue": False,
        }

    def on_success(self) -> None:
        """Called when recovery succeeded - reset counters."""
        self.consecutive_failures = 0
        self.last_error_type = None

    def reset(self) -> None:
        """Reset all counters for new session."""
        self.autocompact_failures = 0
        self.output_recovery_attempts = 0
        self.consecutive_failures = 0
        self.last_error_type = None
        self.has_reactive_compact = False


# ═══════════════════════════════════════════════════════════════
#  STOP HOOKS (Claude Code Pattern)
# ═══════════════════════════════════════════════════════════════


class StopHook:
    """
    Stop hooks run when model finishes WITHOUT tool use.
    They can force the model to keep working if not actually done.
    """

    def __init__(self):
        self.hooks: List[callable] = []

    def register(self, hook: callable) -> None:
        """Register a stop hook."""
        self.hooks.append(hook)

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run all stop hooks.
        Returns: {preventContinuation: bool, blockingErrors: List[str]}
        """
        blocking_errors = []

        for hook in self.hooks:
            try:
                result = await hook(context)
                if result.get("blocking"):
                    blocking_errors.append(result.get("message", "Unknown error"))
            except Exception as e:
                logger.error(f"❌ [STOP_HOOK] Hook failed: {e}")

        prevent = len(blocking_errors) > 0

        return {"preventContinuation": prevent, "blockingErrors": blocking_errors}


# Example stop hooks
async def linter_check(context: Dict[str, Any]) -> Dict[str, Any]:
    """Check if there are linter errors in recent code changes."""
    # Would check for errors in file modifications
    return {"blocking": False, "message": ""}


async def format_check(context: Dict[str, Any]) -> Dict[str, Any]:
    """Check if code is properly formatted."""
    return {"blocking": False, "message": ""}


# ═══════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════

__all__ = [
    "ErrorRecoveryLadder",
    "ErrorCategory",
    "RecoveryAction",
    "StopHook",
    "linter_check",
    "format_check",
]
