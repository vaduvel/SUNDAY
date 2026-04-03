"""Unified browser agent for JARVIS.

This module ties together:
- deterministic Playwright navigation via BrowserNavigator
- lightweight web search via DuckDuckGo
- optional high-level browser-use execution when dependencies exist
"""

from __future__ import annotations

import json
import logging
import os
import re
from importlib.util import find_spec
from typing import Any, Dict, List, Optional

from core.runtime_config import configure_inception_openai_alias, load_project_env

load_project_env()
configure_inception_openai_alias()

logger = logging.getLogger(__name__)


class BrowserAgent:
    """Unified browser automation surface with graceful fallbacks."""

    def __init__(self):
        self.agent = None
        self._initialized = False
        self._navigator_cls = None
        self._browser_use_agent_cls = None
        self._browser_use_browser_cls = None
        self._chat_openai_cls = None
        self._capabilities: Dict[str, bool] = {
            "navigator": False,
            "search": False,
            "browser_use": False,
            "browser_use_agent": False,
        }
        self._check_availability()

    def _check_availability(self):
        """Discover which browser backends are usable in the current environment."""
        try:
            from tools.browser_navigator import BrowserNavigator

            self._navigator_cls = BrowserNavigator
            self._capabilities["navigator"] = True
        except Exception as exc:
            logger.warning("BrowserNavigator unavailable: %s", exc)

        try:
            self._capabilities["search"] = find_spec("duckduckgo_search") is not None
            if not self._capabilities["search"]:
                logger.info("DuckDuckGo search unavailable: module not installed")
        except Exception as exc:
            logger.warning("DuckDuckGo search detection failed: %s", exc)

        try:
            self._capabilities["browser_use"] = (
                find_spec("browser_use") is not None
            )
            if not self._capabilities["browser_use"]:
                logger.info("browser-use backend unavailable: module not installed")
        except Exception as exc:
            logger.warning("browser-use detection failed: %s", exc)

        try:
            self._capabilities["browser_use_agent"] = (
                find_spec("langchain_openai") is not None
            )
        except Exception:
            self._capabilities["browser_use_agent"] = False

    async def _ensure_browser_use_classes(self) -> bool:
        """Import browser-use classes only when they are actually needed."""
        if self._browser_use_browser_cls and self._browser_use_agent_cls:
            return True

        try:
            from browser_use import Agent, Browser

            self._browser_use_agent_cls = Agent
            self._browser_use_browser_cls = Browser
            self._capabilities["browser_use"] = True
            return True
        except Exception as exc:
            logger.warning("browser-use import failed: %s", exc)
            return False

    async def _ensure_chat_openai(self) -> bool:
        """Import langchain-openai only when advanced browser-use is requested."""
        if self._chat_openai_cls is not None:
            return True

        try:
            from langchain_openai import ChatOpenAI

            self._chat_openai_cls = ChatOpenAI
            self._capabilities["browser_use_agent"] = True
            return True
        except Exception:
            self._capabilities["browser_use_agent"] = False
            return False

    async def initialize(self, task: str | None = None):
        """Initialize the highest-capability browser agent available."""
        if self._initialized:
            return True

        if (
            self._capabilities["browser_use"]
            and self._capabilities["browser_use_agent"]
            and (os.getenv("OPENAI_API_KEY") or os.getenv("INCEPTION_API_KEY"))
        ):
            try:
                await self._ensure_browser_use_classes()
                await self._ensure_chat_openai()
                llm = self._chat_openai_cls(
                    model="gpt-4o",
                    api_key=os.getenv("OPENAI_API_KEY") or os.getenv("INCEPTION_API_KEY"),
                    base_url=os.getenv("OPENAI_API_BASE"),
                )
                self.agent = self._browser_use_agent_cls(
                    llm=llm,
                    task=task or "Help the user with web browsing tasks",
                    browser_context=None,
                )
                self._initialized = True
                return True
            except Exception as exc:
                logger.warning("browser-use agent init failed, falling back: %s", exc)

        self._initialized = self._capabilities["navigator"] or self._capabilities["browser_use"]
        return self._initialized

    async def navigate_to(self, url: str) -> Dict[str, Any]:
        """Navigate to a URL and return a semantic summary."""
        if self._capabilities["navigator"]:
            navigator = self._navigator_cls(headless=True)
            try:
                result = await navigator.navigate_with_readiness_check(url)
                return {
                    "success": result.get("success", False),
                    "url": url,
                    "type": "navigation",
                    "verified": result.get("verified", False),
                    **result.get("state", {}),
                }
            finally:
                await navigator.stop()

        if self._capabilities["browser_use"] and await self._ensure_browser_use_classes():
            browser = self._browser_use_browser_cls()
            try:
                page = await browser.new_page()
                await page.goto(url)
                title = await page.title()
                content = await page.evaluate(
                    "() => (document.body && document.body.innerText ? document.body.innerText.slice(0, 2000) : '')"
                )
                return {
                    "success": True,
                    "url": url,
                    "title": title,
                    "content": content[:800],
                    "type": "navigation",
                }
            except Exception as exc:
                return {"success": False, "error": str(exc), "url": url}
            finally:
                await browser.close()

        return {"success": False, "error": "No browser backend available", "url": url}

    async def search_web(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Search the web with DuckDuckGo and return structured results."""
        if not self._capabilities["search"]:
            return {
                "success": False,
                "error": "duckduckgo-search is not installed",
                "query": query,
            }

        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                raw_results = list(ddgs.text(query, max_results=limit))

            results = [
                {
                    "title": item.get("title", "Untitled"),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", ""),
                }
                for item in raw_results
            ]
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
                "type": "search",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "query": query}

    async def extract_from_page(self, url: str, extraction_goal: str) -> Dict[str, Any]:
        """Extract visible content from a page using the deterministic navigator."""
        if self._capabilities["navigator"]:
            navigator = self._navigator_cls(headless=True)
            try:
                await navigator.navigate_with_readiness_check(url)
                extracted = await navigator.extract_text("body", max_chars=5000)
                return {
                    "success": True,
                    "url": url,
                    "title": extracted.get("title", ""),
                    "content": extracted.get("text", ""),
                    "extraction_goal": extraction_goal,
                    "type": "extraction",
                }
            finally:
                await navigator.stop()

        navigation = await self.navigate_to(url)
        if navigation.get("success"):
            return {
                "success": True,
                "url": url,
                "title": navigation.get("title", ""),
                "content": navigation.get("content", ""),
                "extraction_goal": extraction_goal,
                "type": "extraction",
            }

        return navigation

    async def extract_structured_page_data(
        self, schema: Dict[str, Any], url: str | None = None
    ) -> Dict[str, Any]:
        """Extract structured page data instead of only raw text."""
        if not self._capabilities["navigator"]:
            return {
                "success": False,
                "error": "No deterministic browser backend available",
                "schema": schema,
            }

        navigator = self._navigator_cls(headless=True)
        try:
            if url:
                await navigator.navigate_with_readiness_check(url)
            state = await navigator.capture_semantic_page_state()
            content = "\n".join(
                [
                    state.get("title", ""),
                    *state.get("headings", []),
                    state.get("content_preview", ""),
                ]
            )
            data = {
                key: self._coerce_schema_value(key, schema.get(key), content, state)
                for key in schema
            }
            return {
                "success": True,
                "url": state.get("url", url),
                "title": state.get("title", ""),
                "data": data,
                "type": "structured_extraction",
            }
        finally:
            await navigator.stop()

    async def run_browser_subtask(self, subtask: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single browser subtask with verification metadata."""
        action = (subtask.get("action") or "").lower()
        url = subtask.get("url")
        selector = subtask.get("selector")
        text = subtask.get("text")
        schema = subtask.get("schema")

        if action in {"navigate", "open"} and url:
            result = await self.navigate_to(url)
        elif action in {"extract", "read"} and schema is not None:
            result = await self.extract_structured_page_data(schema, url=url)
        elif action in {"extract", "read"} and url:
            result = await self.extract_from_page(url, subtask.get("goal", "extract page"))
        elif action == "click" and self._capabilities["navigator"]:
            navigator = self._navigator_cls(headless=True)
            try:
                if url:
                    await navigator.navigate_with_readiness_check(url)
                result = await navigator.click_with_verification(selector=selector, text=text)
            finally:
                await navigator.stop()
        elif action in {"type", "fill"} and selector and self._capabilities["navigator"]:
            navigator = self._navigator_cls(headless=True)
            try:
                if url:
                    await navigator.navigate_with_readiness_check(url)
                result = await navigator.type_with_verification(selector, text or "")
            finally:
                await navigator.stop()
        else:
            result = await self._execute_legacy_mapping(subtask.get("task") or json.dumps(subtask))

        result["subtask"] = subtask
        result["verified"] = result.get("verified", result.get("success", False))
        return result

    async def execute_browser_task(
        self, task: str, success_criteria: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """Decompose a browser task into deterministic subtasks when possible."""
        lowered = task.lower()
        subtasks: List[Dict[str, Any]] = []
        url_match = re.search(r"https?://\S+", task)
        url = url_match.group(0) if url_match else None

        if url:
            subtasks.append({"action": "navigate", "url": url, "task": task})

        if any(word in lowered for word in ["extract", "summarize", "read", "content"]):
            subtasks.append(
                {
                    "action": "extract",
                    "url": url,
                    "goal": success_criteria.get("goal") if success_criteria else task,
                    "schema": success_criteria.get("schema") if success_criteria else None,
                    "task": task,
                }
            )

        if lowered.startswith(("search ", "find ")):
            query = task.split(" ", 1)[1] if " " in task else task
            subtasks.append({"action": "search", "task": query})

        if not subtasks:
            subtasks.append({"action": "generic", "task": task})

        results: List[Dict[str, Any]] = []
        overall_success = True
        for subtask in subtasks:
            if subtask["action"] == "search":
                result = await self.search_web(subtask["task"])
            else:
                result = await self.run_browser_subtask(subtask)
            results.append(result)
            overall_success = overall_success and bool(result.get("success"))

        last_state = {}
        last_signals: List[str] = []
        for item in reversed(results):
            if item.get("after"):
                last_state = item.get("after", {})
                last_signals = list(item.get("signals", []))
                break
            if item.get("state"):
                last_state = item.get("state", {})
                last_signals = list(item.get("signals", []))
                break

        return {
            "success": overall_success,
            "task": task,
            "success_criteria": success_criteria or {},
            "subtasks": results,
            "verified": all(item.get("verified", item.get("success", False)) for item in results),
            "after": last_state or None,
            "signals": last_signals,
            "url": (last_state or {}).get("url"),
            "title": (last_state or {}).get("title"),
            "type": "browser_task",
        }

    async def execute_task(self, task: str) -> Dict[str, Any]:
        """Execute a browser task, preferring browser-use when fully configured."""
        if await self.initialize(task) and self.agent is not None:
            try:
                result = await self.agent.run()
                return {
                    "success": True,
                    "task": task,
                    "result": str(result)[:1000],
                    "type": "agent_task",
                    "mode": "browser_use_agent",
                }
            except Exception as exc:
                logger.warning("browser-use task failed, falling back: %s", exc)

        lowered = task.lower()
        if lowered.startswith(("search ", "find ")) or re.search(r"https?://\S+", task) or any(
            word in lowered for word in ["extract", "summarize", "content", "page", "read"]
        ):
            decomposed = await self.execute_browser_task(task, {})
            decomposed["mode"] = "deterministic_browser_task"
            return decomposed

        return await self._execute_legacy_mapping(task)

    async def _execute_legacy_mapping(self, task: str) -> Dict[str, Any]:
        lowered = task.lower()
        if lowered.startswith(("search ", "find ")):
            query = task.split(" ", 1)[1] if " " in task else task
            result = await self.search_web(query)
            result["mode"] = "search_fallback"
            return result

        url_match = re.search(r"https?://\S+", task)
        if url_match:
            url = url_match.group(0)
            if any(word in lowered for word in ["extract", "summarize", "content", "page"]):
                result = await self.extract_from_page(url, task)
                result["mode"] = "navigator_extract"
                return result
            result = await self.navigate_to(url)
            result["mode"] = "navigator"
            return result

        return {
            "success": False,
            "task": task,
            "error": "Task could not be mapped to an available browser backend.",
            "mode": "unhandled",
        }

    def _coerce_schema_value(
        self,
        key: str,
        subschema: Any,
        content: str,
        state: Dict[str, Any],
    ) -> Any:
        del subschema
        lowered_key = key.lower()
        if "title" in lowered_key:
            return state.get("title", "")
        if "url" in lowered_key:
            return state.get("url", "")
        if "heading" in lowered_key:
            return state.get("headings", [])
        if "action" in lowered_key or "button" in lowered_key:
            return state.get("primary_actions", [])
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return lines[0][:200] if lines else ""

    def get_status(self) -> Dict[str, Any]:
        """Get browser agent status with backend detail."""
        advanced_agent_ready = bool(
            self._capabilities["browser_use"]
            and self._capabilities["browser_use_agent"]
            and (os.getenv("OPENAI_API_KEY") or os.getenv("INCEPTION_API_KEY"))
        )
        return {
            "available": any(self._capabilities.values()),
            "initialized": self._initialized,
            "mode": (
                "browser_use_agent"
                if advanced_agent_ready
                else "navigator"
                if self._capabilities["navigator"]
                else "search_only"
                if self._capabilities["search"]
                else "unavailable"
            ),
            "backends": dict(self._capabilities),
            "requires_api_key": advanced_agent_ready,
            "supports": [
                "navigate_to",
                "search_web",
                "extract_from_page",
                "extract_structured_page_data",
                "run_browser_subtask",
                "execute_browser_task",
                "execute_task",
            ],
        }


_browser_agent: BrowserAgent | None = None


def get_browser_agent() -> BrowserAgent:
    global _browser_agent
    if _browser_agent is None:
        _browser_agent = BrowserAgent()
    return _browser_agent


if __name__ == "__main__":
    import asyncio

    async def test():
        ba = get_browser_agent()
        print("🌐 Browser Agent Status:")
        print(ba.get_status())

    asyncio.run(test())
