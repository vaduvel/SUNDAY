"""J.A.R.V.I.S. Interactive Chat Mode — TOOL-WIRED EDITION

Conversa direct cu JARVIS în timp real.
Acum cu agentic tool loop: LLM → execută tools → LLM → ... → răspuns final.
"""

import os
import sys
import json
import asyncio
import logging
import re
import subprocess
from datetime import datetime
from typing import Dict, List, Tuple, Any

# Setup
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.runtime_config import (
    configure_inception_openai_alias,
    load_project_env,
    resolve_obsidian_vault_path,
)

load_project_env(os.path.dirname(os.path.abspath(__file__)))
configure_inception_openai_alias()

from core.brain import call_brain_with_tools, PRO_MODEL
from tools.obsidian_researcher import ObsidianResearcher
from tools.memory_tool import (
    StructuredMemory,
    get_memory_summary,
    search_memory as _search_mem,
)
from tools.search_tool import duckduckgo_search
from tools.file_manager import read_text_file, write_text_file
from tools.obsidian_researcher import obsidian_search as _obsidian_search
from core.prompts import generate_galaxy_exhaustive_prompt
from core.identity_context import IdentityContextManager
from core.capability_registry import (
    looks_like_capability_query,
    render_user_capability_summary,
)
from core.output_hygiene import sanitize_assistant_output

logger = logging.getLogger(__name__)

# ─── JarvisEngine singleton (lazy) ─────────────────────────────
_engine_instance = None
OBSIDIAN_VAULT_PATH = str(
    resolve_obsidian_vault_path(os.path.dirname(os.path.abspath(__file__)))
)


def _get_engine():
    global _engine_instance
    if _engine_instance is None:
        try:
            from core.jarvis_engine import JarvisEngine

            _engine_instance = JarvisEngine()
            logger.info("✅ [TOOLS] JarvisEngine loaded — MCP tools active")
        except Exception as e:
            logger.warning(
                f"⚠️ [TOOLS] JarvisEngine unavailable: {e} — basic tools only"
            )
    return _engine_instance


# ─── Helpers ───────────────────────────────────────────────────


def _mcp_to_openai(tool_def: dict) -> dict:
    """Convert MCPRegistry tool def → OpenAI function calling format."""
    params = tool_def.get("parameters", {}) or {
        "type": "object",
        "properties": {},
        "required": [],
    }
    return {
        "type": "function",
        "function": {
            "name": tool_def["name"],
            "description": tool_def.get("description", ""),
            "parameters": params,
        },
    }


# ─── Basic tool definitions (always available) ─────────────────

_BASIC_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web with DuckDuckGo. Use for news, facts, prices, docs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from disk. Returns its text content.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text content to a file on disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a bash command (ls, git, python, etc.) and return output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_summary",
            "description": "Get a summary of past missions and lessons learned from organizational memory.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search organizational memory by keywords (comma-separated).",
            "parameters": {
                "type": "object",
                "properties": {"keywords": {"type": "string"}},
                "required": ["keywords"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obsidian_search",
            "description": "Search the Obsidian knowledge vault for stored notes and knowledge.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]

_BLOCKED_COMMANDS = [
    "rm -rf /",
    "sudo rm",
    "mkfs",
    "> /dev/",
    ":(){:|:&};:",
    "chmod -R 777",
]

_TOOL_FOCUS_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "name": "code-intelligence",
        "keywords": (
            "code",
            "cod",
            "repo",
            "workspace",
            "modul",
            "module",
            "functie",
            "funcție",
            "function",
            "class",
            "symbol",
            "definition",
            "definit",
            "refactor",
            "implement",
            "fix",
            "bug",
            "audit",
            "tsx",
            "python",
            ".py",
            ".ts",
        ),
        "tools": (
            "index_codebase",
            "find_definition",
            "search_code",
            "impact_analysis",
            "symbol_context",
            "detect_changes",
            "memory_full_context",
            "memory_scope_summary",
            "ultraplan",
            "coordinator_prepare",
            "plan_create",
            "plan_current",
        ),
        "guidance": (
            "Pentru cod și repo: indexează sau caută simbolurile înainte să ghicești, "
            "verifică blast radius înainte de schimbări mai mari și cheamă ULTRAPLAN / "
            "coordinator dacă taskul traversează mai multe module."
        ),
    },
    {
        "name": "memory-runtime",
        "keywords": (
            "remember",
            "memorie",
            "memory",
            "context",
            "ce am discutat",
            "ce am vorbit",
            "istoric",
            "history",
            "lesson",
            "lec",
            "profile",
            "preferin",
        ),
        "tools": (
            "memory_full_context",
            "memory_recall_structured",
            "memory_scope_recall",
            "memory_scope_summary",
            "memory_context",
            "memory_summary",
            "search_memory",
            "identity_anchor",
        ),
        "guidance": (
            "Pentru memorie și continuitate: folosește mai întâi contextul complet și "
            "scope memory înainte să răspunzi din presupuneri."
        ),
    },
    {
        "name": "planning-and-agency",
        "keywords": (
            "plan",
            "strategie",
            "strategy",
            "complex",
            "coordinator",
            "agent",
            "agen",
            "mission",
            "misiune",
            "roadmap",
            "decompose",
            "break down",
            "step",
            "pași",
            "pasi",
        ),
        "tools": (
            "ultraplan",
            "coordinator_prepare",
            "coordinator_execute",
            "coordinator_status",
            "plan_create",
            "plan_current",
            "plan_update_subtask",
            "plan_hint",
            "session_start",
            "session_current",
        ),
        "guidance": (
            "Pentru taskuri complexe: preferă să creezi un plan persistent și să armezi "
            "coordinatorul când sunt mai multe roluri sau etape dependente."
        ),
    },
    {
        "name": "research-and-web",
        "keywords": (
            "web",
            "internet",
            "latest",
            "recent",
            "news",
            "doc",
            "docs",
            "search",
            "caut",
            "browse",
            "browser",
            "url",
            "site",
            "online",
        ),
        "tools": (
            "web_search",
            "browser_search",
            "browser_extract",
            "browser_structured_extract",
            "browser_task",
            "stagehand_observe",
            "stagehand_extract",
        ),
        "guidance": (
            "Pentru informații actuale sau pagini web: caută sau extrage direct din browser "
            "în loc să răspunzi din memorie statică."
        ),
    },
)

_TOOL_FOCUS_ALWAYS = (
    "identity_anchor",
    "memory_full_context",
    "memory_scope_summary",
    "plan_current",
)
_MAX_FOCUSED_TOOL_COUNT = 28


async def _exec_run_command(command: str) -> str:
    for bad in _BLOCKED_COMMANDS:
        if bad in command:
            return f"❌ Comandă blocată (pattern periculos): '{bad}'"
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )
        out = result.stdout[-2000:] if result.stdout else ""
        err = result.stderr[-500:] if result.stderr else ""
        return out or err or "✅ Comandă executată (fără output)."
    except subprocess.TimeoutExpired:
        return "⏰ Timeout (60s)."
    except Exception as e:
        return f"❌ Eroare: {e}"


_BASIC_HANDLERS: Dict[str, Any] = {
    "web_search": lambda query: asyncio.get_event_loop().run_in_executor(
        None, lambda: duckduckgo_search(query=query, max_results=5)
    ),
    "read_file": lambda path: asyncio.get_event_loop().run_in_executor(
        None, lambda: read_text_file(path)
    ),
    "write_file": lambda path, content: asyncio.get_event_loop().run_in_executor(
        None, lambda: write_text_file(path, content)
    ),
    "run_command": _exec_run_command,
    "memory_summary": lambda: asyncio.get_event_loop().run_in_executor(
        None, get_memory_summary
    ),
    "search_memory": lambda keywords: asyncio.get_event_loop().run_in_executor(
        None,
        lambda: (
            "\n".join(
                f"• {r.get('observation', '')[:200]}"
                for r in _search_mem(
                    [k.strip() for k in keywords.split(",") if k.strip()], limit=5
                )
            )
            or "Nu s-au găsit rezultate."
        ),
    ),
    "obsidian_search": lambda query: asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _obsidian_search(query, vault_path=OBSIDIAN_VAULT_PATH),
    ),
}


# ═══════════════════════════════════════════════════════════════
#  JARVIS CHAT
# ═══════════════════════════════════════════════════════════════


class JarvisChat:
    MAX_TOOL_ITERATIONS = 10

    def __init__(self, session_id: str = "chat", mode_hint: str = "chat"):
        self.obsidian = ObsidianResearcher(OBSIDIAN_VAULT_PATH)
        self.history: List[Dict] = []
        self.name = "JARVIS"
        self._tools_schema: List[Dict] | None = None
        self._handler_map: Dict[str, Any] | None = None
        self._tool_schema_by_name: Dict[str, Dict[str, Any]] = {}
        self.structured_memory = StructuredMemory()
        self.session_id = session_id
        self.mode_hint = mode_hint
        self._current_turn_input: str | None = None
        self.identity = IdentityContextManager(
            os.path.join(os.getcwd(), ".agent/brain_vault"),
            os.getcwd(),
        )

    # ─── System prompt ─────────────────────────────────────────

    def _system_prompt(self, skills_dna: str = None, **_: Any) -> str:
        rules_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "JARVIS.md"
        )
        project_rules = ""
        if os.path.exists(rules_path):
            with open(rules_path, "r") as f:
                project_rules = f.read()

        engine = _get_engine()
        mcp_tool_names = [t["name"] for t in engine.mcp.get_tool_listing()] if engine else []
        basic_tool_names = [tool["function"]["name"] for tool in _BASIC_TOOLS_SCHEMA]
        active_tool_list = list(dict.fromkeys([*basic_tool_names, *mcp_tool_names]))
        tool_names = ", ".join(active_tool_list) if active_tool_list else "unavailable"

        # Use provided skills_dna or generate default
        if skills_dna is None:
            skills_dna = (
                f"MCP Tools active: {tool_names}. "
                "Also: web_search, read_file, write_file, run_command, "
                "memory_summary, search_memory, obsidian_search."
            )
        memory_context = self.structured_memory.get_full_context(session_id=self.session_id)

        return generate_galaxy_exhaustive_prompt(
            os_info="macOS (Apple Silicon)",
            shell="zsh",
            project_rules=project_rules or "Dezvoltă sisteme de elită.",
            skills_dna=skills_dna,
            identity_anchor=self.identity.render_identity_block(),
            context_rules=self.identity.render_context_rules(
                active_tools=active_tool_list,
                memory_context=memory_context,
                mode_hint=self.mode_hint,
            ),
            capability_model=self.identity.render_capability_model(
                active_tools=active_tool_list,
                mode_hint=self.mode_hint,
            ),
        )

    def _active_tool_list(self) -> List[str]:
        engine = _get_engine()
        mcp_tool_names = [t["name"] for t in engine.mcp.get_tool_listing()] if engine else []
        basic_tool_names = [tool["function"]["name"] for tool in _BASIC_TOOLS_SCHEMA]
        return list(dict.fromkeys([*basic_tool_names, *mcp_tool_names]))

    # ─── Tool registry (built once, cached) ────────────────────

    def _build_tools_cache(self) -> Tuple[List[Dict], Dict[str, Any]]:
        schema = list(_BASIC_TOOLS_SCHEMA)
        handlers = dict(_BASIC_HANDLERS)
        schema_by_name = {
            tool["function"]["name"]: tool for tool in _BASIC_TOOLS_SCHEMA
        }

        engine = _get_engine()
        if engine:
            for tool_def in engine.mcp.get_tool_listing():
                name = tool_def["name"]
                if name in handlers:
                    continue  # don't override basic tools
                tool_schema = _mcp_to_openai(tool_def)
                schema.append(tool_schema)
                schema_by_name[name] = tool_schema

                def _make_handler(n):
                    async def _h(**kwargs):
                        return await engine.mcp.call_tool(n, kwargs)

                    return _h

                handlers[name] = _make_handler(name)

        self._tool_schema_by_name = schema_by_name
        return schema, handlers

    def _tokenize_focus_query(self, text: str) -> List[str]:
        return [
            token
            for token in re.findall(r"[a-zA-Z0-9_./-]+", (text or "").lower())
            if len(token) >= 3
        ]

    def _tool_focus_matches(self, user_input: str) -> List[dict[str, Any]]:
        lowered = (user_input or "").lower()
        return [
            profile
            for profile in _TOOL_FOCUS_PROFILES
            if any(keyword in lowered for keyword in profile["keywords"])
        ]

    def _tool_match_score(self, query_tokens: List[str], tool_name: str, description: str) -> int:
        if not query_tokens:
            return 0
        haystack = f"{tool_name} {description}".lower()
        score = 0
        for token in query_tokens:
            if token in tool_name.lower():
                score += 3
            elif token in haystack:
                score += 1
        return score

    def _focus_bundle_for_input(
        self, user_input: str
    ) -> Tuple[List[Dict], Dict[str, Any], str]:
        if self._tools_schema is None:
            self._tools_schema, self._handler_map = self._build_tools_cache()

        full_schema = self._tools_schema or []
        handler_map = self._handler_map or {}
        available_names = [tool["function"]["name"] for tool in full_schema]
        available_set = set(available_names)

        selected_names: List[str] = []

        def _add(name: str):
            if name in available_set and name not in selected_names:
                selected_names.append(name)

        for tool in _BASIC_TOOLS_SCHEMA:
            _add(tool["function"]["name"])
        for name in _TOOL_FOCUS_ALWAYS:
            _add(name)

        matched_profiles = self._tool_focus_matches(user_input)
        guidance_lines = [
            profile["guidance"]
            for profile in matched_profiles
            if profile.get("guidance")
        ]
        for profile in matched_profiles:
            for name in profile["tools"]:
                _add(name)

        query_tokens = self._tokenize_focus_query(user_input)
        lexical_scores: List[Tuple[int, str]] = []
        for name in available_names:
            if name in selected_names:
                continue
            description = self._tool_schema_by_name.get(name, {}).get("function", {}).get(
                "description", ""
            )
            score = self._tool_match_score(query_tokens, name, description)
            if score > 0:
                lexical_scores.append((score, name))

        lexical_scores.sort(key=lambda item: (-item[0], item[1]))
        for _score, name in lexical_scores:
            if len(selected_names) >= _MAX_FOCUSED_TOOL_COUNT:
                break
            _add(name)

        if not matched_profiles and len(selected_names) < min(len(available_names), 12):
            default_priority = (
                "search_code",
                "find_definition",
                "memory_recall_structured",
                "memory_scope_recall",
                "ultraplan",
                "coordinator_prepare",
                "session_current",
            )
            for name in default_priority:
                if len(selected_names) >= _MAX_FOCUSED_TOOL_COUNT:
                    break
                _add(name)

        selected_set = set(selected_names)
        focused_schema = [
            tool for tool in full_schema if tool["function"]["name"] in selected_set
        ]
        focused_handlers = {
            name: handler
            for name, handler in handler_map.items()
            if name in selected_set
        }

        focus_prompt = (
            "#### 0D. TOOL FOCUS FOR THIS TURN\n"
            f"- Focused tools for this request: {', '.join(selected_names[:18]) or 'basic tools'}\n"
            "- Do not brute-force every tool. Prefer the focused set above first.\n"
        )
        if guidance_lines:
            for line in guidance_lines:
                focus_prompt += f"- {line}\n"
        else:
            focus_prompt += (
                "- Dacă cererea devine multi-step, code-heavy sau cross-module, folosește "
                "ULTRAPLAN, memory context și code intelligence înainte de a improviza.\n"
            )

        return focused_schema, focused_handlers, focus_prompt

    def _get_tools(self) -> Tuple[List[Dict], Dict[str, Any]]:
        if self._tools_schema is None:
            self._tools_schema, self._handler_map = self._build_tools_cache()
            logger.info(f"🔧 [TOOLS] {len(self._tools_schema)} tools available")
        if self._current_turn_input:
            focused_schema, focused_handlers, _focus_prompt = self._focus_bundle_for_input(
                self._current_turn_input
            )
            if focused_schema:
                logger.info(
                    "🎯 [TOOLS] Focused %s/%s tools for turn",
                    len(focused_schema),
                    len(self._tools_schema or []),
                )
                return focused_schema, focused_handlers
        return self._tools_schema, self._handler_map

    def _get_turn_focus_prompt(self, user_input: str) -> str:
        _schema, _handlers, focus_prompt = self._focus_bundle_for_input(user_input)
        return focus_prompt

    def _agent_memory_runtime(self):
        engine = _get_engine()
        return getattr(engine, "agent_memory", None) if engine else None

    def _store_scope_memory(
        self,
        scope: str,
        content: str,
        *,
        tags: List[str] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        runtime = self._agent_memory_runtime()
        if not runtime:
            return
        snippet = (content or "").strip()
        if not snippet:
            return
        try:
            runtime.write(
                scope,
                snippet[:1200],
                session_id=self.session_id,
                tags=tags,
                metadata=metadata,
            )
        except Exception as exc:
            logger.debug("[MEMORY_SCOPE] %s", exc)

    def _looks_like_taskful_turn(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        task_markers = (
            "implement",
            "fix",
            "audit",
            "plan",
            "research",
            "caut",
            "refactor",
            "build",
            "create",
            "coord",
            "browser",
            "computer",
            "co-work",
            "cowork",
            "analyze",
            "analize",
        )
        return len(lowered.split()) >= 6 or any(marker in lowered for marker in task_markers)

    def _inject_scope_memory_summary(self, messages: List[Dict]) -> None:
        runtime = self._agent_memory_runtime()
        if not runtime:
            return
        try:
            summary = runtime.summary(session_id=self.session_id)
        except Exception:
            return
        if not summary:
            return
        preview_parts = []
        if summary.get("working_preview"):
            preview_parts.append(
                "working=" + " | ".join(item for item in summary["working_preview"][:3] if item)
            )
        if summary.get("tool_preview"):
            preview_parts.append(
                "tool=" + ", ".join(item for item in summary["tool_preview"][:3] if item)
            )
        if summary.get("personal_preview"):
            preview_parts.append(
                "personal=" + ", ".join(item for item in summary["personal_preview"][:3] if item)
            )
        counts = (
            f"working={summary.get('working_count', 0)}, "
            f"personal={summary.get('personal_count', 0)}, "
            f"tool={summary.get('tool_count', 0)}, "
            f"episodic={summary.get('episodic_count', 0)}"
        )
        messages.append(
            {
                "role": "system",
                "content": (
                    "Memory scopes summary:\n"
                    f"- Counts: {counts}\n"
                    f"- Preview: {' ; '.join(preview_parts) if preview_parts else 'No scope previews yet.'}"
                ),
            }
        )

    # ─── Tool executor ─────────────────────────────────────────

    async def _execute_tool(self, name: str, args: Dict, handler_map: Dict) -> str:
        handler = handler_map.get(name)
        if not handler:
            return f"❌ Tool necunoscut: '{name}'"
        try:
            result = handler(**args)
            if asyncio.iscoroutine(result):
                result = await result
            # run_in_executor returns a Future/coroutine too
            if hasattr(result, "__await__"):
                result = await result
            rendered = str(result)
            engine = _get_engine()
            if engine and getattr(engine, "result_budget", None):
                budgeted = engine.result_budget.check_limit(name, rendered)
                if budgeted.get("allowed"):
                    rendered = str(budgeted.get("content", rendered))
            self._store_scope_memory(
                "tool",
                f"{name}: {rendered[:500]}",
                tags=[name],
                metadata={
                    "tool_name": name,
                    "outcome": "success" if not rendered.startswith("❌") else "error",
                },
            )
            return rendered[:3000]
        except Exception as e:
            error_text = f"❌ Tool error ({name}): {e}"
            self._store_scope_memory(
                "tool",
                error_text,
                tags=[name, "error"],
                metadata={"tool_name": name, "outcome": "error"},
            )
            return error_text

    # ─── Core agentic loop ──────────────────────────────────────

    async def _agentic_loop(
        self, messages: List[Dict], *, verbose: bool = False
    ) -> str:
        """Run tool-calling loop. Returns final text response."""
        tools_schema, handler_map = self._get_tools()

        for iteration in range(self.MAX_TOOL_ITERATIONS):
            msg = await call_brain_with_tools(
                messages, tools=tools_schema, model=PRO_MODEL
            )

            tool_calls = getattr(msg, "tool_calls", None)

            if not tool_calls:
                return sanitize_assistant_output(msg.content or "")

            # ── Append assistant message with tool_calls ──────
            tc_list = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]
            messages.append(
                {"role": "assistant", "content": msg.content, "tool_calls": tc_list}
            )

            # ── Execute each tool call ────────────────────────
            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                if verbose:
                    print(
                        f"\n  🔧 {tool_name}({', '.join(f'{k}={repr(v)[:40]}' for k, v in args.items())})...",
                        end="",
                        flush=True,
                    )

                result_str = await self._execute_tool(tool_name, args, handler_map)

                if verbose:
                    status = "❌" if result_str.startswith("❌") else "✅"
                    print(f" {status}", end="", flush=True)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    }
                )

        return "⚠️ Limită iterații atinsă."

    # ─── Public chat methods ────────────────────────────────────

    async def chat(self, user_input: str) -> str:
        if user_input.startswith("/"):
            return await self._handle_command(user_input)

        self.history.append({"role": "user", "content": user_input})
        self.structured_memory.store_short_term(
            content=user_input, role="user", session_id=self.session_id
        )
        self._store_scope_memory(
            "working",
            user_input,
            metadata={"role": "user"},
        )
        if self._looks_like_taskful_turn(user_input):
            self._store_scope_memory(
                "task",
                f"User goal: {user_input}",
                tags=["user_goal"],
                metadata={"context": self.mode_hint},
            )

        messages = [{"role": "system", "content": self._system_prompt()}]
        for msg in self.history[-10:]:
            messages.append(msg)
        messages.append({"role": "system", "content": self._get_turn_focus_prompt(user_input)})

        # Inject relevant memory context
        try:
            summary = get_memory_summary()
            if summary and len(summary) > 10:
                messages.append(
                    {"role": "system", "content": f"Memorie: {summary[:500]}"}
                )
        except Exception:
            pass

        try:
            full_context = self.structured_memory.get_full_context(
                query=user_input, session_id=self.session_id
            )
            if full_context:
                messages.append(
                    {
                        "role": "system",
                        "content": f"Structured memory: {full_context[:1200]}",
                    }
                )
        except Exception:
            pass

        self._inject_scope_memory_summary(messages)

        if looks_like_capability_query(user_input):
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Capability self-check (ground truth from runtime wiring):\n"
                        + render_user_capability_summary(
                            active_tools=self._active_tool_list(),
                            workspace_root=os.getcwd(),
                            mode_hint=self.mode_hint,
                        )
                        + "\nConfirm concret ce poți face ACUM și propune imediat următorul pas util."
                    ),
                }
            )

        self._current_turn_input = user_input
        try:
            response = sanitize_assistant_output(
                await self._agentic_loop(messages, verbose=False),
                user_message=user_input,
            )
        finally:
            self._current_turn_input = None
        self.history.append({"role": "assistant", "content": response})
        self.structured_memory.store_short_term(
            content=response, role="assistant", session_id=self.session_id
        )
        self._store_scope_memory(
            "working",
            response,
            metadata={"role": "assistant"},
        )
        if self._looks_like_taskful_turn(user_input):
            self._store_scope_memory(
                "task",
                f"Assistant outcome: {response[:800]}",
                tags=["assistant_outcome"],
                metadata={"context": user_input[:200]},
            )
        self._reflex_learning(user_input, response)
        return response

    async def stream_chat(self, user_input: str):
        """Chat cu output vizibil: afișează tool calls, apoi răspunsul final."""
        if user_input.startswith("/"):
            result = await self._handle_command(user_input)
            print(result)
            return

        self.history.append({"role": "user", "content": user_input})
        self.structured_memory.store_short_term(
            content=user_input, role="user", session_id=self.session_id
        )
        self._store_scope_memory(
            "working",
            user_input,
            metadata={"role": "user"},
        )
        if self._looks_like_taskful_turn(user_input):
            self._store_scope_memory(
                "task",
                f"User goal: {user_input}",
                tags=["user_goal"],
                metadata={"context": self.mode_hint},
            )

        messages = [{"role": "system", "content": self._system_prompt()}]
        for msg in self.history[-10:]:
            messages.append(msg)
        messages.append({"role": "system", "content": self._get_turn_focus_prompt(user_input)})

        try:
            summary = get_memory_summary()
            if summary and len(summary) > 10:
                messages.append(
                    {"role": "system", "content": f"Memorie: {summary[:500]}"}
                )
        except Exception:
            pass

        try:
            full_context = self.structured_memory.get_full_context(
                query=user_input, session_id=self.session_id
            )
            if full_context:
                messages.append(
                    {
                        "role": "system",
                        "content": f"Structured memory: {full_context[:1200]}",
                    }
                )
        except Exception:
            pass

        self._inject_scope_memory_summary(messages)

        if looks_like_capability_query(user_input):
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Capability self-check (ground truth from runtime wiring):\n"
                        + render_user_capability_summary(
                            active_tools=self._active_tool_list(),
                            workspace_root=os.getcwd(),
                            mode_hint=self.mode_hint,
                        )
                        + "\nConfirm concret ce poți face ACUM și propune imediat următorul pas util."
                    ),
                }
            )

        print(f"🤖 {self.name}: ", end="", flush=True)

        self._current_turn_input = user_input
        try:
            response = sanitize_assistant_output(
                await self._agentic_loop(messages, verbose=True),
                user_message=user_input,
            )
        finally:
            self._current_turn_input = None

        # Print final response (with newline after tool status chars)
        print(f"\n{response}", flush=True)

        self.history.append({"role": "assistant", "content": response})
        self.structured_memory.store_short_term(
            content=response, role="assistant", session_id=self.session_id
        )
        self._store_scope_memory(
            "working",
            response,
            metadata={"role": "assistant"},
        )
        if self._looks_like_taskful_turn(user_input):
            self._store_scope_memory(
                "task",
                f"Assistant outcome: {response[:800]}",
                tags=["assistant_outcome"],
                metadata={"context": user_input[:200]},
            )
        self._reflex_learning(user_input, response)
        print()

    # ─── Reflex learning ───────────────────────────────────────

    def _reflex_learning(self, question: str, answer: str):
        async def run_reflection():
            try:
                reflection_prompt = (
                    f"Ești modulul de memorie JARVIS.\n"
                    f"User: {question}\nJARVIS: {answer[:300]}...\n\n"
                    "Extrage informația cheie care merită memorată. "
                    "Format: o propoziție scurtă + titlu 3-4 cuvinte. "
                    "Include [[Link-uri]] unde e cazul."
                )
                from core.brain import call_brain

                reflection = await call_brain(
                    [{"role": "system", "content": reflection_prompt}], model=PRO_MODEL
                )
                if "ERROR" not in reflection:
                    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
                    title = f"Reflex_{date_str}"
                    content = (
                        f"---\ntags: [jarvis-reflex, learning]\n---\n"
                        f"# Reflecție Autonomă\n\n{reflection}\n\n---\n"
                        f"Context Original:\n> Q: {question}\n> A: {answer[:200]}..."
                    )
                    self.obsidian.create_note(title=title, content=content)
                    print(f"🧠 [REFLEX] Stored: {title}")
            except Exception as e:
                logger.debug(f"[REFLEX] {e}")

        asyncio.create_task(run_reflection())

    # ─── Commands ──────────────────────────────────────────────

    async def _handle_command(self, cmd: str) -> str:
        cmd = cmd.strip().lower()

        if cmd == "/help":
            tools_schema, _ = self._get_tools()
            tool_list = "\n".join(
                f"  - {t['function']['name']}: {t['function']['description'][:60]}"
                for t in tools_schema
            )
            return (
                f"📋 Comenzi:\n"
                f"- /tools    — listează toate tool-urile active\n"
                f"- /capabilities — arată capabilitățile reale ale runtime-ului\n"
                f"- /memorie  — rezumat memorie\n"
                f"- /obsidian [query] — caută în vault\n"
                f"- /history  — ultimele 5 mesaje\n"
                f"- /clear    — șterge istoricul\n"
                f"- /quit     — ieși\n\n"
                f"🔧 Tool-uri active ({len(tools_schema)}):\n{tool_list}"
            )

        elif cmd == "/tools":
            tools_schema, _ = self._get_tools()
            lines = [f"🔧 {len(tools_schema)} tool-uri active:\n"]
            for t in tools_schema:
                f = t["function"]
                lines.append(f"  [{f['name']}] {f['description'][:70]}")
            return "\n".join(lines)

        elif cmd == "/capabilities":
            return render_user_capability_summary(
                active_tools=self._active_tool_list(),
                workspace_root=os.getcwd(),
                mode_hint=self.mode_hint,
            )

        elif cmd == "/memorie":
            try:
                return get_memory_summary()[:1000] or "Nu există memorie încă."
            except Exception as e:
                return f"Eroare: {e}"

        elif cmd == "/history":
            if not self.history:
                return "Nu ai încă istoric."
            lines = []
            for msg in self.history[-5:]:
                role = "👤" if msg["role"] == "user" else "🤖"
                lines.append(f"{role} {msg['content'][:80]}...")
            return "\n".join(lines)

        elif cmd == "/clear":
            self.history = []
            return "✅ Istoric șters."

        elif cmd == "/quit":
            print("👋 La revedere!")
            sys.exit(0)

        elif cmd.startswith("/obsidian"):
            query = cmd.replace("/obsidian", "").strip()
            if not query:
                return "❌ Specifică un query. Ex: /obsidian ANAF"
            return self.obsidian.search_notes(query)

        else:
            return f"❌ Comandă necunoscută: {cmd}. Tastează /help."

    # ─── Entry point ───────────────────────────────────────────

    async def start(self):
        tools_schema, _ = self._get_tools()
        print(f"""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║    ██████╗ ███████╗████████╗██████╗  ██████╗             ║
║    ██╔══██╗██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗            ║
║    ██████╔╝█████╗     ██║   ██████╔╝██║   ██║            ║
║    ██╔══██╗██╔══╝     ██║   ██╔══██╗██║   ██║            ║
║    ██║  ██║███████╗   ██║   ██║  ██║╚██████╔╝            ║
║    ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝             ║
║                                                          ║
║           🧠 J.A.R.V.I.S. CHAT — TOOL-WIRED              ║
║           {len(tools_schema)} tools active | Obsidian connected          ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝

Tastează /help pentru comenzi sau /tools pentru lista completă.

""")

        while True:
            try:
                user_input = input("👤 Tu: ").strip()
                if not user_input:
                    continue
                await self.stream_chat(user_input)
            except KeyboardInterrupt:
                print("\n👋 La revedere!")
                break


if __name__ == "__main__":
    chat = JarvisChat()
    asyncio.run(chat.start())
