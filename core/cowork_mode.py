"""J.A.R.V.I.S. Co-Work Mode - Always-On Desktop Assistant

This module enables JARVIS to run in "always on" mode, similar to Claude Code.
The AI continuously monitors for user input and can execute actions on the desktop.

Key features:
- Continuous listening for user commands
- Desktop awareness (screen, window, app)
- Action loop: observe -> think -> act -> verify
- Session persistence across commands
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import os

logger = logging.getLogger(__name__)

# Import JARVIS components
try:
    from core.brain import call_brain, PRO_MODEL
    from core.memory_consolidation import get_memory_consolidation
    from core.context_graph import get_context_graph
    from tools.computer_use import get_computer_tool
    from tools.memory_tool import get_structured_memory
except ImportError as e:
    logger.warning(f"Some JARVIS modules not available: {e}")
    call_brain = None
    PRO_MODEL = "openai/mercury-2"


class CoWorkState(Enum):
    """States of the Co-Work mode"""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    EXECUTING = "executing"
    WAITING = "waiting"
    ERROR = "error"


@dataclass
class CoWorkAction:
    """Represents an action taken by JARVIS"""

    action_type: str  # "mouse", "keyboard", "browser", "terminal", "answer"
    description: str
    params: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    success: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class CoWorkSession:
    """Persistent session for Co-Work mode"""

    session_id: str
    start_time: float
    state: CoWorkState
    context: Dict[str, Any]
    action_history: List[CoWorkAction]
    last_input: Optional[str] = None
    last_response: Optional[str] = None


class CoWorkMode:
    """
    Always-On Desktop Assistant Mode for JARVIS.

    Similar to Claude Code's computer use, this enables:
    - Continuous awareness of desktop state
    - Receiving commands at any time
    - Executing multi-step actions on desktop
    - Learning from interactions

    Usage:
        cowork = CoWorkMode()
        await coworker.start()  # Start always-on mode
        # Or process single command:
        result = await coworker.process_command("Open Safari and search for AI")
    """

    def __init__(self, jarvis_root: str = "."):
        self.jarvis_root = Path(jarvis_root)
        self.active = False
        self.session: Optional[CoWorkSession] = None
        self.state = CoWorkState.IDLE

        # Core components
        self.computer = None
        self.memory = None
        self.context_graph = None

        # Configuration
        self.max_actions_per_command = 20
        self.action_timeout = 30  # seconds
        self.confirmation_required = [
            "delete",
            "rm ",
            "format",
            "sudo",
            "shutdown",
            "restart",
        ]

        # Callbacks
        self.on_state_change: Optional[Callable] = None
        self.on_action: Optional[Callable] = None

        logger.info("🏠 [COWORK] Co-Work Mode initialized")

    async def initialize(self) -> bool:
        """Initialize required components"""
        try:
            # Initialize computer tool
            self.computer = get_computer_tool()

            # Initialize memory
            try:
                self.memory = get_structured_memory()
            except:
                pass

            # Initialize context graph
            try:
                self.context_graph = get_context_graph()
            except:
                pass

            logger.info("✅ [COWORK] Initialization complete")
            return True
        except Exception as e:
            logger.error(f"❌ [COWORK] Initialization failed: {e}")
            return False

    async def start(self) -> Dict[str, Any]:
        """Start Co-Work mode - begins continuous listening loop"""
        if self.active:
            return {"success": False, "error": "Already active"}

        init_ok = await self.initialize()
        if not init_ok:
            return {"success": False, "error": "Initialization failed"}

        # Create session
        self.session = CoWorkSession(
            session_id=f"cowork_{int(time.time())}",
            start_time=time.time(),
            state=CoWorkState.LISTENING,
            context={},
            action_history=[],
        )

        self.active = True
        self.state = CoWorkState.LISTENING

        logger.info("🚀 [COWORK] Started - JARVIS is now always-on!")

        # Start the continuous loop in background
        asyncio.create_task(self._main_loop())

        return {
            "success": True,
            "session_id": self.session.session_id,
            "message": "JARVIS Co-Work mode active. Say a command or type one.",
        }

    async def stop(self) -> Dict[str, Any]:
        """Stop Co-Work mode"""
        if not self.active:
            return {"success": False, "error": "Not active"}

        self.active = False
        self.state = CoWorkState.IDLE

        if self.session:
            duration = time.time() - self.session.start_time
            logger.info(f"🛑 [COWORK] Stopped. Session duration: {duration:.1f}s")

        return {
            "success": True,
            "actions_executed": len(self.session.action_history) if self.session else 0,
        }

    async def process_command(self, command: str) -> Dict[str, Any]:
        """
        Process a single command in Co-Work mode.
        This is the main entry point for executing desktop automation.

        Args:
            command: User command (e.g., "Open Safari and search for AI")

        Returns:
            {"success": bool, "response": str, "actions": list, "error": str}
        """
        if not self.active:
            await self.start()

        self.state = CoWorkState.PROCESSING
        self._update_session("last_input", command)

        logger.info(f"📝 [COWORK] Processing: {command[:50]}...")

        try:
            # Step 1: Get current desktop context
            desktop_context = await self._get_desktop_context()

            # Step 2: Analyze command and create action plan
            action_plan = await self._plan_actions(command, desktop_context)

            # Step 3: Execute actions
            results = await self._execute_actions(action_plan)

            # Step 4: Generate response
            response = await self._generate_response(command, results)

            self.state = CoWorkState.LISTENING
            self._update_session("last_response", response)

            return {
                "success": True,
                "response": response,
                "actions": [
                    {
                        "type": a.action_type,
                        "description": a.description,
                        "success": a.success,
                    }
                    for a in self.session.action_history[-len(results) :]
                ],
            }

        except Exception as e:
            self.state = CoWorkState.ERROR
            logger.error(f"❌ [COWORK] Command failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": f"I encountered an error: {str(e)}",
            }

    async def _get_desktop_context(self) -> Dict[str, Any]:
        """Get current desktop state"""
        context = {"timestamp": time.time()}

        if self.computer:
            try:
                status = self.computer.get_status()
                context.update(status)
            except Exception as e:
                logger.debug(f"Could not get computer status: {e}")

        # Get active window
        if self.computer:
            try:
                context["active_window"] = self.computer.get_active_window()
            except:
                pass

        return context

    async def _plan_actions(self, command: str, context: Dict) -> List[Dict]:
        """Use LLM to plan actions needed for the command"""

        # Build prompt for action planning
        planning_prompt = f"""You are JARVIS in Co-Work mode. The user wants to:

"{command}"

Current desktop state:
- Screen: {context.get("screen_size", "unknown")}
- Active window: {context.get("active_window", "unknown")}

Plan the actions needed. Respond with a JSON list of actions.
Each action has: type, description, params

Types:
- "mouse_move": Move mouse to x,y
- "mouse_click": Click at x,y or current position
- "keyboard_type": Type text
- "keyboard_hotkey": Press shortcut (e.g., ["cmd", "c"])
- "terminal": Run shell command
- "browser": Open URL or search
- "launch": Launch application
- "answer": Just respond to user (no action needed)

Respond ONLY with JSON, no other text.
"""

        if call_brain:
            try:
                response = await call_brain(
                    [{"role": "user", "content": planning_prompt}],
                    model=PRO_MODEL,
                    profile="precise",
                )

                # Try to parse JSON from response
                import json
                import re

                json_match = re.search(r"\[.*\]", response, re.DOTALL)
                if json_match:
                    actions = json.loads(json_match.group())
                    return actions[: self.max_actions_per_command]
            except Exception as e:
                logger.debug(f"LLM planning failed: {e}")

        # Fallback: simple keyword-based planning
        return self._simple_action_planning(command)

    def _simple_action_planning(self, command: str) -> List[Dict]:
        """Simple keyword-based action planning as fallback"""
        command_lower = command.lower()
        actions = []

        # Check for browser/search
        if any(kw in command_lower for kw in ["search", "google", "find", "caută"]):
            if "safari" in command_lower or "chrome" in command_lower:
                actions.append(
                    {
                        "type": "launch",
                        "description": "Open browser",
                        "params": {"app": "Safari"},
                    }
                )

            # Extract search query
            search_terms = (
                command_lower.replace("search", "").replace("caută", "").strip()
            )
            if search_terms:
                actions.append(
                    {
                        "type": "browser",
                        "description": f"Search for {search_terms}",
                        "params": {"query": search_terms},
                    }
                )

        # Check for app launch
        if any(kw in command_lower for kw in ["open", "deschide", "start", "launch"]):
            for app in [
                "safari",
                "chrome",
                "terminal",
                "notes",
                "finder",
                "music",
                "mail",
            ]:
                if app in command_lower:
                    actions.append(
                        {
                            "type": "launch",
                            "description": f"Open {app}",
                            "params": {"app": app.title()},
                        }
                    )
                    break

        # Check for terminal commands
        if any(
            kw in command_lower for kw in ["run ", "execute ", "rulează", "execută"]
        ):
            # Extract command after "run" or "execute"
            parts = command_lower.split("run ")
            if len(parts) > 1:
                cmd = parts[1].strip()
                actions.append(
                    {
                        "type": "terminal",
                        "description": f"Run: {cmd}",
                        "params": {"command": cmd},
                    }
                )

        # Default: just answer
        if not actions:
            actions.append(
                {"type": "answer", "description": "Respond to user", "params": {}}
            )

        return actions

    async def _execute_actions(self, action_plan: List[Dict]) -> List[CoWorkAction]:
        """Execute the planned actions"""
        results = []

        for action_def in action_plan:
            action = CoWorkAction(
                action_type=action_def.get("type", "answer"),
                description=action_def.get("description", ""),
                params=action_def.get("params", {}),
            )

            # Check for dangerous commands
            if self._requires_confirmation(action):
                logger.warning(
                    f"⚠️ [COWORK] Action requires confirmation: {action.description}"
                )

            # Execute based on type
            try:
                result = await self._execute_single_action(action)
                action.result = result
                action.success = (
                    result.get("success", False) if isinstance(result, dict) else True
                )
            except Exception as e:
                action.result = {"error": str(e)}
                action.success = False
                logger.error(f"❌ [COWORK] Action failed: {e}")

            results.append(action)

            # Add to session history
            if self.session:
                self.session.action_history.append(action)

            # Callback
            if self.on_action:
                self.on_action(action)

            # Small delay between actions
            await asyncio.sleep(0.3)

        return results

    async def _execute_single_action(self, action: CoWorkAction) -> Dict:
        """Execute a single action"""

        if action.action_type == "mouse_move":
            x = action.params.get("x", 0)
            y = action.params.get("y", 0)
            return self.computer.mouse_move(x, y, action.params.get("duration", 0))

        elif action.action_type == "mouse_click":
            return self.computer.mouse_click(
                action.params.get("x"),
                action.params.get("y"),
                action.params.get("button", "left"),
                action.params.get("clicks", 1),
            )

        elif action.action_type == "keyboard_type":
            return self.computer.keyboard_type(action.params.get("text", ""))

        elif action.action_type == "keyboard_hotkey":
            keys = action.params.get("keys", [])
            return self.computer.keyboard_hotkey(*keys)

        elif action.action_type == "terminal":
            return self.computer.run_command(action.params.get("command", ""))

        elif action.action_type == "launch":
            return self.computer.launch_app(action.params.get("app", ""))

        elif action.action_type == "browser":
            query = action.params.get("query", "")
            url = action.params.get("url", "")

            # Open browser and search
            if self.computer:
                self.computer.launch_app("Safari")
                await asyncio.sleep(1)

                # Type search in address bar
                self.computer.keyboard_hotkey("cmd", "l")
                await asyncio.sleep(0.3)
                self.computer.keyboard_type(f"https://google.com/search?q={query}")
                self.computer.keyboard_press("enter")

            return {"success": True, "query": query}

        elif action.action_type == "answer":
            return {"success": True, "answer": True}

        elif action.action_type == "screenshot":
            return self.computer.screenshot()

        else:
            return {
                "success": False,
                "error": f"Unknown action type: {action.action_type}",
            }

    def _requires_confirmation(self, action: CoWorkAction) -> bool:
        """Check if action requires user confirmation"""
        action_str = (action.description + " " + str(action.params)).lower()
        return any(conf in action_str for conf in self.confirmation_required)

    async def _generate_response(
        self, command: str, results: List[CoWorkAction]
    ) -> str:
        """Generate natural language response from results"""

        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        if not failed:
            if successful:
                action_types = [r.action_type for r in successful]
                if "answer" in action_types and len(successful) == 1:
                    # Just responded, no actions needed
                    return "I've processed your request."
                return f"Done! Executed {len(successful)} action(s): {', '.join(action_types)}."
            else:
                return "No actions were needed."
        else:
            return f"Partially complete. {len(successful)} succeeded, {len(failed)} failed."

    async def _main_loop(self):
        """Main continuous loop for always-on mode"""
        logger.info("🔄 [COWORK] Main loop started")

        while self.active:
            try:
                # In a full implementation, this would listen for:
                # - Voice input
                # - Global hotkey
                # - File-based commands
                # - Websocket connections

                # For now, just maintain the session
                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ [COWORK] Loop error: {e}")
                await asyncio.sleep(1)

        logger.info("🔄 [COWORK] Main loop ended")

    def _update_session(self, key: str, value: Any):
        """Update session context"""
        if self.session:
            self.session.context[key] = value

    def get_status(self) -> Dict[str, Any]:
        """Get Co-Work mode status"""
        return {
            "active": self.active,
            "state": self.state.value if self.state else "unknown",
            "session_id": self.session.session_id if self.session else None,
            "actions_count": len(self.session.action_history) if self.session else 0,
            "last_input": self.session.last_input if self.session else None,
            "last_response": self.session.last_response if self.session else None,
        }


# ==================== GLOBAL INSTANCE ====================

_cowork_instance: Optional[CoWorkMode] = None


def get_cowork_mode() -> CoWorkMode:
    """Get or create the global Co-Work mode instance"""
    global _cowork_instance
    if _cowork_instance is None:
        _cowork_instance = CoWorkMode()
    return _cowork_instance


# ==================== QUICK FUNCTIONS ====================


async def start_cowork() -> Dict[str, Any]:
    """Quick function to start Co-Work mode"""
    coworker = get_cowork_mode()
    return await coworker.start()


async def process_cowork_command(command: str) -> Dict[str, Any]:
    """Quick function to process a command in Co-Work mode"""
    coworker = get_cowork_mode()
    return await coworker.process_command(command)


def cowork_status() -> Dict[str, Any]:
    """Get Co-Work status"""
    coworker = get_cowork_mode()
    return coworker.get_status()


if __name__ == "__main__":
    # Test Co-Work mode
    async def test():
        coworker = CoWorkMode()
        await coworker.initialize()

        # Test single command
        result = await coworker.process_command("Open Safari")
        print("Result:", result)

        # Get status
        print("Status:", coworker.get_status())

    asyncio.run(test())
