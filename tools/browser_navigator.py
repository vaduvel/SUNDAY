"""J.A.R.V.I.S. browser navigator with verified actions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class BrowserNavigator:
    """Deterministic browser control with semantic verification."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        self.last_semantic_state: Optional[Dict[str, Any]] = None

    async def start(self):
        """Launch the Chromium engine."""
        if self.page:
            return
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 800}
        )
        self.page = await self.context.new_page()
        logger.info("👁️ [BROWSER] Digital Eyes ONLINE.")

    async def _ensure_started(self):
        if self.page is None:
            await self.start()

    async def navigate_to(self, url: str):
        """Compatibility wrapper for blueprint-style verified navigation."""
        result = await self.navigate_with_readiness_check(url)
        return result.get("state", {})

    async def navigate_with_readiness_check(self, url: str) -> Dict[str, Any]:
        """Navigate and wait for a stable, readable page state."""
        await self._ensure_started()
        logger.info("🌐 [BROWSER] Navigating to: %s", url)
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            readiness = await self._wait_for_page_ready()
            state = await self.capture_semantic_page_state()
            verified = bool(readiness.get("ready")) and state.get("url", "").startswith(
                ("http://", "https://")
            )
            return {
                "success": verified,
                "action": "navigate",
                "url": url,
                "verified": verified,
                "readiness": readiness,
                "state": state,
                "signals": ["browser_navigated", "page_loaded", "semantic_state_captured"],
            }
        except Exception as exc:
            return self._failure("navigate", exc, url=url)

    async def get_page_summary(self) -> Dict[str, Any]:
        await self._ensure_started()
        title = await self._safe_title()
        interactive_elements = await self._collect_interactive_elements()
        return {
            "title": title,
            "url": getattr(self.page, "url", ""),
            "interactive_elements": interactive_elements,
        }

    async def take_screenshot(self, name: str) -> str:
        await self._ensure_started()
        artifacts_dir = Path("artifacts")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = str(artifacts_dir / f"screenshot_{name}.png")
        await self.page.screenshot(path=path)
        logger.info("📷 [BROWSER] Screenshot captured: %s", path)
        return path

    async def click_element(self, selector: str):
        result = await self.click_with_verification(selector=selector)
        if result.get("success"):
            return result.get("after", {})
        raise RuntimeError(result.get("error", "Browser click failed"))

    async def click_with_verification(
        self, selector: str | None = None, text: str | None = None
    ) -> Dict[str, Any]:
        """Click an element and verify semantic state changes."""
        await self._ensure_started()
        before = await self.capture_semantic_page_state()
        target = selector or text
        try:
            if selector:
                await self.page.click(selector, timeout=5000)
            elif text:
                fallback = await self.fallback_visual_click(text)
                fallback["before"] = before
                return fallback
            else:
                raise ValueError("selector or text is required for click")

            await self._wait_after_interaction()
            after = await self.capture_semantic_page_state()
            verified = self._state_changed(before, after)
            return {
                "success": True,
                "action": "click",
                "selector": selector,
                "text": text,
                "target": target,
                "before": before,
                "after": after,
                "verified": verified,
                "signals": self._interaction_signals("click", verified, before, after),
            }
        except Exception as exc:
            if text and not selector:
                fallback = await self.fallback_visual_click(text)
                fallback["before"] = before
                return fallback
            return self._failure("click", exc, selector=selector, text=text, before=before)

    async def type_text(self, selector: str, text: str):
        result = await self.type_with_verification(selector, text)
        if result.get("success"):
            return {
                "selector": selector,
                "typed": len(text),
                "url": result.get("after", {}).get("url", getattr(self.page, "url", "")),
            }
        raise RuntimeError(result.get("error", "Browser type failed"))

    async def type_with_verification(self, selector: str, text: str) -> Dict[str, Any]:
        """Type into a field and verify the field value matches."""
        await self._ensure_started()
        before = await self.capture_semantic_page_state()
        try:
            await self.page.fill(selector, text, timeout=5000)
            await self._wait_after_interaction()
            typed_value = await self._safe_input_value(selector)
            after = await self.capture_semantic_page_state()
            verified = typed_value == text or self._state_changed(before, after)
            return {
                "success": True,
                "action": "type",
                "selector": selector,
                "text": text,
                "typed_value": typed_value,
                "before": before,
                "after": after,
                "verified": verified,
                "signals": self._interaction_signals("type", verified, before, after),
            }
        except Exception as exc:
            return self._failure("type", exc, selector=selector, text=text, before=before)

    async def extract_text(self, selector: str = "body", max_chars: int = 4000) -> Dict[str, Any]:
        await self._ensure_started()
        try:
            text = await self.page.inner_text(selector)
        except Exception:
            locator = self.page.locator(selector)
            text = await locator.text_content() or ""
        return {
            "selector": selector,
            "text": (text or "")[:max_chars],
            "url": getattr(self.page, "url", ""),
            "title": await self._safe_title(),
        }

    async def capture_semantic_page_state(self) -> Dict[str, Any]:
        """Capture a semantic page state suitable for observer/verifier loops."""
        await self._ensure_started()
        interactive_elements = await self._collect_interactive_elements()
        derived = await self._derive_page_semantics()
        state = {
            "title": await self._safe_title(),
            "url": getattr(self.page, "url", ""),
            "interactive_elements": interactive_elements,
            "content_preview": derived.get("content_preview", ""),
            "ready_state": derived.get("ready_state", "unknown"),
            "headings": derived.get("headings", []),
            "form_fields": derived.get("form_fields", []),
            "primary_actions": derived.get("primary_actions", []),
            "interactive_count": len(interactive_elements),
        }
        state["browser_dom_hash"] = self._hash_payload(
            {
                "url": state["url"],
                "title": state["title"],
                "content_preview": state["content_preview"],
                "headings": state["headings"],
                "interactive": [
                    (item.get("tag"), item.get("text")) for item in interactive_elements
                ],
            }
        )
        state["signals"] = self._semantic_signals(state)
        self.last_semantic_state = state
        return state

    async def fallback_visual_click(self, target_description: str) -> Dict[str, Any]:
        """Fallback click based on visible text/heuristics when selectors fail."""
        await self._ensure_started()
        before = await self.capture_semantic_page_state()
        attempts = [
            ("text", lambda: self.page.locator(f"text={target_description}").first.click(timeout=3000)),
            (
                "button",
                lambda: self.page.get_by_role("button", name=target_description).click(
                    timeout=3000
                ),
            ),
            (
                "link",
                lambda: self.page.get_by_role("link", name=target_description).click(
                    timeout=3000
                ),
            ),
        ]

        last_error = None
        for mode, operation in attempts:
            try:
                await operation()
                await self._wait_after_interaction()
                after = await self.capture_semantic_page_state()
                verified = self._state_changed(before, after)
                return {
                    "success": True,
                    "action": "fallback_visual_click",
                    "target_description": target_description,
                    "mode": mode,
                    "before": before,
                    "after": after,
                    "verified": verified,
                    "signals": self._interaction_signals("click", verified, before, after),
                }
            except Exception as exc:
                last_error = exc

        return self._failure(
            "fallback_visual_click",
            last_error or RuntimeError("No visual target matched"),
            target_description=target_description,
            before=before,
        )

    async def observe(self) -> Dict[str, Any]:
        return await self.capture_semantic_page_state()

    async def stop(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        logger.info("👁️ [BROWSER] Digital Eyes OFFLINE.")

    async def _collect_interactive_elements(self) -> List[Dict[str, Any]]:
        try:
            elements = await self.page.query_selector_all(
                "button, a, input, textarea, select, [role='button']"
            )
        except Exception:
            return []

        result: List[Dict[str, Any]] = []
        for idx, element in enumerate(elements[:20]):
            try:
                text = (await element.inner_text()).strip()
            except Exception:
                text = ""
            try:
                tag = await element.evaluate("node => node.tagName")
            except Exception:
                tag = "UNKNOWN"
            result.append({"id": idx, "tag": str(tag), "text": text})
        return result

    async def _derive_page_semantics(self) -> Dict[str, Any]:
        script = """
        () => {
          const text = document.body && document.body.innerText ? document.body.innerText : "";
          const headings = Array.from(document.querySelectorAll("h1,h2,h3"))
            .map(el => el.innerText.trim())
            .filter(Boolean)
            .slice(0, 8);
          const formFields = Array.from(document.querySelectorAll("input, textarea, select"))
            .map(el => ({
              tag: el.tagName,
              type: el.getAttribute("type") || "",
              name: el.getAttribute("name") || el.getAttribute("aria-label") || ""
            }))
            .slice(0, 10);
          const primaryActions = Array.from(document.querySelectorAll("button, [role='button'], a"))
            .map(el => el.innerText.trim())
            .filter(Boolean)
            .slice(0, 10);
          return {
            content_preview: text.slice(0, 1200),
            ready_state: document.readyState,
            headings,
            form_fields: formFields,
            primary_actions: primaryActions,
          };
        }
        """
        try:
            data = await self.page.evaluate(script)
            return {
                "content_preview": data.get("content_preview", ""),
                "ready_state": data.get("ready_state", "unknown"),
                "headings": data.get("headings", []),
                "form_fields": data.get("form_fields", []),
                "primary_actions": data.get("primary_actions", []),
            }
        except Exception:
            try:
                content_preview = await self.page.evaluate(
                    "() => (document.body && document.body.innerText ? document.body.innerText.slice(0, 1200) : '')"
                )
            except Exception:
                content_preview = ""
            return {
                "content_preview": content_preview,
                "ready_state": "unknown",
                "headings": [],
                "form_fields": [],
                "primary_actions": [],
            }

    async def _safe_title(self) -> str:
        try:
            return await self.page.title()
        except Exception:
            return ""

    async def _safe_input_value(self, selector: str) -> str:
        try:
            return await self.page.input_value(selector)
        except Exception:
            try:
                locator = self.page.locator(selector)
                return await locator.input_value()
            except Exception:
                return ""

    async def _wait_for_page_ready(self) -> Dict[str, Any]:
        ready_state = "unknown"
        network_idle = False
        dom_loaded = False
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            dom_loaded = True
        except Exception:
            dom_loaded = False
        try:
            await self.page.wait_for_load_state("networkidle", timeout=5000)
            network_idle = True
        except Exception:
            network_idle = False
        try:
            ready_state = await self.page.evaluate("() => document.readyState")
        except Exception:
            ready_state = "unknown"
        return {
            "ready": dom_loaded or ready_state in {"interactive", "complete"},
            "dom_loaded": dom_loaded,
            "network_idle": network_idle,
            "ready_state": ready_state,
        }

    async def _wait_after_interaction(self) -> None:
        try:
            await self.page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            await asyncio.sleep(0.15)

    def _state_changed(self, before: Dict[str, Any], after: Dict[str, Any]) -> bool:
        return bool(
            before.get("browser_dom_hash") != after.get("browser_dom_hash")
            or before.get("url") != after.get("url")
            or before.get("title") != after.get("title")
        )

    def _interaction_signals(
        self,
        action: str,
        verified: bool,
        before: Dict[str, Any],
        after: Dict[str, Any],
    ) -> List[str]:
        signals = [f"browser_{action}"]
        if verified:
            signals.append("semantic_state_changed")
        if before.get("url") != after.get("url"):
            signals.append("url_changed")
        if before.get("browser_dom_hash") != after.get("browser_dom_hash"):
            signals.append("page_changed")
        signals.append("semantic_state_captured")
        return signals

    def _semantic_signals(self, state: Dict[str, Any]) -> List[str]:
        signals = ["page_observed"]
        if state.get("ready_state") in {"interactive", "complete"}:
            signals.append("page_ready")
        if state.get("interactive_count", 0):
            signals.append("interactive_elements_found")
        if state.get("form_fields"):
            signals.append("form_detected")
        return signals

    def _hash_payload(self, payload: Dict[str, Any]) -> str:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        return digest.hexdigest()

    def _failure(self, action: str, exc: Exception, **context: Any) -> Dict[str, Any]:
        return {
            "success": False,
            "action": action,
            "error": str(exc),
            "error_code": self._classify_error(action, exc),
            **context,
        }

    def _classify_error(self, action: str, exc: Exception) -> str:
        text = str(exc).lower()
        if "timeout" in text:
            return f"{action.upper()}_TIMEOUT"
        if "not found" in text or "strict mode violation" in text:
            return f"{action.upper()}_TARGET_NOT_FOUND"
        if "selector" in text:
            return f"{action.upper()}_SELECTOR_ERROR"
        return f"{action.upper()}_FAILED"


async def main():
    nav = BrowserNavigator(headless=True)
    await nav.start()
    result = await nav.navigate_with_readiness_check("https://www.google.com")
    print(f"📊 [BROWSER] Page Title: {result['state']['title']}")
    await nav.stop()


if __name__ == "__main__":
    asyncio.run(main())
