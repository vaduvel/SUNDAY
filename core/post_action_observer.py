"""
J.A.R.V.I.S. Post-Action Observer
==================================

Responsabil pentru captură de stare după fiecare pas.

Based on JARVIS V2 Blueprint Section 4.3
"""

import time
import json
import hashlib
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class SemanticSnapshot:
    """Snapshot semantic al stării sistemului"""

    timestamp: datetime
    session_id: str
    step_id: str

    # Browser state
    browser_url: Optional[str] = None
    browser_title: Optional[str] = None
    browser_dom_hash: Optional[str] = None

    # Desktop state
    active_window: Optional[str] = None
    mouse_position: Optional[tuple] = None
    screen_regions: List[str] = field(default_factory=list)

    # File system
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)

    # Memory
    memories_written: List[str] = field(default_factory=list)

    # Signals observed
    signals: List[str] = field(default_factory=list)

    # Raw data
    raw_observations: Dict[str, Any] = field(default_factory=dict)


class PostActionObserver:
    """
    Observer care capturează starea sistemului după fiecare pas important.

    Responsabil pentru:
    - captură de stare browser/desktop
    - snapshot semantic
    - diff expected vs actual
    """

    def __init__(self):
        self.snapshots: List[SemanticSnapshot] = []
        self.computer = None
        self.browser_session = None

        # Try to import computer tool
        try:
            from tools.computer_use import get_computer_tool

            self.computer = get_computer_tool()
        except:
            logger.warning("Computer tool not available for observation")

    def set_browser_session(self, browser_session: Any) -> None:
        """Attach a browser/session adapter for richer observations."""
        self.browser_session = browser_session

    def observe_after_action(
        self, step_id: str, session_id: str, action_type: str, action_params: Dict
    ) -> SemanticSnapshot:
        """
        Observă starea după o acțiune.

        Args:
            step_id: ID-ul pasului executat
            session_id: ID-ul sesiunii
            action_type: Tipul acțiunii executate
            action_params: Parametrii acțiunii

        Returns:
            SemanticSnapshot cu starea observată
        """
        snapshot = SemanticSnapshot(
            timestamp=datetime.now(), session_id=session_id, step_id=step_id
        )

        # Observe based on action type
        if action_type in [
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_search",
            "browser_click_verified",
            "browser_type_verified",
        ]:
            self._observe_browser(snapshot, action_params)

        elif action_type in [
            "mouse_click",
            "mouse_move",
            "keyboard_type",
            "launch_app",
            "observe_screen",
            "open_app_verified",
            "click_screen_target",
            "type_text_verified",
        ]:
            self._observe_desktop(snapshot, action_params)

        elif action_type in ["file_write", "create_folder"]:
            self._observe_files(snapshot, action_params)

        elif action_type in ["memory_write", "memory_search"]:
            self._observe_memory(snapshot, action_params)

        else:
            # Generic observation
            self._observe_generic(snapshot)

        # Store snapshot
        self.snapshots.append(snapshot)

        logger.info(
            f"📸 [OBSERVER] Captured snapshot for {step_id}: {len(snapshot.signals)} signals"
        )

        return snapshot

    def observe_browser_state(self, session_id: str) -> Dict[str, Any]:
        """Return a normalized browser observation payload."""
        state: Dict[str, Any] = {"session_id": session_id, "kind": "browser"}
        browser = self.browser_session

        try:
            if browser and hasattr(browser, "get_page_summary"):
                summary = browser.get_page_summary()
                if hasattr(summary, "__await__"):
                    summary = None
            else:
                summary = None
        except Exception:
            summary = None

        if isinstance(summary, dict):
            state.update(summary)
        elif browser and getattr(browser, "last_semantic_state", None):
            state.update(dict(browser.last_semantic_state))
        elif browser and hasattr(browser, "page") and getattr(browser, "page", None):
            try:
                page = browser.page
                state.update(
                    {
                        "url": getattr(page, "url", None),
                        "title": getattr(page, "title", None),
                    }
                )
            except Exception:
                pass

        return state

    def observe_desktop_state(self, session_id: str) -> Dict[str, Any]:
        """Return a normalized desktop observation payload."""
        state: Dict[str, Any] = {"session_id": session_id, "kind": "desktop"}
        if self.computer and hasattr(self.computer, "get_status"):
            try:
                status = self.computer.get_status()
                if isinstance(status, dict):
                    state.update(status)
            except Exception as exc:
                state["error"] = str(exc)
        return state

    def build_semantic_snapshot(self, raw_state: Dict[str, Any]) -> Dict[str, Any]:
        """Build a semantic snapshot summary from raw environment state."""
        snapshot = {
            "signals": list(raw_state.get("signals", [])),
            "browser": {
                "url": raw_state.get("url") or raw_state.get("browser_url"),
                "title": raw_state.get("title") or raw_state.get("browser_title"),
            },
            "desktop": {
                "active_window": raw_state.get("active_window"),
                "mouse_position": raw_state.get("mouse_position"),
            },
            "artifacts": list(raw_state.get("artifacts", [])),
            "files_created": list(raw_state.get("files_created", [])),
            "files_modified": list(raw_state.get("files_modified", [])),
        }
        snapshot["signal_count"] = len(snapshot["signals"])
        return snapshot

    def _observe_browser(self, snapshot: SemanticSnapshot, params: Dict):
        """Observă starea browser-ului"""
        browser_state = (
            params.get("browser_state")
            or params.get("state")
            or params.get("after")
            or params.get("semantic_state")
            or {}
        )
        snapshot.browser_url = (
            browser_state.get("url") or params.get("url") or snapshot.browser_url
        )
        snapshot.browser_title = (
            browser_state.get("title") or params.get("title") or snapshot.browser_title
        )
        snapshot.browser_dom_hash = browser_state.get("browser_dom_hash") or self._hash_payload(
            {
                "url": snapshot.browser_url,
                "title": snapshot.browser_title,
                "content_preview": browser_state.get("content_preview", ""),
            }
        )

        signals = browser_state.get("signals") or params.get("signals") or []
        if not signals:
            signals = ["browser_navigated", "semantic_state_captured"]
            if params.get("verified"):
                signals.append("page_changed")
        snapshot.signals.extend(signals)

        snapshot.raw_observations["browser"] = {
            **browser_state,
            "url": snapshot.browser_url,
            "title": snapshot.browser_title,
            "browser_dom_hash": snapshot.browser_dom_hash,
            "timestamp": time.time(),
        }

    def _observe_desktop(self, snapshot: SemanticSnapshot, params: Dict):
        """Observă starea desktop-ului"""
        desktop_state = (
            params.get("screen_state")
            or params.get("after")
            or params.get("desktop_state")
            or {}
        )
        if self.computer:
            try:
                status = self.computer.get_status()
                snapshot.active_window = status.get("active_window")
                snapshot.mouse_position = (
                    status.get("mouse_position", {}).get("x"),
                    status.get("mouse_position", {}).get("y"),
                )
                snapshot.screen_regions = ["top_bar", "main_area", "dock"]

                snapshot.signals.extend(["desktop_observed", "window_active"])
            except Exception as e:
                logger.warning(f"Desktop observation failed: {e}")

        if desktop_state:
            snapshot.active_window = desktop_state.get("active_app") or desktop_state.get(
                "active_window"
            ) or snapshot.active_window
            mouse = desktop_state.get("mouse_position")
            if isinstance(mouse, dict):
                snapshot.mouse_position = (mouse.get("x"), mouse.get("y"))
            elif isinstance(mouse, (list, tuple)):
                snapshot.mouse_position = tuple(mouse)
            snapshot.screen_regions = desktop_state.get("screen_regions", snapshot.screen_regions)
            snapshot.signals.extend(desktop_state.get("signals", []))

        snapshot.raw_observations["desktop"] = {
            "active_window": snapshot.active_window,
            "mouse_position": snapshot.mouse_position,
            **desktop_state,
            "timestamp": time.time(),
        }

    def _observe_files(self, snapshot: SemanticSnapshot, params: Dict):
        """Observă starea sistemului de fișiere"""
        if "filename" in params:
            snapshot.files_created.append(params["filename"])

        snapshot.signals.extend(["file_created", "filesystem_modified"])

        snapshot.raw_observations["files"] = {
            "created": snapshot.files_created,
            "timestamp": time.time(),
        }

    def _observe_memory(self, snapshot: SemanticSnapshot, params: Dict):
        """Observă starea memoriei"""
        if "memory_id" in params:
            snapshot.memories_written.append(params["memory_id"])

        snapshot.signals.extend(["memory_written", "memory_updated"])

        snapshot.raw_observations["memory"] = {
            "written": snapshot.memories_written,
            "timestamp": time.time(),
        }

    def _observe_generic(self, snapshot: SemanticSnapshot):
        """Observație generică"""
        snapshot.signals.append("action_completed")
        snapshot.raw_observations["generic"] = {"timestamp": time.time()}

    def _hash_payload(self, payload: Dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def diff_expected_vs_actual(
        self, expected: Dict[str, Any], observed: SemanticSnapshot
    ) -> Dict[str, Any]:
        """
        Compară starea așteptată cu cea observată.

        Returns:
            Dict cu "match" (bool), "diffs" (list), "severity" (str)
        """
        diffs = []
        severity = "none"

        # Check browser URL
        if "browser_url" in expected:
            if observed.browser_url != expected["browser_url"]:
                diffs.append(
                    f"URL mismatch: expected {expected['browser_url']}, got {observed.browser_url}"
                )
                severity = "high"

        # Check active window
        if "active_window" in expected:
            if observed.active_window != expected["active_window"]:
                diffs.append(
                    f"Window mismatch: expected {expected['active_window']}, got {observed.active_window}"
                )
                severity = "medium"

        # Check files
        if "expected_files" in expected:
            for f in expected["expected_files"]:
                if f not in observed.files_created:
                    diffs.append(f"File not created: {f}")
                    severity = "high"

        # Check signals
        if "expected_signals" in expected:
            for sig in expected["expected_signals"]:
                if sig not in observed.signals:
                    diffs.append(f"Signal not observed: {sig}")
                    severity = "medium" if severity == "none" else severity

        return {
            "match": len(diffs) == 0,
            "diffs": diffs,
            "severity": severity,
            "observed_signals": observed.signals,
        }

    def diff_expected_vs_observed(
        self, expected: Dict[str, Any], observed: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compare expected state against a normalized observed dict."""
        normalized = self.build_semantic_snapshot(observed)
        browser = normalized.get("browser", {})
        desktop = normalized.get("desktop", {})
        pseudo_snapshot = SemanticSnapshot(
            timestamp=datetime.now(),
            session_id=str(observed.get("session_id", "unknown")),
            step_id=str(observed.get("step_id", "unknown")),
            browser_url=browser.get("url"),
            browser_title=browser.get("title"),
            active_window=desktop.get("active_window"),
            mouse_position=desktop.get("mouse_position"),
            files_created=normalized.get("files_created", []),
            files_modified=normalized.get("files_modified", []),
            signals=normalized.get("signals", []),
            raw_observations=observed,
        )
        return self.diff_expected_vs_actual(expected, pseudo_snapshot)

    def get_recent_snapshot(self, step_id: str = None) -> Optional[SemanticSnapshot]:
        """Get most recent snapshot"""
        if step_id:
            for snapshot in reversed(self.snapshots):
                if snapshot.step_id == step_id:
                    return snapshot
        return self.snapshots[-1] if self.snapshots else None

    def get_observation_stats(self) -> Dict[str, Any]:
        """Get observation statistics"""
        return {
            "total_snapshots": len(self.snapshots),
            "by_signal": self._count_signals(),
        }

    def _count_signals(self) -> Dict[str, int]:
        """Count occurrences of each signal"""
        counts = {}
        for snapshot in self.snapshots:
            for signal in snapshot.signals:
                counts[signal] = counts.get(signal, 0) + 1
        return counts


# ==================== GLOBAL INSTANCE ====================

_observer: Optional[PostActionObserver] = None


def get_post_action_observer() -> PostActionObserver:
    """Get or create global observer"""
    global _observer
    if _observer is None:
        _observer = PostActionObserver()
    return _observer


# ==================== TEST ====================

if __name__ == "__main__":
    print("=== POST-ACTION OBSERVER TEST ===\n")

    observer = get_post_action_observer()

    # Test observations
    snapshot1 = observer.observe_after_action(
        step_id="step_001",
        session_id="session_123",
        action_type="browser_navigate",
        action_params={"url": "https://example.com", "title": "Example"},
    )
    print(f"Snapshot 1: {len(snapshot1.signals)} signals")
    print(f"  Browser: {snapshot1.browser_url}")
    print(f"  Signals: {snapshot1.signals}")

    snapshot2 = observer.observe_after_action(
        step_id="step_002",
        session_id="session_123",
        action_type="file_write",
        action_params={"filename": "test.txt"},
    )
    print(f"\nSnapshot 2: {len(snapshot2.signals)} signals")
    print(f"  Files: {snapshot2.files_created}")

    # Test diff
    diff = observer.diff_expected_vs_actual(
        expected={
            "browser_url": "https://example.com",
            "expected_signals": ["browser_navigated"],
        },
        observed=snapshot1,
    )
    print(f"\nDiff: {diff['match']}, severity: {diff['severity']}")

    print(f"\nStats: {observer.get_observation_stats()}")

    print("\n✅ Observer test complete!")
