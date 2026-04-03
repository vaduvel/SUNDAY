"""J.A.R.V.I.S. (NUCLEUS - AUTONOMY DAEMON)

The Subconscious Background Processing loop.
This layer provides JARVIS with 'free will'—allowing him to think,
optimize code, and structure ideas proactively while the user is idle.

V2: Connected to self-improvement loop for actionable thought execution.
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from core.brain import call_brain
from core.orchestrator import PermissionMode

logger = logging.getLogger(__name__)

INVALID_THOUGHT_MARKERS = (
    "error:",
    "brain call timed out",
    "brain call failed",
    "traceback",
    "litellm.",
    "cannot connect to host",
)

ACTIONABLE_KEYWORDS = (
    "implement",
    "fix",
    "connect",
    "add",
    "improve",
    "rescrie",
    "adauga",
    "corecteaza",
    "conecteaza",
    "aplic",
    "modifica",
)


class AutonomyDaemon:
    """The continuous background engine driving spontaneous AI thoughts."""

    def __init__(self):
        self.is_running = False
        self.last_user_interaction = datetime.now()
        self.idle_threshold_seconds = 180  # 3 minutes of idle time
        self.task = None
        self.subconscious_logs: List[str] = []
        self.last_error: Optional[str] = None
        self.max_log_entries = 20

    def ping_user_activity(self):
        """Called whenever the user interacts, resetting the idle timer."""
        self.last_user_interaction = datetime.now()

    def get_recent_thoughts(self) -> List[str]:
        """Fetch JARVIS's background thoughts."""
        valid_entries = [
            entry
            for entry in self.subconscious_logs
            if self._extract_actionable_thought(entry)
        ]
        return valid_entries[-5:]

    def _extract_actionable_thought(self, raw_text: str) -> Optional[str]:
        """Return a normalized autonomous suggestion or None if the payload is invalid."""
        if not raw_text:
            return None

        normalized = raw_text.strip()
        if "Gând Autonom:" in normalized:
            normalized = normalized.split("Gând Autonom:", 1)[1].strip()

        normalized = " ".join(normalized.split())
        lowered = normalized.lower()
        if not normalized:
            return None
        if any(marker in lowered for marker in INVALID_THOUGHT_MARKERS):
            return None
        return normalized

    async def start(self):
        """Awaken the subconscious daemon."""
        if self.is_running:
            return
        self.is_running = True
        logger.info(
            "🧠 [AUTONOMY] Subconscious Daemon Awakened. JARVIS has self-initiative."
        )
        self.task = asyncio.create_task(self._autonomy_loop())

    async def stop(self):
        """Put the daemon to sleep."""
        self.is_running = False
        if self.task:
            self.task.cancel()
            logger.info("🧠 [AUTONOMY] Subconscious Daemon Sleeping.")

    async def _autonomy_loop(self):
        """The core heartbeat of the daemon."""
        while self.is_running:
            await asyncio.sleep(60)  # Check status every minute

            idle_time = (datetime.now() - self.last_user_interaction).total_seconds()

            if idle_time > self.idle_threshold_seconds:
                # The core is mostly idle. Let Jarvis use processing power to think.
                await self._generate_autonomous_thought()
                # Wait 5 minutes before thinking again to conserve compute budget
                await asyncio.sleep(300)

    async def _generate_autonomous_thought(self):
        """JARVIS spends API tokens proactively to devise ideas.

        V2: Now executes actionable thoughts if confidence > 0.7 and contains action keywords.
        """
        logger.info(
            "🧠 [AUTONOMY] Idle state detected. Generating Subconscious Thought..."
        )

        system_prompt = (
            "You are JARVIS's Subconscious. The user is inactive. "
            "Scan hypothetically what a top-tier software engineer would improve in a modern Agent/NextJS app. "
            "You are allowed to propose self-improvements to JARVIS's own code, tests, prompts, workflows, and architecture inside the active workspace. "
            "Prefer ideas that are local, reversible, testable, and useful. "
            "Never propose purchases, subscriptions, billing actions, payments, or anything that spends user money. "
            "If the idea is high-impact or risky, phrase it as an approval-ready proposal for the user. "
            "Format: Start directly with the action. Examples: 'Pot rescrie sistemul de cache pentru a scădea timpul de răspuns la 2ms. Să execut protocolul?' "
            "sau 'Am detectat o metodă de-a scrie un test E2E de integrare pentru Fleet Protcols. Îl pregătesc pentru aprobare?' "
            "Max 2 sentences. Sharp, technical, Romanian language."
            "IMPORTANT: If proposing an action, include a confidence score 0.0-1.0 at the end."
        )

        prompt = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "Genereaza o propunere autonoma actionabila cu confidence score.",
            },
        ]

        try:
            # We use 'creative' profile to allow AI to brainstorm freely
            thought = await call_brain(prompt, profile="creative")
            thought_str = str(thought)

            # Extract confidence score if present
            confidence = 0.5
            try:
                if "confidence:" in thought_str.lower():
                    conf_part = thought_str.lower().split("confidence:")[1].split()[0]
                    confidence = float(conf_part.replace(".", "").replace(",", "."))
            except:
                pass

            actionable = self._extract_actionable_thought(thought_str)
            if not actionable:
                self.last_error = thought_str.strip()[:240]
                logger.debug(
                    "⚠️ [AUTONOMY] Ignoring invalid subconscious payload: %s",
                    self.last_error,
                )
                return

            # V2: Check if thought is actionable and execute
            thought_lower = actionable.lower()
            is_actionable = any(kw in thought_lower for kw in ACTIONABLE_KEYWORDS)

            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] Gând Autonom: {actionable}"

            if self.subconscious_logs and self.subconscious_logs[-1].endswith(
                actionable
            ):
                logger.info("🧠 [AUTONOMY] Duplicate thought suppressed.")
                return

            # Execute if actionable and confidence > 0.7
            if is_actionable and confidence > 0.7:
                logger.info(
                    f"🎯 [AUTONOMY] Actionable thought detected (confidence: {confidence})"
                )
                log_entry += f" [ACTIONABLE - executing]"

                # Trigger self-improvement loop
                try:
                    from core.self_improvement_loop import run_self_improvement

                    result = await run_self_improvement(scope="all", dry_run=True)
                    logger.info(
                        f"🔧 [AUTONOMY] Self-improvement result: {result.get('gaps_found', 0)} gaps found"
                    )
                    log_entry += (
                        f" -> Self-improvement: {result.get('gaps_found', 0)} gaps"
                    )
                except Exception as si_error:
                    logger.error(f"❌ [AUTONOMY] Self-improvement failed: {si_error}")
                    log_entry += f" [SELF-IMPROVEMENT ERROR: {str(si_error)[:50]}]"
            else:
                logger.info(
                    f"💡 [AUTONOMY] Thought logged (confidence: {confidence}, actionable: {is_actionable})"
                )

            self.last_error = None
            self.subconscious_logs.append(log_entry)
            self.subconscious_logs = self.subconscious_logs[-self.max_log_entries :]
            logger.info(f"✨ [EUREKA] {log_entry}")

        except Exception as e:
            self.last_error = str(e)
            logger.error(f"❌ [AUTONOMY] Subconscious failure: {e}")


# Global Singleton for system-wide access
jarvis_daemon = AutonomyDaemon()
