"""J.A.R.V.I.S. (GALAXY NUCLEUS - RESULT BUDGETING & SLOT RESERVATION)

Claude Code's Result Budgeting:
- Per-tool size limits
- Aggregate conversation budget
- Persist oversized results to disk
- Slot reservation: 8K default, escalate to 64K on hit
"""

import os
import logging
import hashlib
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ResultBudget:
    """
    Manages tool output size limits to prevent context bloat.
    """

    # Per-tool size limits (characters)
    TOOL_LIMITS = {
        "execute_command": 30000,  # Bash output
        "file_read": None,  # Infinity - self-bounds via tokens
        "file_write": 100000,  # Write confirmation
        "duck_duck_go_search": 10000,  # Search results
        "obsidian_search": 10000,  # Vault results
        "memory_summary": 5000,  # Memory output
        "search_memory": 5000,  # Search results
    }

    # Default for unknown tools
    DEFAULT_LIMIT = 10000

    # Aggregate conversation budget
    CONVERSATION_LIMIT = 500000  # 500K chars total

    def __init__(self, storage_dir: str = None):
        self.storage_dir = storage_dir or os.path.expanduser("~/.jarvis/tool-results")
        os.makedirs(self.storage_dir, exist_ok=True)

        self.used = 0
        self.persisted_files: Dict[str, str] = {}  # tool_id -> file_path

    def check_limit(self, tool_name: str, content: str) -> Dict[str, Any]:
        """
        Check if content exceeds limits.
        Returns: {allowed: bool, content: str, persisted: bool, file: str}
        """
        # Get tool-specific limit
        limit = self.TOOL_LIMITS.get(tool_name, self.DEFAULT_LIMIT)

        # Infinity means self-bounds
        if limit is None:
            return {"allowed": True, "content": content, "persisted": False}

        # Check per-tool limit
        if len(content) > limit:
            return self._persist_content(tool_name, content, limit)

        # Check aggregate limit
        if self.used + len(content) > self.CONVERSATION_LIMIT:
            # Would need to persist some earlier results
            logger.warning(f"⚠️ [BUDGET] Conversation limit approaching")

        return {"allowed": True, "content": content, "persisted": False}

    def _persist_content(
        self, tool_name: str, content: str, limit: int
    ) -> Dict[str, Any]:
        """Persist oversized content to disk."""
        # Create hash for filename
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        filename = f"{tool_name}_{content_hash}.txt"
        filepath = os.path.join(self.storage_dir, filename)

        try:
            # Write preview + full content location
            preview = (
                content[:limit] + f"\n\n... [Output truncated. Full result: {filepath}]"
            )

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            self.persisted_files[filename] = filepath
            self.used += len(content)

            logger.info(f"💾 [BUDGET] Persisted {len(content)} chars to {filename}")

            return {
                "allowed": True,
                "content": preview,
                "persisted": True,
                "file": filepath,
            }
        except Exception as e:
            logger.error(f"❌ [BUDGET] Failed to persist: {e}")
            return {
                "allowed": False,
                "content": f"Output too large ({len(content)} chars) and failed to persist",
                "persisted": False,
            }

    def get_persisted(self, filename: str) -> Optional[str]:
        """Retrieve persisted content."""
        filepath = self.persisted_files.get(filename)
        if filepath and os.path.exists(filepath):
            try:
                return open(filepath, "r", encoding="utf-8").read()
            except:
                return None
        return None

    def reset(self) -> None:
        """Reset budget for new session."""
        self.used = 0
        # Could also clean up old persisted files


# ═══════════════════════════════════════════════════════════════
#  SLOT RESERVATION (Claude Code Pattern)
# ═══════════════════════════════════════════════════════════════


class SlotReservation:
    """
    Claude Code's output slot reservation:
    - Default 8K output tokens
    - Escalates to 64K when limit hit
    - Saves context in 99% of requests
    """

    DEFAULT_SLOT = 8192  # 8K
    ESCALATED_SLOT = 65536  # 64K
    ESCALATION_THRESHOLD = 7500  # Trigger at 7.5K

    def __init__(self):
        self.current_slot = self.DEFAULT_SLOT
        self.escalation_count = 0
        self.max_escalations = 3

    def should_escalate(self, output_tokens: int) -> bool:
        """Check if should escalate to larger slot."""
        if output_tokens >= self.ESCALATION_THRESHOLD:
            if self.escalation_count < self.max_escalations:
                return True
        return False

    def escalate(self) -> Dict[str, Any]:
        """Escalate to larger output slot."""
        if self.current_slot == self.DEFAULT_SLOT:
            self.current_slot = self.ESCALATED_SLOT
            self.escalation_count += 1
            logger.info(f"🚀 [SLOT] Escalated to {self.ESCALATED_SLOT} tokens")
            return {
                "escalated": True,
                "new_slot": self.ESCALATED_SLOT,
                "remaining": self.escalation_count,
            }
        return {"escalated": False, "reason": "Already at max or exhausted"}

    def get_slot(self) -> int:
        """Get current slot size."""
        return self.current_slot

    def reset(self) -> None:
        """Reset for new session."""
        self.current_slot = self.DEFAULT_SLOT
        self.escalation_count = 0


# ═══════════════════════════════════════════════════════════════
#  CONTEXT MODIFIERS
# ═══════════════════════════════════════════════════════════════


class ContextModifier:
    """
    Context modifiers let tools change the execution environment
    for subsequent tools. Only serial tools can produce modifiers.
    """

    @staticmethod
    def plan_mode() -> callable:
        """Enter plan mode (read-only)."""

        def modifier(context: Dict[str, Any]) -> Dict[str, Any]:
            context["permission_mode"] = "plan"
            return context

        return modifier

    @staticmethod
    def set_working_directory(path: str) -> callable:
        """Change working directory."""

        def modifier(context: Dict[str, Any]) -> Dict[str, Any]:
            context["cwd"] = path
            return context

        return modifier

    @staticmethod
    def add_env_var(key: str, value: str) -> callable:
        """Add environment variable."""

        def modifier(context: Dict[str, Any]) -> Dict[str, Any]:
            if "env" not in context:
                context["env"] = {}
            context["env"][key] = value
            return context

        return modifier

    @staticmethod
    def enter_sandbox() -> callable:
        """Enter sandboxed execution."""

        def modifier(context: Dict[str, Any]) -> Dict[str, Any]:
            context["sandboxed"] = True
            return context

        return modifier


# ═══════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════

__all__ = ["ResultBudget", "SlotReservation", "ContextModifier"]
