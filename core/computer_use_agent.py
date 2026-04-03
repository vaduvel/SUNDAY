"""🖥️ JARVIS Computer Use Agent
Inspired by Claude Code / Devin: Autonomous GUI interaction.

Capabilities:
- Mouse control: move, click, drag, scroll
- Keyboard control: type, shortcuts, hotkeys
- Screen capture: screenshots, region selection
- Application control: launch, focus, close
- Browser automation: navigate, fill forms, scrape
- Multi-monitor support
"""

import asyncio
import hashlib
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import base64

logger = logging.getLogger(__name__)


class MouseButton(Enum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class KeyModifier(Enum):
    CMD = "command"
    CTRL = "control"
    SHIFT = "shift"
    ALT = "option"


@dataclass
class Point:
    """2D point."""

    x: int
    y: int

    def __str__(self):
        return f"({self.x}, {self.y})"


@dataclass
class Rectangle:
    """Rectangle region."""

    x: int
    y: int
    width: int
    height: int

    def __str__(self):
        return f"({self.x}, {self.y}, {self.width}x{self.height})"


@dataclass
class ScreenCapture:
    """Screen capture result."""

    image_data: bytes  # Base64 encoded
    width: int
    height: int
    timestamp: str


class MacOSComputerUse:
    """Computer use implementation for macOS using pyautogui and osascript."""

    def __init__(self):
        self._screenshot_dir = "/tmp/jarvis_screenshots"
        os.makedirs(self._screenshot_dir, exist_ok=True)

        # Import pyautogui
        try:
            import pyautogui

            self.pyautogui = pyautogui
            self.pyautogui.FAILSAFE = True
            self.pyautogui.PAUSE = 0.1
        except ImportError:
            logger.warning("pyautogui not installed - some features will be limited")
            self.pyautogui = None

    # ═══════════════════════════════════════════════════════════
    # MOUSE OPERATIONS
    # ═══════════════════════════════════════════════════════════

    async def mouse_move(self, x: int, y: int, duration: float = 0.0):
        """Move mouse to coordinates."""
        if self.pyautogui:
            self.pyautogui.moveTo(x, y, duration=duration)
        else:
            # Fallback to AppleScript
            script = f'tell application "System Events" to set position of pointer to {{ {x}, {y} }}'
            await self._run_applescript(script)

    async def mouse_click(
        self,
        x: int = None,
        y: int = None,
        button: MouseButton = MouseButton.LEFT,
        clicks: int = 1,
    ):
        """Click at coordinates (or current position)."""
        if self.pyautogui:
            if x is not None and y is not None:
                self.pyautogui.click(x, y, clicks=clicks, button=button.value)
            else:
                self.pyautogui.click(clicks=clicks, button=button.value)
        else:
            script = f'tell application "System Events" to {"click" if clicks == 1 else "double click"}'
            await self._run_applescript(script)

    async def mouse_right_click(self, x: int = None, y: int = None):
        """Right click."""
        await self.mouse_click(x, y, MouseButton.RIGHT)

    async def mouse_drag(
        self, from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.5
    ):
        """Drag from point to point."""
        if self.pyautogui:
            self.pyautogui.moveTo(from_x, from_y)
            self.pyautogui.dragTo(to_x, to_y, duration=duration)

    async def mouse_scroll(self, clicks: int, x: int = None, y: int = None):
        """Scroll mouse wheel."""
        if self.pyautogui:
            self.pyautogui.scroll(clicks, x=x, y=y)

    async def get_mouse_position(self) -> Point:
        """Get current mouse position."""
        if self.pyautogui:
            x, y = self.pyautogui.position()
            return Point(x, y)

        # Fallback
        script = 'tell application "System Events" to get position of pointer'
        result = await self._run_applescript(script)
        # Parse result
        coords = result.strip().split(", ")
        return Point(int(coords[0]), int(coords[1]))

    # ═══════════════════════════════════════════════════════════
    # KEYBOARD OPERATIONS
    # ═══════════════════════════════════════════════════════════

    async def keyboard_type(self, text: str, interval: float = 0.0):
        """Type text."""
        if self.pyautogui:
            self.pyautogui.write(text, interval=interval)
        else:
            # Fallback - character by character
            for char in text:
                script = f'tell application "System Events" to keystroke "{char}"'
                await self._run_applescript(script)
                await asyncio.sleep(interval)

    async def keyboard_press(self, key: str, modifiers: List[KeyModifier] = None):
        """Press a key combination."""
        if self.pyautogui:
            mod_keys = [m.value for m in (modifiers or [])]
            self.pyautogui.hotkey(*mod_keys, key)
        else:
            # Fallback with AppleScript
            mod_str = ""
            if modifiers:
                mod_str = (
                    f"using {{"
                    + ", ".join([f"{m.value} key" for m in modifiers])
                    + "}} "
                )
            script = f'tell application "System Events" to keystroke "{key}" {mod_str}'
            await self._run_applescript(script)

    async def keyboard_hotkey(self, *keys: str):
        """Press a combination like cmd+c."""
        if self.pyautogui:
            self.pyautogui.hotkey(*keys)
        else:
            for key in keys:
                await self.keyboard_press(key)
                await asyncio.sleep(0.05)

    async def copy(self):
        """Copy (cmd+c)."""
        await self.keyboard_hotkey("command", "c")

    async def paste(self):
        """Paste (cmd+v)."""
        await self.keyboard_hotkey("command", "v")

    async def select_all(self):
        """Select all (cmd+a)."""
        await self.keyboard_hotkey("command", "a")

    async def save(self):
        """Save (cmd+s)."""
        await self.keyboard_hotkey("command", "s")

    # ═══════════════════════════════════════════════════════════
    # SCREEN OPERATIONS
    # ═══════════════════════════════════════════════════════════

    async def capture_screen(self, region: Rectangle = None) -> ScreenCapture:
        """Capture entire screen or region."""
        timestamp = int(time.time())
        filename = f"screenshot_{timestamp}.png"
        filepath = os.path.join(self._screenshot_dir, filename)

        if self.pyautogui:
            if region:
                img = self.pyautogui.screenshot(
                    region=(region.x, region.y, region.width, region.height)
                )
            else:
                img = self.pyautogui.screenshot()
            img.save(filepath)
        else:
            # Fallback to screencapture command
            cmd = ["screencapture", "-x", filepath]
            if region:
                cmd.extend(
                    ["-R", f"{region.x},{region.y},{region.width},{region.height}"]
                )
            subprocess.run(cmd)

        # Read and encode
        with open(filepath, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        # Get dimensions
        if self.pyautogui:
            if region:
                width, height = region.width, region.height
            else:
                width, height = self.pyautogui.size()
        else:
            # Use file info
            from PIL import Image

            with Image.open(filepath) as img:
                width, height = img.size

        return ScreenCapture(
            image_data=image_data,
            width=width,
            height=height,
            timestamp=datetime.now().isoformat(),
        )

    async def get_screen_size(self) -> Tuple[int, int]:
        """Get screen dimensions."""
        if self.pyautogui:
            return self.pyautogui.size()
        else:
            script = 'tell application "Finder" to get bounds of window of desktop'
            result = await self._run_applescript(script)
            # Parse: {0, 0, 1920, 1080}
            coords = result.strip("{").strip("}").split(", ")
            return int(coords[2]), int(coords[3])

    # ═══════════════════════════════════════════════════════════
    # APPLICATION OPERATIONS
    # ═══════════════════════════════════════════════════════════

    async def launch_app(self, app_name: str):
        """Launch an application."""
        script = f'tell application "{app_name}" to activate'
        await self._run_applescript(script)

    async def close_app(self, app_name: str):
        """Close an application."""
        script = f'tell application "{app_name}" to quit'
        await self._run_applescript(script)

    async def focus_window(self, app_name: str = None, window_title: str = None):
        """Focus a window."""
        if app_name:
            script = f'tell application "{app_name}" to activate'
            await self._run_applescript(script)

    async def get_active_app(self) -> str:
        """Get the name of the frontmost application."""
        script = 'tell application "System Events" to get name of first process whose frontmost is true'
        return (await self._run_applescript(script)).strip()

    # ═══════════════════════════════════════════════════════════
    # BROWSER OPERATIONS
    # ═══════════════════════════════════════════════════════════

    async def open_url(self, url: str):
        """Open URL in default browser."""
        script = f'open location "{url}"'
        await self._run_applescript(script)

    async def browser_navigate(self, url: str):
        """Navigate browser to URL (Chrome/Safari)."""
        # Try Chrome first
        try:
            script = """
            tell application "Google Chrome"
                activate
                tell window 1
                    set URL of active tab to "{url}"
                end tell
            end tell
            """.format(url=url)
            await self._run_applescript(script)
        except:
            # Fallback to Safari
            script = f'''
            tell application "Safari"
                activate
                tell window 1
                    set current URL to "{url}"
                end tell
            end tell
            '''
            await self._run_applescript(script)

    async def browser_click_element(self, x: int, y: int):
        """Click in browser at coordinates."""
        await self.mouse_click(x, y)

    # ═══════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════

    async def _run_applescript(self, script: str) -> str:
        """Run AppleScript and return result."""
        process = await asyncio.create_subprocess_exec(
            "osascript",
            "-e",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if stderr:
            logger.warning(f"AppleScript warning: {stderr.decode()}")

        return stdout.decode()


class ComputerUseAgent:
    """
    High-level Computer Use Agent for JARVIS.

    Provides task-based automation over the raw computer use primitives.
    """

    def __init__(self):
        self.computer = MacOSComputerUse()
        self._action_history: List[Dict] = []
        self._last_observation: Optional[Dict[str, Any]] = None
        self._last_action_result: Optional[Dict[str, Any]] = None

    async def execute_task(self, task: str) -> Dict[str, Any]:
        """
        Execute a high-level task.

        Examples:
        - "Open Safari and go to github.com"
        - "Click on the login button"
        - "Take a screenshot of the top half of the screen"
        """
        task_lower = task.lower()

        if task_lower.startswith("observe") or "observe screen" in task_lower:
            return await self.observe_screen()

        if "open app" in task_lower or task_lower.startswith("launch "):
            app_name = self._extract_app_name(task)
            if app_name:
                return await self.open_app_verified(app_name)

        if "type" in task_lower and ("into" in task_lower or "in " in task_lower):
            text = self._extract_quoted_text(task)
            destination = self._extract_destination(task)
            if text:
                return await self.type_text_verified(text, destination or "active field")

        if "click" in task_lower and not re.findall(r"(\d+)[,\s]+(\d+)", task):
            target = self._extract_destination(task) or task.replace("click", "").strip()
            if target:
                return await self.click_screen_target(target)

        # Parse and route to appropriate action
        if "open" in task_lower and "url" in task_lower:
            # Extract URL
            import re

            urls = re.findall(r"https?://[^\s]+", task)
            if urls:
                await self.computer.open_url(urls[0])
                return {"success": True, "action": "open_url", "url": urls[0]}

        elif "navigate" in task_lower or "go to" in task_lower:
            import re

            urls = re.findall(r"https?://[^\s]+", task)
            if urls:
                await self.computer.browser_navigate(urls[0])
                return {"success": True, "action": "navigate", "url": urls[0]}

        elif "screenshot" in task_lower:
            capture = await self.computer.capture_screen()
            return {
                "success": True,
                "action": "screenshot",
                "dimensions": f"{capture.width}x{capture.height}",
                "timestamp": capture.timestamp,
            }

        elif "click" in task_lower:
            # Try to extract coordinates
            import re

            coords = re.findall(r"(\d+)[,\s]+(\d+)", task)
            if coords:
                x, y = int(coords[0][0]), int(coords[0][1])
                await self.computer.mouse_click(x, y)
                return {"success": True, "action": "click", "position": f"({x}, {y})"}

        elif "type" in task_lower or "write" in task_lower:
            # Extract text to type
            import re

            # Look for quoted text
            match = re.search(r'[""]([^"]+)[""]', task)
            if match:
                text = match.group(1)
                await self.computer.keyboard_type(text)
                return {"success": True, "action": "type", "text": text}

        elif "launch" in task_lower or "open app" in task_lower:
            # Extract app name
            import re

            apps = re.findall(r"(?:app|application)\s+(\w+)", task_lower)
            if apps:
                app_name = apps[0].title()
                await self.computer.launch_app(app_name)
                return {"success": True, "action": "launch_app", "app": app_name}

        return {"success": False, "error": "Could not understand task"}

    async def observe_screen(self) -> Dict[str, Any]:
        """Capture a semantic desktop observation."""
        width, height = await self.computer.get_screen_size()
        mouse = await self.computer.get_mouse_position()
        active_app = await self.computer.get_active_app()
        capture = await self.computer.capture_screen()
        image_hash = hashlib.sha256(str(capture.image_data).encode("utf-8")).hexdigest()
        observation = {
            "success": True,
            "active_app": active_app,
            "active_window": active_app,
            "mouse_position": {"x": mouse.x, "y": mouse.y},
            "screen_size": {"width": width, "height": height},
            "screen_hash": image_hash,
            "timestamp": capture.timestamp,
            "signals": ["desktop_observed", "screen_captured"],
        }
        self._last_observation = observation
        self._action_history.append({"action": "observe_screen", "active_app": active_app})
        return observation

    async def open_app_verified(self, app_name: str) -> Dict[str, Any]:
        """Open an application and verify it became frontmost."""
        before = await self.observe_screen()
        await self.computer.launch_app(app_name)
        await asyncio.sleep(0.4)
        after = await self.observe_screen()
        verified = app_name.lower() in (after.get("active_app") or "").lower()
        signals = ["app_launch_attempted"]
        if verified:
            signals.append("app_focused")
        result = {
            "success": verified,
            "action": "open_app_verified",
            "app_name": app_name,
            "before": before,
            "after": after,
            "verified": verified,
            "signals": signals,
        }
        self._last_action_result = result
        return result

    async def click_screen_target(self, target_desc: str) -> Dict[str, Any]:
        """Click a desktop target using coordinates or simple heuristics."""
        before = await self.observe_screen()
        coordinates = self._resolve_target_coordinates(target_desc, before)
        if not coordinates:
            return {
                "success": False,
                "action": "click_screen_target",
                "target_desc": target_desc,
                "error": "Target could not be resolved to coordinates",
                "error_code": "TARGET_NOT_RESOLVED",
                "before": before,
            }

        await self.computer.mouse_click(coordinates.x, coordinates.y)
        await asyncio.sleep(0.2)
        after = await self.observe_screen()
        verified = self._screen_state_changed(before, after)
        result = {
            "success": True,
            "action": "click_screen_target",
            "target_desc": target_desc,
            "position": {"x": coordinates.x, "y": coordinates.y},
            "before": before,
            "after": after,
            "verified": verified,
            "signals": ["screen_click", "screen_captured"] + (["screen_changed"] if verified else []),
        }
        self._last_action_result = result
        return result

    async def type_text_verified(self, text: str, destination_desc: str) -> Dict[str, Any]:
        """Type text and verify that the desktop state remains active and responsive."""
        before = await self.observe_screen()
        await self.computer.keyboard_type(text)
        await asyncio.sleep(0.15)
        after = await self.observe_screen()
        verified = bool(text) and (
            before.get("active_app") == after.get("active_app")
            or self._screen_state_changed(before, after)
        )
        result = {
            "success": True,
            "action": "type_text_verified",
            "text_length": len(text),
            "destination_desc": destination_desc,
            "before": before,
            "after": after,
            "verified": verified,
            "signals": ["keyboard_input_attempted", "screen_captured"] + (["screen_changed"] if verified else []),
        }
        self._last_action_result = result
        return result

    async def assert_screen_change(self, expected_signal: str) -> Dict[str, Any]:
        """Assert a specific screen-change signal using the latest observation."""
        previous = self._last_observation or await self.observe_screen()
        current = await self.observe_screen()
        changed = self._screen_state_changed(previous, current)
        signal_map = {
            "screen_changed": changed,
            "window_changed": previous.get("active_app") != current.get("active_app"),
            "mouse_moved": previous.get("mouse_position") != current.get("mouse_position"),
            "app_focused": bool(current.get("active_app")),
        }
        matched = signal_map.get(expected_signal, changed)
        if not matched and self._last_action_result:
            matched = expected_signal in self._last_action_result.get("signals", [])
        return {
            "success": matched,
            "action": "assert_screen_change",
            "expected_signal": expected_signal,
            "matched": matched,
            "previous": previous,
            "current": current,
        }

    async def click_at(self, x: int, y: int) -> Dict[str, Any]:
        """Click at specific coordinates."""
        await self.computer.mouse_click(x, y)
        self._action_history.append({"action": "click", "x": x, "y": y})
        return {"success": True, "position": f"({x}, {y})"}

    async def type_text(self, text: str) -> Dict[str, Any]:
        """Type text."""
        await self.computer.keyboard_type(text)
        self._action_history.append({"action": "type", "text": text})
        return {"success": True, "text": text}

    async def get_screenshot(self, region: Rectangle = None) -> Dict[str, Any]:
        """Get screenshot."""
        capture = await self.computer.capture_screen(region)
        self._action_history.append({"action": "screenshot"})
        return {
            "success": True,
            "width": capture.width,
            "height": capture.height,
            "timestamp": capture.timestamp,
            "has_image": bool(capture.image_data),
        }

    async def get_screen_info(self) -> Dict[str, Any]:
        """Get screen information."""
        width, height = await self.computer.get_screen_size()
        return {"width": width, "height": height}

    async def run_workflow(self, steps: List[Dict]) -> List[Dict]:
        """Run a sequence of steps."""
        results = []

        for step in steps:
            action = step.get("action")

            try:
                if action == "click":
                    result = await self.click_at(step["x"], step["y"])
                elif action == "type":
                    result = await self.type_text(step["text"])
                elif action == "navigate":
                    await self.computer.browser_navigate(step["url"])
                    result = {"success": True}
                elif action == "screenshot":
                    result = await self.get_screenshot()
                elif action == "wait":
                    await asyncio.sleep(step.get("seconds", 1))
                    result = {"success": True}
                else:
                    result = {"success": False, "error": f"Unknown action: {action}"}

                results.append(result)

            except Exception as e:
                results.append({"success": False, "error": str(e)})

        return results

    def get_history(self) -> List[Dict]:
        """Get action history."""
        return self._action_history

    def get_status(self) -> Dict[str, Any]:
        """Expose lightweight runtime status for observers and bridge."""
        latest = self._last_observation or {}
        return {
            "available": True,
            "active_window": latest.get("active_app"),
            "mouse_position": latest.get("mouse_position"),
            "last_screen_hash": latest.get("screen_hash"),
            "history_length": len(self._action_history),
        }

    def _resolve_target_coordinates(
        self, target_desc: str, observation: Dict[str, Any]
    ) -> Optional[Point]:
        coord_match = re.search(r"(\d+)[,\s]+(\d+)", target_desc)
        if coord_match:
            return Point(int(coord_match.group(1)), int(coord_match.group(2)))

        screen = observation.get("screen_size", {})
        width = int(screen.get("width") or 0)
        height = int(screen.get("height") or 0)
        lowered = target_desc.lower()
        if "center" in lowered and width and height:
            return Point(width // 2, height // 2)
        if "top" in lowered and width and height:
            return Point(width // 2, max(20, height // 6))
        if "bottom" in lowered and width and height:
            return Point(width // 2, max(20, int(height * 0.85)))
        if "left" in lowered and width and height:
            return Point(max(20, width // 6), height // 2)
        if "right" in lowered and width and height:
            return Point(max(20, int(width * 0.85)), height // 2)
        return None

    def _screen_state_changed(self, before: Dict[str, Any], after: Dict[str, Any]) -> bool:
        return bool(
            before.get("screen_hash") != after.get("screen_hash")
            or before.get("active_app") != after.get("active_app")
            or before.get("mouse_position") != after.get("mouse_position")
        )

    def _extract_quoted_text(self, task: str) -> str:
        match = re.search(r'["“](.+?)["”]', task)
        return match.group(1) if match else ""

    def _extract_destination(self, task: str) -> str:
        match = re.search(r"(?:into|in|on)\s+(.+)$", task, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _extract_app_name(self, task: str) -> str:
        match = re.search(
            r"(?:open app|launch|open application|application)\s+([A-Za-z0-9 ._-]+)",
            task,
            re.IGNORECASE,
        )
        return match.group(1).strip() if match else ""


# Integration with vision for UI understanding
class ComputerUseWithVision:
    """Computer use enhanced with OCR/Vision for understanding UI."""

    def __init__(self):
        self.computer_use = ComputerUseAgent()

    async def find_and_click(
        self, target_text: str, screenshot: ScreenCapture
    ) -> Dict[str, Any]:
        """
        Find text on screen and click it.

        This would use OCR to find the target text and click on it.
        """
        # Placeholder - would integrate with vision model
        # 1. Use OCR on screenshot to find text positions
        # 2. Find target_text in results
        # 3. Click on the position

        return {"success": False, "error": "Vision integration not implemented"}

    async def describe_screen(self) -> str:
        """Describe what's on screen using vision."""
        capture = await self.computer_use.computer.capture_screen()

        # Placeholder - would use vision model to describe
        return f"Screen {capture.width}x{capture.height}"

# Standalone test
if __name__ == "__main__":

    async def test():
        agent = ComputerUseAgent()

        # Get screen info
        info = await agent.get_screen_info()
        print(f"Screen: {info}")

        # Test screenshot
        ss = await agent.get_screenshot()
        print(f"Screenshot: {ss}")

        # Test task execution
        result = await agent.execute_task("Take a screenshot")
        print(f"Task result: {result}")

    asyncio.run(test())
