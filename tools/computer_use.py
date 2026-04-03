"""J.A.R.V.I.S. Computer Use Tool - Full Desktop Autonomy

Provides:
- Screen capture (screenshot)
- Mouse control (move, click, drag)
- Keyboard control (type, hotkeys)
- Window management
- Application control
"""

import os
import time
import subprocess
import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pyautogui
    import pynput

    PYAUTOGUI_AVAILABLE = True
    PYNPUT_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    PYNPUT_AVAILABLE = False
    logger.info("PyAutoGUI/pynput not available - computer use limited")


@dataclass
class ScreenRegion:
    """Represents a region of the screen for OCR/analysis"""

    x: int
    y: int
    width: int
    height: int


class ComputerTool:
    """
    Anthropic Computer Use-style tool for JARVIS.
    Enables AI to interact with desktop like a human.
    """

    def __init__(self, screenshots_dir: str = ".agent/screenshots"):
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Configure pyautogui
        if PYAUTOGUI_AVAILABLE:
            pyautogui.PAUSE = 0.5  # Pause between actions
            pyautogui.FAILSAFE = True  # Failsafe - move to corner to abort

        self._keyboard = None
        if PYNPUT_AVAILABLE:
            try:
                self._keyboard = pynput.keyboard.Controller()
            except Exception as e:
                logger.warning(f"Keyboard controller init failed: {e}")

        logger.info("🎛️ [COMPUTER] Computer Use Tool initialized")

    # ==================== SCREEN CAPTURE ====================

    def screenshot(
        self, region: Optional[Tuple[int, int, int, int]] = None
    ) -> Dict[str, Any]:
        """
        Take a screenshot of all screens or a specific region.
        Returns path to screenshot file.

        Args:
            region: Optional (x, y, width, height) for partial screenshot

        Returns:
            {"success": bool, "path": str, "error": str}
        """
        if not PYAUTOGUI_AVAILABLE:
            return {"success": False, "error": "PyAutoGUI not available"}

        try:
            timestamp = int(time.time() * 1000)
            filename = f"screenshot_{timestamp}.png"
            filepath = self.screenshots_dir / filename

            if region:
                x, y, w, h = region
                img = pyautogui.screenshot(region=(x, y, w, h))
            else:
                img = pyautogui.screenshot()

            img.save(str(filepath))
            logger.debug(f"📸 [COMPUTER] Screenshot saved: {filepath}")

            return {"success": True, "path": str(filepath), "timestamp": timestamp}
        except Exception as e:
            logger.error(f"❌ [COMPUTER] Screenshot failed: {e}")
            return {"success": False, "error": str(e)}

    def get_screen_size(self) -> Dict[str, int]:
        """Get the primary screen resolution"""
        if not PYAUTOGUI_AVAILABLE:
            return {"width": 0, "height": 0}

        size = pyautogui.size()
        return {"width": size.width, "height": size.height}

    # ==================== MOUSE CONTROL ====================

    def mouse_move(self, x: int, y: int, duration: float = 0.0) -> Dict[str, Any]:
        """
        Move mouse cursor to absolute position.

        Args:
            x: Target X coordinate
            y: Target Y coordinate
            duration: Movement duration in seconds (0 = instant)

        Returns:
            {"success": bool, "position": {"x": int, "y": int}}
        """
        if not PYAUTOGUI_AVAILABLE:
            return {"success": False, "error": "PyAutoGUI not available"}

        try:
            pyautogui.moveTo(x, y, duration=duration)
            return {"success": True, "position": {"x": x, "y": y}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def mouse_click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        clicks: int = 1,
    ) -> Dict[str, Any]:
        """
        Click at position (or current position if None).

        Args:
            x, y: Optional target coordinates
            button: "left", "right", or "middle"
            clicks: Number of clicks (1 = single, 2 = double)

        Returns:
            {"success": bool, "position": {"x": int, "y": int}}
        """
        if not PYAUTOGUI_AVAILABLE:
            return {"success": False, "error": "PyAutoGUI not available"}

        try:
            if x is not None and y is not None:
                pyautogui.click(x, y, clicks=clicks, button=button)
                position = {"x": x, "y": y}
            else:
                pyautogui.click(clicks=clicks, button=button)
                position = dict(pyautogui.position())

            logger.debug(f"🖱️ [COMPUTER] Click: {position} button={button}")
            return {"success": True, "position": position}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def mouse_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
        button: str = "left",
    ) -> Dict[str, Any]:
        """
        Drag from start to end position (for selecting, moving files, etc.)
        """
        if not PYAUTOGUI_AVAILABLE:
            return {"success": False, "error": "PyAutoGUI not available"}

        try:
            pyautogui.moveTo(start_x, start_y)
            pyautogui.mouseDown(button=button)
            pyautogui.moveTo(end_x, end_y, duration=duration)
            pyautogui.mouseUp(button=button)

            return {
                "success": True,
                "from": {"x": start_x, "y": start_y},
                "to": {"x": end_x, "y": end_y},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def mouse_scroll(self, clicks: int) -> Dict[str, Any]:
        """
        Scroll the mouse wheel.

        Args:
            clicks: Positive = up, Negative = down
        """
        if not PYAUTOGUI_AVAILABLE:
            return {"success": False, "error": "PyAutoGUI not available"}

        try:
            pyautogui.scroll(clicks)
            return {"success": True, "clicks": clicks}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_mouse_position(self) -> Dict[str, int]:
        """Get current mouse position"""
        if not PYAUTOGUI_AVAILABLE:
            return {"x": 0, "y": 0}

        pos = pyautogui.position()
        return {"x": pos.x, "y": pos.y}

    # ==================== KEYBOARD CONTROL ====================

    def keyboard_type(self, text: str, interval: float = 0.0) -> Dict[str, Any]:
        """
        Type text string (as if typed on keyboard).

        Args:
            text: Text to type
            interval: Delay between keystrokes (seconds)
        """
        if not PYAUTOGUI_AVAILABLE:
            return {"success": False, "error": "PyAutoGUI not available"}

        try:
            pyautogui.write(text, interval=interval)
            logger.debug(f"⌨️ [COMPUTER] Typed: {text[:50]}...")
            return {"success": True, "text_length": len(text)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def keyboard_hotkey(self, *keys: str) -> Dict[str, Any]:
        """
        Press keyboard shortcut (e.g., "cmd", "c" for copy).

        Args:
            *keys: Keys to press together (e.g., "cmd", "c")
        """
        if not PYAUTOGUI_AVAILABLE:
            return {"success": False, "error": "PyAutoGUI not available"}

        try:
            pyautogui.hotkey(*keys)
            logger.debug(f"⌨️ [COMPUTER] Hotkey: {'+'.join(keys)}")
            return {"success": True, "keys": list(keys)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def keyboard_press(self, key: str) -> Dict[str, Any]:
        """Press a single key"""
        if not PYAUTOGUI_AVAILABLE:
            return {"success": False, "error": "PyAutoGUI not available"}

        try:
            pyautogui.press(key)
            return {"success": True, "key": key}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== WINDOW MANAGEMENT ====================

    def get_active_window(self) -> Optional[str]:
        """Get the title of the currently active window"""
        try:
            script = """tell application "System Events" to get name of first process whose frontmost is true"""
            result = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    def launch_app(self, app_name: str) -> Dict[str, Any]:
        """Launch an application by name"""
        try:
            subprocess.run(["open", "-a", app_name], check=True)
            return {"success": True, "app": app_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== TERMINAL COMMANDS ====================

    def run_command(self, command: str, shell: bool = True) -> Dict[str, Any]:
        """Run a terminal command (wrapper for subprocess)"""
        try:
            result = subprocess.run(
                command, shell=shell, capture_output=True, text=True, timeout=30
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== FIND ELEMENT ON SCREEN ====================

    def locate_on_screen(
        self, image_path: str, confidence: float = 0.8
    ) -> Optional[Dict[str, int]]:
        """
        Locate an image on screen (for clicking buttons, etc.)

        Args:
            image_path: Path to image to find
            confidence: Match confidence (0-1)

        Returns:
            {"x": int, "y": int, "width": int, "height": int} or None
        """
        if not PYAUTOGUI_AVAILABLE:
            return None

        try:
            import pyautogui

            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                return {
                    "x": location.left,
                    "y": location.top,
                    "width": location.width,
                    "height": location.height,
                }
        except Exception as e:
            logger.debug(f"Locate failed: {e}")

        return None

    # ==================== STATUS ====================

    def get_status(self) -> Dict[str, Any]:
        """Get computer tool status"""
        return {
            "available": PYAUTOGUI_AVAILABLE,
            "screen_size": self.get_screen_size(),
            "mouse_position": self.get_mouse_position(),
            "active_window": self.get_active_window(),
            "screenshot_dir": str(self.screenshots_dir),
        }


# ==================== GLOBAL INSTANCE ====================

_computer_tool: Optional[ComputerTool] = None


def get_computer_tool() -> ComputerTool:
    """Get or create the global computer tool instance"""
    global _computer_tool
    if _computer_tool is None:
        _computer_tool = ComputerTool()
    return _computer_tool


# ==================== MCP TOOL REGISTRY ====================


def register_computer_tools(registry) -> None:
    """Register computer tool functions with MCP registry"""

    computer = get_computer_tool()

    # Screenshot
    registry.register_tool(
        name="computer_screenshot",
        description="Take a screenshot of the screen. Returns path to image file.",
        parameters={
            "type": "object",
            "properties": {
                "region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional [x, y, width, height] for partial screenshot",
                }
            },
        },
        handler=lambda args: computer.screenshot(args.get("region") if args else None),
    )

    # Mouse move
    registry.register_tool(
        name="computer_mouse_move",
        description="Move mouse cursor to absolute screen position",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "duration": {"type": "number", "default": 0},
            },
            "required": ["x", "y"],
        },
        handler=lambda args: computer.mouse_move(
            args["x"], args["y"], args.get("duration", 0)
        ),
    )

    # Mouse click
    registry.register_tool(
        name="computer_mouse_click",
        description="Click mouse button at position or current location",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                },
                "clicks": {"type": "integer", "default": 1},
            },
        },
        handler=lambda args: computer.mouse_click(
            args.get("x"),
            args.get("y"),
            args.get("button", "left"),
            args.get("clicks", 1),
        ),
    )

    # Keyboard type
    registry.register_tool(
        name="computer_keyboard_type",
        description="Type text using keyboard",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        handler=lambda args: computer.keyboard_type(args["text"]),
    )

    # Keyboard hotkey
    registry.register_tool(
        name="computer_keyboard_hotkey",
        description="Press keyboard shortcut (e.g., cmd+c, ctrl+v)",
        parameters={
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keys to press together (e.g., ['cmd', 'c'] for copy)",
                }
            },
            "required": ["keys"],
        },
        handler=lambda args: computer.keyboard_hotkey(*args["keys"]),
    )

    # Get status
    registry.register_tool(
        name="computer_status",
        description="Get computer tool status and current state",
        parameters={"type": "object", "properties": {}},
        handler=lambda _: computer.get_status(),
    )

    logger.info("✅ [MCP] Computer tools registered")


if __name__ == "__main__":
    # Test the computer tool
    computer = get_computer_tool()
    print("Computer Tool Status:", computer.get_status())
