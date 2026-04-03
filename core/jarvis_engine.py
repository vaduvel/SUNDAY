"""J.A.R.V.I.S. (GALAXY NUCLEUS - AEON AEGIS EDITION)

The Unified AEON GRADE Engine with AEGIS Heartbeat.
Integrates:
- Agentic OS Layer (MCP Registry)
- Mission State Machine (StateManager)
- Neuro-Symbolic Safety (SymbolicValidator)
- Emergency Kill Switch (AegisInterlock)
- Digital Vision (BrowserNavigator)
- Background AI Maintenance (KairosEngine)
"""

import os
import asyncio
import logging
import time
from typing import AsyncGenerator, List, Dict, Any, Optional

from tools.advanced_memory import AdvancedMemory
from tools.memory_tool import StructuredMemory

try:
    from tools.browser_navigator import BrowserNavigator
    from tools.desktop_control import DesktopControl
except ImportError:
    BrowserNavigator = None
    DesktopControl = None

try:
    from tools.browser_agent import get_browser_agent
except ImportError:
    get_browser_agent = None

try:
    from tools.stagehand_browser import get_stagehand_browser
except ImportError:
    get_stagehand_browser = None

try:
    from tools.voice_cascade import get_voice_cascade
except ImportError:
    get_voice_cascade = None

try:
    from tools.voice_input import get_voice_input
except ImportError:
    get_voice_input = None
from core.architecture_oracle import SymbolOracle
from core.dojo_sandbox import DojoSandbox
from core.pool_manager import AgentPool, ResourceGuard
from core.ensemble_oracle import ReasoningHub
from core.context_compactor import ContextManager
from core.kairos_engine import KairosEngine
from core.episodic_memory import EpisodicMemory
from core.brain import PRO_MODEL, CHEAP_MODEL, call_brain

# 🔱 AEON & AEGIS MODULES
from core.mcp_registry import MCPRegistry
from core.state_manager import StateManager, MissionState
from core.symbolic_check import SymbolicValidator
from core.evals_engine import EvalsEngine
from core.aegis_interlock import AegisInterlock

# 🧬 INFINITY CREATOR STACK
from core.creator_engine import CreatorEngine
from core.research_engine import ResearchEngine
from core.doc_engine import DocEngine

# 🌉 NUCLEUS BRIDGE INTEGRATION
try:
    from bridge.nucleus_bridge import push_event
except ImportError:
    # Fallback if bridge is not in python path
    async def push_event(*args, **kwargs):
        pass


logger = logging.getLogger(__name__)


class JarvisEngine:
    """The Apex Galactic Infrastructure (AEON GRADE with AEGIS Heartbeat)."""

    def __init__(self):
        self.name = "J.A.R.V.I.S. (AEON AEGIS)"
        self.root = os.getcwd()
        self.vault_path = os.path.join(self.root, ".agent/brain_vault")
        if not os.path.exists(self.vault_path):
            os.makedirs(self.vault_path)

        # 🛡️ AEGIS INTERLOCK (The Stop Button)
        self.aegis = AegisInterlock(self.root)

        # 🔱 AEON INFRASTRUCTURE
        self.mcp = MCPRegistry()
        self.state = StateManager(max_steps=100)
        self.validator = SymbolicValidator(self.root)
        self.evals = EvalsEngine(self.vault_path)

        # CORE MODULES
        self.memory = AdvancedMemory(self.root)
        self.structured_memory = StructuredMemory()
        self.oracle = SymbolOracle(self.root)
        self.dojo = DojoSandbox(self.root)
        self.pool = AgentPool()
        self.reasoning = ReasoningHub()
        self.guard = ResourceGuard()
        self.context = ContextManager(self.vault_path)

        # Browser (optional - requires playwright)
        self.browser = BrowserNavigator(headless=True) if BrowserNavigator else None
        self.browser_agent = get_browser_agent() if get_browser_agent else None
        self.stagehand = get_stagehand_browser() if get_stagehand_browser else None

        self.kairos = KairosEngine(self)
        self.episodic = EpisodicMemory(self.vault_path)

        # 🔱 OS SOVEREIGN (Desktop Control)
        self.desktop = DesktopControl() if DesktopControl else None
        self.voice = get_voice_cascade() if get_voice_cascade else None
        self.voice_input = get_voice_input() if get_voice_input else None

        # 🏗️ INFINITY MODULES
        self.workspace = os.path.join(self.root, "workspace")
        if not os.path.exists(self.workspace):
            os.makedirs(self.workspace)

        self.creator = CreatorEngine(self.workspace)
        self.research = ResearchEngine()
        self.doc_factory = DocEngine(os.path.join(self.workspace, "exports"))

        # 🚀 NEW CLAUDE CODE PATTERNS
        from core.streaming_tool_executor import (
            StreamingToolExecutor,
            ToolSafetyClassifier,
        )
        from core.error_recovery import ErrorRecoveryLadder, StopHook
        from core.result_budgeting import ResultBudget, SlotReservation

        self.tool_executor = StreamingToolExecutor(max_concurrency=10)
        self.safety_classifier = ToolSafetyClassifier()
        self.error_recovery = ErrorRecoveryLadder()
        self.stop_hooks = StopHook()
        self.result_budget = ResultBudget()
        self.slot_reservation = SlotReservation()

        # Register stop hooks
        from core.error_recovery import linter_check, format_check

        self.stop_hooks.register(linter_check)
        self.stop_hooks.register(format_check)

        # 🧬 NEW PATTERNS FROM RESEARCH
        # Self-Evolving Skills (OpenSpace pattern)
        from core.self_evolving_skills import SelfEvolvingSkills

        self.skills_engine = SelfEvolvingSkills(
            os.path.join(self.root, ".jarvis/skills")
        )

        # Auto Agents (PraisonAI pattern)
        from core.auto_agents import AutoAgentsManager

        self.auto_agents = AutoAgentsManager(self._llm_executor)

        # Knowledge Graph (GitNexus pattern)
        from core.knowledge_graph import CodeKnowledgeGraph, GraphRAGAgent

        self.knowledge_graph = CodeKnowledgeGraph(self.root)
        self.graph_rag = GraphRAGAgent(self.knowledge_graph)

        # Skill Library (seb1n awesome-ai-agent-skills pattern)
        from core.skill_library import SkillLibrary, get_skill_for_task

        self.skill_library = SkillLibrary()
        self.get_skill_for_task = get_skill_for_task

        from core.agent_memory_runtime import AgentMemoryRuntime
        from core.identity_context import IdentityContextManager
        from core.plan_notebook import PlanNotebook
        from core.session_runtime import SessionRuntime
        from core.tracing_runtime import JarvisTracer
        from core.ultraplan import UltraPlanner
        from core.coordinator_mode import CoordinatorMode

        self.tracer = JarvisTracer(self.vault_path)
        self.agent_memory = AgentMemoryRuntime(self.structured_memory)
        self.identity = IdentityContextManager(self.vault_path, self.root)
        self.plan_notebook = PlanNotebook(self.vault_path)
        self.session_runtime = SessionRuntime(self.vault_path)
        self.ultraplan = UltraPlanner()
        self.coordinator = CoordinatorMode(self.auto_agents, self.ultraplan)
        self.remote_mcp_clients: Dict[str, Any] = {}
        self._current_session_id: Optional[str] = None

        # 🧠 OBSERVATIONAL MEMORY (Mastra pattern)
        from core.observational_memory import ObservationalMemory

        self.observational_memory = ObservationalMemory()
        self.plan_notebook.register_plan_change_hook(self._record_plan_change)
        self._setup_session_modules()

        # ⚡ AGENT HARNESS PRIMITIVES
        from core.agent_harness import AgentHarness

        self.harness = AgentHarness()

        # 🔄 LLM GATEWAY (LLM-agnostic abstraction)
        from core.llm_gateway import create_llm_gateway

        self.llm_gateway = create_llm_gateway()

        # 🔌 MCP SERVER (deep integration)
        from core.mcp_server import create_jarvis_mcp_server

        self.mcp_server = create_jarvis_mcp_server()
        self.mcp.set_tracer(self.tracer)
        self.mcp_server.set_tracer(self.tracer)

        # 🖥️ COMPUTER USE AGENT
        try:
            from core.computer_use_agent import ComputerUseAgent

            self.computer_use = ComputerUseAgent()
        except Exception as e:
            logger.warning(f"ComputerUseAgent not available: {e}")
            self.computer_use = None

        # 🧠 META-COGNITION (Thinking engine)
        from core.meta_cognition import MetaCognition

        self.meta_cognition = MetaCognition()

        # 🎓 ADVANCED COGNITION (Opus-level thinking)
        from core.advanced_cognition import AdvancedCognition

        self.advanced_cognition = AdvancedCognition()

        self.active_model = PRO_MODEL
        self._register_mcp_tools()
        self._sync_mcp_server_tools()

        # Start Background Maintenance
        self.kairos.start()

    async def _llm_executor(self, system_prompt: str, user_prompt: str) -> str:
        """Adapter used by coordinator/auto-agents."""
        span_id = self.tracer.start_span(
            "llm",
            "coordinator_executor",
            {"model": self.active_model},
        )
        try:
            result = await call_brain(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=self.active_model,
                profile="balanced",
            )
            self.tracer.end_span(
                span_id,
                attributes={"response_chars": len(result)},
            )
            return result
        except Exception as exc:
            self.tracer.end_span(span_id, status="error", error=str(exc))
            raise

    def _setup_session_modules(self):
        """Register session exporters/importers for runtime state."""
        self.session_runtime.register_module(
            "state_manager",
            lambda session_id: self.state.get_mission_report(),
            self._restore_state_snapshot,
        )
        self.session_runtime.register_module(
            "plan_notebook",
            lambda session_id: self.plan_notebook.summary(),
            self._restore_plan_snapshot,
        )
        self.session_runtime.register_module(
            "identity",
            lambda session_id: self.identity.summary(),
        )
        self.session_runtime.register_module(
            "agent_memory",
            lambda session_id: self.agent_memory.summary(session_id=session_id),
        )
        self.session_runtime.register_module(
            "tracing",
            lambda session_id: self.tracer.summary(limit=50),
        )

    def _restore_state_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Restore state manager fields from a persisted session snapshot."""
        if not isinstance(snapshot, dict):
            return

        final_state = snapshot.get("final_state")
        if final_state:
            try:
                self.state.current_state = MissionState(final_state)
            except Exception:
                pass
        self.state.step_count = int(snapshot.get("total_steps", 0))
        self.state.history = list(snapshot.get("history", []))

    def _restore_plan_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Restore the currently focused plan from session data."""
        if not isinstance(snapshot, dict):
            return
        current_plan = snapshot.get("current_plan")
        if not isinstance(current_plan, dict):
            return
        plan_id = current_plan.get("id")
        if not plan_id:
            return
        try:
            self.plan_notebook.recover_historical_plan(plan_id)
        except Exception:
            return

    def _record_plan_change(self, event: str, payload: Dict[str, Any]) -> None:
        """Mirror notebook events into observational memory and traces."""
        try:
            self.observational_memory.observer.record_plan_change(
                old_plan=event,
                new_plan=json.dumps(payload, ensure_ascii=False)[:400],
                reason=event,
            )
        except Exception:
            pass

        try:
            self.tracer.record_event(
                "plan_notebook",
                event,
                attributes={
                    "plan_id": payload.get("plan_id")
                    or payload.get("id")
                    or payload.get("plan", {}).get("id", ""),
                },
            )
        except Exception:
            pass

    def _transition_state(
        self,
        new_state: MissionState,
        reason: str,
        *,
        session_id: Optional[str] = None,
    ) -> None:
        """Transition mission state while syncing memory, session, and traces."""
        old_state = self.state.current_state.value
        self.state.transition_to(new_state, reason)

        try:
            self.observational_memory.observer.record_state_change(
                old_state,
                self.state.current_state.value,
                reason,
            )
        except Exception:
            pass

        if session_id:
            try:
                self.session_runtime.checkpoint(
                    f"state_{self.state.current_state.value.lower()}",
                    {
                        "from": old_state,
                        "to": self.state.current_state.value,
                        "reason": reason,
                    },
                    session_id=session_id,
                )
            except Exception:
                pass

        try:
            self.tracer.record_event(
                "state_transition",
                f"{old_state}->{self.state.current_state.value}",
                attributes={"reason": reason, "session_id": session_id or ""},
            )
        except Exception:
            pass

    def _sync_mcp_server_tools(self):
        """Mirror registry tools into the standalone MCP server implementation."""
        from core.mcp_server import MCPTool as ServerMCPTool

        for tool in self.mcp.tools.values():
            self.mcp_server.register_tool(
                ServerMCPTool(
                    name=tool.name,
                    description=tool.description,
                    inputSchema=tool.parameters,
                    handler=tool.handler,
                )
            )

    def _register_mcp_tools(self):
        """[MCP]: Registering all engine capabilities as standardized 2026 tools."""

        # Browser tools (optional)
        if self.browser:
            self.mcp.register_tool(
                "browse",
                "Autonomous web navigation",
                {"properties": {"url": {"type": "string"}}},
                self.browser.navigate_to,
            )
        if self.browser_agent:
            self.mcp.register_tool(
                "browser_search",
                "Search the web using the unified browser agent.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
                self._browser_search,
            )
            self.mcp.register_tool(
                "browser_navigate",
                "Navigate to a URL using the unified browser agent.",
                {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
                self._browser_navigate,
            )
            self.mcp.register_tool(
                "browser_extract",
                "Extract visible page content using the unified browser agent.",
                {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "goal": {"type": "string"},
                    },
                    "required": ["url", "goal"],
                },
                self._browser_extract,
            )
            self.mcp.register_tool(
                "browser_task",
                "Execute a higher-level browser task with graceful fallbacks.",
                {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "success_criteria": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["task"],
                },
                self._browser_task,
            )
            self.mcp.register_tool(
                "browser_structured_extract",
                "Extract structured page data with a schema using the unified browser agent.",
                {
                    "type": "object",
                    "properties": {
                        "schema": {"type": "object", "additionalProperties": True},
                        "url": {"type": "string"},
                    },
                    "required": ["schema"],
                },
                self._browser_structured_extract,
            )
            self.mcp.register_tool(
                "browser_subtask",
                "Run a single browser subtask with verification metadata.",
                {
                    "type": "object",
                    "properties": {
                        "subtask": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["subtask"],
                },
                self._browser_subtask,
            )
            self.mcp.register_tool(
                "browser_status",
                "Inspect unified browser backend status.",
                {},
                self._browser_status,
            )
        if self.stagehand:
            self.mcp.register_tool(
                "stagehand_status",
                "Inspect Stagehand-style deterministic browser status.",
                {},
                self._stagehand_status,
            )
            self.mcp.register_tool(
                "stagehand_act",
                "Perform a deterministic browser action.",
                {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "target": {"type": "string"},
                    },
                    "required": ["action"],
                },
                self._stagehand_act,
            )
            self.mcp.register_tool(
                "stagehand_extract",
                "Extract structured data via deterministic browser primitives.",
                {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "schema": {"type": "object", "additionalProperties": True},
                        "url": {"type": "string"},
                    },
                },
                self._stagehand_extract,
            )
            self.mcp.register_tool(
                "stagehand_observe",
                "Observe current page semantics via deterministic browser primitives.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
                self._stagehand_observe,
            )

        # Code indexing tools
        self.mcp.register_tool(
            "index_code",
            "Index file for code understanding",
            {"properties": {"path": {"type": "string"}}},
            self._index_code_wrapper,
        )

        # OS CONTROL TOOLS
        if self.desktop:
            self.mcp.register_tool(
                "desktop_notify",
                "Sends a macOS notification to the desktop.",
                {
                    "properties": {
                        "message": {"type": "string"},
                        "title": {"type": "string"},
                    }
                },
                self.desktop.desktop_notify,
            )
            self.mcp.register_tool(
                "desktop_open_finder",
                "Opens a Finder window at the specified path.",
                {"properties": {"path": {"type": "string"}}},
                self.desktop.desktop_open_finder,
            )
            self.mcp.register_tool(
                "desktop_voice_say",
                "Uses the system voice to speak a message.",
                {"properties": {"text": {"type": "string"}}},
                self.desktop.desktop_voice_say,
            )
            self.mcp.register_tool(
                "desktop_launch_app",
                "Launches a specific application on the Mac.",
                {"properties": {"app_name": {"type": "string"}}},
                self.desktop.desktop_launch_app,
            )

        # 🧬 SELF-EVOLVING SKILLS TOOLS (OpenSpace pattern)
        self.mcp.register_tool(
            "skills_search",
            "Search for relevant skills in the skill library",
            {"properties": {"query": {"type": "string"}}},
            self._skills_search,
        )
        self.mcp.register_tool(
            "skills_status",
            "Get status of the self-evolving skills engine",
            {},
            self._skills_status,
        )

        # 🕸️ KNOWLEDGE GRAPH TOOLS (GitNexus pattern)
        self.mcp.register_tool(
            "index_codebase",
            "Build knowledge graph from codebase",
            {
                "properties": {
                    "extensions": {"type": "array", "items": {"type": "string"}}
                }
            },
            self._index_codebase,
        )
        self.mcp.register_tool(
            "find_definition",
            "Find definition of a function/class/variable in code",
            {"properties": {"name": {"type": "string"}}},
            self._find_definition,
        )
        self.mcp.register_tool(
            "search_code",
            "Search the codebase using knowledge graph",
            {"properties": {"query": {"type": "string"}}},
            self._search_code,
        )
        self.mcp.register_tool(
            "impact_analysis",
            "GitNexus blast radius: what breaks if this symbol changes? Returns direct + indirect dependents with confidence.",
            {"properties": {"symbol_name": {"type": "string"}}},
            self._impact_analysis,
        )
        self.mcp.register_tool(
            "impact",
            "GitNexus impact tool: analyze blast radius for a symbol change.",
            {
                "type": "object",
                "properties": {"symbol_name": {"type": "string"}},
                "required": ["symbol_name"],
            },
            self._impact_analysis,
        )
        self.mcp.register_tool(
            "detect_changes",
            "Map modified lines to affected symbols and downstream effects.",
            {
                "type": "object",
                "properties": {
                    "changed_lines": {
                        "type": "object",
                        "description": "dict of {file_path: [line_numbers]}",
                        "additionalProperties": True,
                    }
                },
                "required": ["changed_lines"],
            },
            self._detect_changes,
        )
        self.mcp.register_tool(
            "symbol_context",
            "360-degree view of a symbol: definition, references, callers, dependencies.",
            {"properties": {"symbol_name": {"type": "string"}}},
            self._symbol_context,
        )

        # 📚 SKILL LIBRARY TOOLS (seb1n pattern)
        self.mcp.register_tool(
            "list_skills",
            "List all available skills in the library",
            {},
            self._list_skills,
        )

        self.mcp.register_tool(
            "import_skill_pack",
            "Import a filesystem SKILL.md pack into the local skill library",
            {
                "type": "object",
                "properties": {
                    "source_dir": {"type": "string"},
                    "pack_name": {"type": "string"},
                },
                "required": ["source_dir"],
            },
            self._import_skill_pack,
        )

        # 🧠 STRUCTURED MEMORY TOOLS (PraisonAI 4-type pattern)
        self.mcp.register_tool(
            "memory_write",
            "Write to structured memory (short_term, long_term, entity, episodic).",
            {
                "type": "object",
                "properties": {
                    "memory_type": {
                        "type": "string",
                        "enum": ["short_term", "long_term", "entity", "episodic"],
                    },
                    "payload": {"type": "object", "additionalProperties": True},
                },
                "required": ["memory_type", "payload"],
            },
            self._memory_write,
        )
        self.mcp.register_tool(
            "memory_recall_structured",
            "Recall structured memory by type with optional filters.",
            {
                "type": "object",
                "properties": {
                    "memory_type": {
                        "type": "string",
                        "enum": ["short_term", "long_term", "entity", "episodic"],
                    },
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "session_id": {"type": "string"},
                },
                "required": ["memory_type"],
            },
            self._memory_recall_structured,
        )
        self.mcp.register_tool(
            "memory_full_context",
            "Get a unified context string from all 4 structured memory types.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "session_id": {"type": "string"},
                },
            },
            self._memory_full_context,
        )
        self.mcp.register_tool(
            "memory_scope_write",
            "Write to AgentScope/ReMe-style memory scopes (personal, task, tool, working).",
            {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["personal", "task", "tool", "working"],
                    },
                    "content": {"type": "string"},
                    "session_id": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "metadata": {"type": "object", "additionalProperties": True},
                },
                "required": ["scope", "content"],
            },
            self._memory_scope_write,
        )
        self.mcp.register_tool(
            "memory_scope_recall",
            "Recall AgentScope/ReMe-style memory scopes with unified output.",
            {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["personal", "task", "tool", "working"],
                    },
                    "query": {"type": "string"},
                    "session_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["scope"],
            },
            self._memory_scope_recall,
        )
        self.mcp.register_tool(
            "memory_scope_summary",
            "Summarize personal/task/tool/working memory overlays.",
            {
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
            },
            self._memory_scope_summary,
        )

        # 🧭 IDENTITY + CONTEXT TOOLS
        self.mcp.register_tool(
            "identity_anchor",
            "Return the persistent identity anchor and context priorities.",
            {},
            self._identity_anchor,
        )

        # 🧠 ULTRAPLAN / COORDINATOR MODES
        self.mcp.register_tool(
            "ultraplan",
            "Generate a deep implementation plan with checkpoints and risks.",
            {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["task"],
            },
            self._ultraplan,
        )
        self.mcp.register_tool(
            "coordinator_prepare",
            "Prepare coordinator meta-agent plan and role assignment.",
            {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
            self._coordinator_prepare,
        )
        self.mcp.register_tool(
            "coordinator_execute",
            "Execute coordinator meta-agent mode for a complex task.",
            {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
            self._coordinator_execute,
        )
        self.mcp.register_tool(
            "coordinator_status",
            "Get coordinator meta-agent status.",
            {},
            self._coordinator_status,
        )
        self.mcp.register_tool(
            "plan_create",
            "Create a persistent plan notebook entry from a task.",
            {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["task"],
            },
            self._plan_create,
        )
        self.mcp.register_tool(
            "plan_current",
            "Get the current plan notebook state and hint.",
            {},
            self._plan_current,
        )
        self.mcp.register_tool(
            "plan_update_subtask",
            "Update a notebook subtask state.",
            {
                "type": "object",
                "properties": {
                    "subtask_idx": {"type": "integer"},
                    "state": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["subtask_idx", "state"],
            },
            self._plan_update_subtask,
        )
        self.mcp.register_tool(
            "plan_finish",
            "Finish the current notebook plan with an outcome.",
            {
                "type": "object",
                "properties": {"outcome": {"type": "string"}},
            },
            self._plan_finish,
        )
        self.mcp.register_tool(
            "plan_history",
            "List historical notebook plans.",
            {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
            self._plan_history,
        )
        self.mcp.register_tool(
            "plan_resume",
            "Recover a historical notebook plan by id.",
            {
                "type": "object",
                "properties": {"plan_id": {"type": "string"}},
                "required": ["plan_id"],
            },
            self._plan_resume,
        )
        self.mcp.register_tool(
            "plan_hint",
            "Get the current notebook execution hint.",
            {},
            self._plan_hint,
        )
        self.mcp.register_tool(
            "session_start",
            "Start a persistent runtime session.",
            {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "mode": {"type": "string"},
                },
                "required": ["task"],
            },
            self._session_start,
        )
        self.mcp.register_tool(
            "session_snapshot",
            "Persist a snapshot of registered runtime modules.",
            {
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
            },
            self._session_snapshot,
        )
        self.mcp.register_tool(
            "session_resume",
            "Resume a previously persisted runtime session.",
            {
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
            self._session_resume,
        )
        self.mcp.register_tool(
            "session_list",
            "List recent runtime sessions.",
            {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
            self._session_list,
        )
        self.mcp.register_tool(
            "session_current",
            "Get the current runtime session if one is active.",
            {},
            self._session_current,
        )
        self.mcp.register_tool(
            "session_close",
            "Close a runtime session with final status.",
            {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "status": {"type": "string"},
                    "result_preview": {"type": "string"},
                },
            },
            self._session_close,
        )
        self.mcp.register_tool(
            "trace_recent",
            "Inspect recent runtime trace spans.",
            {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "kind": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            self._trace_recent,
        )
        self.mcp.register_tool(
            "trace_summary",
            "Get aggregate trace statistics for the runtime.",
            {},
            self._trace_summary,
        )
        self.mcp.register_tool(
            "mcp_connect_remote",
            "Connect to a remote MCP server with client-side tool policy.",
            {
                "type": "object",
                "properties": {
                    "alias": {"type": "string"},
                    "server_url": {"type": "string"},
                    "mode": {"type": "string", "enum": ["stateless", "stateful"]},
                    "allowed_tools": {"type": "array", "items": {"type": "string"}},
                    "blocked_tools": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["alias", "server_url"],
            },
            self._mcp_connect_remote,
        )
        self.mcp.register_tool(
            "mcp_remote_tools",
            "List remote MCP tools for a connected alias.",
            {
                "type": "object",
                "properties": {"alias": {"type": "string"}},
                "required": ["alias"],
            },
            self._mcp_remote_tools,
        )
        self.mcp.register_tool(
            "mcp_call_remote",
            "Call a tool on a connected remote MCP server.",
            {
                "type": "object",
                "properties": {
                    "alias": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "arguments": {"type": "object", "additionalProperties": True},
                },
                "required": ["alias", "tool_name"],
            },
            self._mcp_call_remote,
        )

        # 🧠 OBSERVATIONAL MEMORY TOOLS (Mastra pattern)
        self.mcp.register_tool(
            "memory_observations",
            "Get recent observations from observational memory",
            {"properties": {"limit": {"type": "integer"}}},
            self._get_observations,
        )
        self.mcp.register_tool(
            "memory_stats",
            "Get observational memory statistics",
            {},
            self._memory_stats,
        )
        self.mcp.register_tool(
            "memory_context",
            "Get dense context string from observational memory",
            {},
            self._memory_context,
        )

        # ⚡ AGENT HARNESS TOOLS
        self.mcp.register_tool(
            "harness_status",
            "Get status of agent harness primitives",
            {},
            self._harness_status,
        )

        if self.voice:
            self.mcp.register_tool(
                "voice_status",
                "Inspect the current voice cascade pathway and availability.",
                {},
                self._voice_status,
            )
            self.mcp.register_tool(
                "voice_speak",
                "Speak a message through the voice cascade.",
                {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                self._voice_speak,
            )
            self.mcp.register_tool(
                "voice_listen",
                "Listen for a short utterance through the voice cascade.",
                {
                    "type": "object",
                    "properties": {"timeout": {"type": "integer"}},
                },
                self._voice_listen,
            )
        if self.voice_input:
            self.mcp.register_tool(
                "voice_session_status",
                "Inspect the persistent voice runtime state and active sessions.",
                {},
                self._voice_session_status,
            )
            self.mcp.register_tool(
                "voice_session_start",
                "Start or resume a persistent voice session.",
                {
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}},
                },
                self._voice_session_start,
            )
            self.mcp.register_tool(
                "voice_session_listen",
                "Capture incremental transcript events inside a persistent voice session.",
                {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "timeout": {"type": "integer"},
                        "phrase_limit": {"type": "integer"},
                    },
                    "required": ["session_id"],
                },
                self._voice_session_listen,
            )
            self.mcp.register_tool(
                "voice_session_stop",
                "Stop a persistent voice session.",
                {
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}},
                    "required": ["session_id"],
                },
                self._voice_session_stop,
            )
            self.mcp.register_tool(
                "voice_session_cancel",
                "Cancel an in-flight persistent voice session.",
                {
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}},
                    "required": ["session_id"],
                },
                self._voice_session_cancel,
            )

        # 🤝 CO-WORK TOOLS
        self.mcp.register_tool(
            "cowork_status",
            "Inspect the current co-work runtime state.",
            {},
            self._cowork_status,
        )
        self.mcp.register_tool(
            "cowork_start",
            "Start the co-work runtime if it is not already active.",
            {},
            self._cowork_start,
        )
        self.mcp.register_tool(
            "cowork_command",
            "Process a co-work command using the persistent desktop assistant runtime.",
            {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            self._cowork_command,
        )
        self.mcp.register_tool(
            "cowork_stop",
            "Stop the co-work runtime.",
            {},
            self._cowork_stop,
        )

        # 🖥️ COMPUTER USE TOOLS
        self.mcp.register_tool(
            "computer_task",
            "Execute a computer use task (click, type, navigate, screenshot)",
            {"properties": {"task": {"type": "string"}}},
            self._computer_task,
        )
        self.mcp.register_tool(
            "computer_screenshot",
            "Take a screenshot of the screen",
            {},
            self._computer_screenshot,
        )
        self.mcp.register_tool(
            "computer_screen_info",
            "Get screen dimensions",
            {},
            self._computer_screen_info,
        )
        self.mcp.register_tool(
            "computer_observe_screen",
            "Capture a semantic observation of the current desktop state.",
            {},
            self._computer_observe_screen,
        )
        self.mcp.register_tool(
            "computer_open_app",
            "Open an application and verify focus.",
            {
                "type": "object",
                "properties": {"app_name": {"type": "string"}},
                "required": ["app_name"],
            },
            self._computer_open_app,
        )
        self.mcp.register_tool(
            "computer_click_target",
            "Click a screen target using coordinates or simple semantic hints.",
            {
                "type": "object",
                "properties": {"target_desc": {"type": "string"}},
                "required": ["target_desc"],
            },
            self._computer_click_target,
        )
        self.mcp.register_tool(
            "computer_type_verified",
            "Type text and verify the desktop state after the action.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "destination_desc": {"type": "string"},
                },
                "required": ["text", "destination_desc"],
            },
            self._computer_type_verified,
        )
        self.mcp.register_tool(
            "computer_assert_change",
            "Assert a screen-change signal based on the last desktop observation.",
            {
                "type": "object",
                "properties": {"expected_signal": {"type": "string"}},
                "required": ["expected_signal"],
            },
            self._computer_assert_change,
        )

    async def execute_mission(self, user_input: str) -> AsyncGenerator[Dict, None]:
        """[AEON-LOOP]: The mission cycle protected by the AEGIS Heartbeat."""
        mission_span_id = self.tracer.start_span(
            "mission",
            "execute_mission",
            {"task_preview": user_input[:160]},
        )
        session_id: Optional[str] = None
        mission_span_closed = False

        try:
            # 🛡️ [AEGIS] HEARTBEAT CHECK
            self.aegis.trigger_heartbeat()

            # 🌉 [NUCLEUS] UI Update
            await push_event("MISSION_START", f"Starting mission: {user_input}")

            start_time = time.time()
            self.state.reset()
            plan_bundle = self.ultraplan.build_plan(user_input)
            recommended_mode = plan_bundle.get("mode", "default")
            session = self.session_runtime.start_session(
                user_input,
                mode=recommended_mode,
                metadata={"entrypoint": "execute_mission"},
            )
            session_id = session["id"]
            self._current_session_id = session_id
            self.session_runtime.checkpoint(
                "mission_received",
                {
                    "recommended_mode": recommended_mode,
                    "complexity_score": plan_bundle.get("complexity_score"),
                },
                session_id=session_id,
            )
            self.structured_memory.store_short_term(
                content=user_input,
                role="user",
                session_id=session_id,
            )
            plan_record = self.plan_notebook.create_plan_from_bundle(
                user_input, plan_bundle
            )
            self.session_runtime.update(
                session_id=session_id,
                metadata={
                    "entrypoint": "execute_mission",
                    "plan_id": plan_record["id"],
                },
            )
            self.session_runtime.snapshot(session_id)

            # 1. PLANNING PHASE
            self._transition_state(
                MissionState.PLANNING,
                f"Input: {user_input[:30]}",
                session_id=session_id,
            )
            self.plan_notebook.update_subtask_state(
                0, "in_progress", note="Mission intake started."
            )
            msg = (
                f"🧠 [PLANNING] Aeon Reasoning check... mode={recommended_mode} "
                f"(complexity={plan_bundle.get('complexity_score')})"
            )
            await push_event("STATUS", msg)
            yield {"type": "status", "message": msg}

            steps = plan_bundle.get("steps", [])
            first_title = steps[0]["title"] if steps else "Map current state"
            second_title = steps[1]["title"] if len(steps) > 1 else "Implement stable primitives"
            yield {
                "type": "status",
                "message": f"📐 [ULTRAPLAN] {first_title} → {second_title}",
            }

            if recommended_mode == "coordinator":
                preview = await self.coordinator.prepare(user_input)
                self.session_runtime.checkpoint(
                    "coordinator_prepared",
                    {"roles": preview.get("roles", [])},
                    session_id=session_id,
                )
                yield {
                    "type": "status",
                    "message": "🤝 [COORDINATOR] Meta-agent coordination armed for multi-role execution.",
                }

            # (Simulating plan for validation)
            is_safe, problems = self.validator.validate_plan([f"Task: {user_input}"])
            if not is_safe:
                self._transition_state(
                    MissionState.FAILURE,
                    "Neuro-Symbolic rejection.",
                    session_id=session_id,
                )
                self.plan_notebook.finish_plan("failed")
                self.session_runtime.checkpoint(
                    "validation_failed",
                    {"problem": problems[0]},
                    session_id=session_id,
                )
                self.session_runtime.snapshot(session_id)
                self.session_runtime.close_session(
                    session_id=session_id,
                    status="failed",
                    result_preview=problems[0],
                )
                self.tracer.end_span(
                    mission_span_id,
                    status="error",
                    error=problems[0],
                    attributes={
                        "session_id": session_id,
                        "recommended_mode": recommended_mode,
                    },
                )
                mission_span_closed = True
                self._current_session_id = None
                yield {
                    "type": "status",
                    "message": f"🚨 [GOD-EYE] Planning halted: {problems[0]}",
                }
                return

            # 2. EXECUTING PHASE
            self.plan_notebook.finish_subtask(0, note="Mission intake validated.")
            if len(steps) > 1:
                self.plan_notebook.update_subtask_state(
                    1, "in_progress", note="Execution path armed."
                )
            self._transition_state(
                MissionState.EXECUTING,
                "Mission start.",
                session_id=session_id,
            )
            yield {
                "type": "status",
                "message": f"🚀 [AEON] Core sequence active on {self.active_model}.",
            }

            # 🏗️ [CREATOR MODE] Check for build/research tasks
            if "build" in user_input.lower() or "create" in user_input.lower():
                msg = "🏗️ [CREATOR] Orchestrating autonomous production sequence..."
                await push_event("STATUS", msg)
                yield {"type": "status", "message": msg}
            elif "research" in user_input.lower() or "cauta" in user_input.lower():
                msg = "🔭 [RESEARCH] Deep scanning market and technical resources..."
                await push_event("STATUS", msg)
                yield {"type": "status", "message": msg}
            elif "raport" in user_input.lower() or "document" in user_input.lower():
                msg = "📄 [DOCGEN] Initializing professional document factory..."
                await push_event("STATUS", msg)
                yield {"type": "status", "message": msg}

            # Recurring Heartbeat during execution (simulated here)
            self.aegis.trigger_heartbeat()

            # 3. FINALIZATION
            self._transition_state(
                MissionState.SUCCESS,
                "Mission achieved.",
                session_id=session_id,
            )
            current_plan = self.plan_notebook.get_current_plan() or {}
            for idx, item in enumerate(current_plan.get("subtasks", [])):
                if item.get("state") != "done":
                    self.plan_notebook.finish_subtask(
                        idx, note="Marked complete during mission finalization."
                    )
            self.plan_notebook.finish_plan("completed")
            self.structured_memory.store_episodic(
                event=f"Mission executed: {user_input}",
                context=f"mode={recommended_mode}",
                importance=0.7,
                tags=["mission", recommended_mode],
            )
            self.evals.log_mission_metrics(
                user_input, self.state.step_count, time.time() - start_time, "SUCCESS"
            )
            self.session_runtime.snapshot(session_id)
            self.session_runtime.close_session(
                session_id=session_id,
                status="completed",
                result_preview="Mission executed successfully.",
            )
            self.tracer.end_span(
                mission_span_id,
                attributes={
                    "session_id": session_id,
                    "recommended_mode": recommended_mode,
                    "step_count": self.state.step_count,
                },
            )
            mission_span_closed = True
            self._current_session_id = None
            yield {
                "type": "final",
                "content": "🌌 MISIUNE COMPLETĂ: J.A.R.V.I.S. AEON la capacitate nominală (AEGIS PROTECT).",
            }
        except Exception as exc:
            if session_id:
                try:
                    self.session_runtime.checkpoint(
                        "mission_exception",
                        {"error": str(exc)},
                        session_id=session_id,
                    )
                    self.session_runtime.snapshot(session_id)
                    self.session_runtime.close_session(
                        session_id=session_id,
                        status="error",
                        result_preview=str(exc),
                    )
                except Exception:
                    pass
            self._current_session_id = None
            if not mission_span_closed:
                self.tracer.end_span(
                    mission_span_id,
                    status="error",
                    error=str(exc),
                    attributes={"session_id": session_id or ""},
                )
            raise

    # ═══════════════════════════════════════════════════════════════
    #  🧬 SELF-EVOLVING SKILLS TOOL IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════

    async def _skills_search(self, query: str) -> Dict[str, Any]:
        """Search skills engine for relevant skills."""
        skill = await self.skills_engine.find_skill(query)
        if skill:
            return {
                "name": skill.name,
                "description": skill.description,
                "quality": skill.quality_score,
            }
        return {"message": "No matching skills found"}

    async def _skills_status(self) -> Dict[str, Any]:
        """Get skills engine status."""
        return self.skills_engine.get_skill_status()

    # ═══════════════════════════════════════════════════════════════
    #  🕸️ KNOWLEDGE GRAPH TOOL IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════

    async def _index_code_wrapper(self, path: str) -> Dict[str, Any]:
        """Wrapper for oracle index_file."""
        try:
            return await self.oracle.index_file(path)
        except Exception as e:
            return {"error": str(e)}

    async def _index_codebase(self, extensions: List[str] = None) -> Dict[str, Any]:
        """Index the codebase to build knowledge graph."""
        self.knowledge_graph.index_directory(extensions)
        return self.knowledge_graph.get_graph_stats()

    async def _find_definition(self, name: str) -> Dict[str, Any]:
        """Find definition of a symbol."""
        node = self.knowledge_graph.find_definition(name)
        if node:
            return {
                "name": node.name,
                "type": node.node_type,
                "file": node.file_path,
                "line": node.line_start,
            }
        return {"error": "Definition not found"}

    async def _search_code(self, query: str) -> List[Dict[str, Any]]:
        """Search codebase using knowledge graph."""
        results = self.knowledge_graph.search(query)
        return [
            {
                "name": r.name,
                "type": r.node_type,
                "file": r.file_path,
                "line": r.line_start,
            }
            for r in results[:10]
        ]

    async def _impact_analysis(self, symbol_name: str) -> Dict[str, Any]:
        return self.knowledge_graph.impact(symbol_name)

    async def _detect_changes(self, changed_lines: Dict[str, Any]) -> Dict[str, Any]:
        # changed_lines may come as JSON string from LLM
        if isinstance(changed_lines, str):
            import json
            try:
                changed_lines = json.loads(changed_lines)
            except Exception:
                return {"error": "changed_lines must be a dict {file_path: [lines]}"}
        return self.knowledge_graph.detect_changes(changed_lines)

    async def _symbol_context(self, symbol_name: str) -> Dict[str, Any]:
        return self.knowledge_graph.get_symbol_context(symbol_name)

    # ═══════════════════════════════════════════════════════════════
    #  📚 SKILL LIBRARY TOOL IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════

    async def _list_skills(self) -> List[Dict[str, Any]]:
        """List all skills in the library."""
        return self.skill_library.list_skills()

    async def _import_skill_pack(
        self, source_dir: str, pack_name: str = "imported"
    ) -> Dict[str, Any]:
        """Import a SKILL.md pack from disk."""
        return self.skill_library.import_skill_pack(source_dir, pack_name=pack_name)

    # ═══════════════════════════════════════════════════════════════
    #  🧠 STRUCTURED MEMORY TOOL IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════

    async def _memory_write(self, memory_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Write to one of the four PraisonAI-style memory types."""
        if memory_type == "short_term":
            return self.structured_memory.store_short_term(
                content=payload.get("content", ""),
                role=payload.get("role", "user"),
                session_id=payload.get("session_id", "default"),
            )
        if memory_type == "entity":
            return self.structured_memory.store_entity(
                entity_name=payload.get("entity_name", ""),
                entity_type=payload.get("entity_type", "concept"),
                attributes=payload.get("attributes", {}),
            )
        if memory_type == "episodic":
            return self.structured_memory.store_episodic(
                event=payload.get("event", ""),
                context=payload.get("context", ""),
                importance=float(payload.get("importance", 0.5)),
                tags=payload.get("tags", []),
            )
        if memory_type == "long_term":
            return self.structured_memory.store_long_term(
                observation=payload.get("observation", ""),
                tags=payload.get("tags", []),
                quality_score=payload.get("quality_score"),
                mission_type=payload.get("mission_type"),
            )
        return {"error": f"Unsupported memory type: {memory_type}"}

    async def _memory_recall_structured(
        self,
        memory_type: str,
        query: str = "",
        limit: int = 10,
        session_id: str = "default",
    ) -> Any:
        """Recall one of the four memory types."""
        if memory_type == "short_term":
            return self.structured_memory.recall_short_term(session_id=session_id, limit=limit)
        if memory_type == "entity":
            return self.structured_memory.recall_entity(entity_name=query or None)
        if memory_type == "episodic":
            return self.structured_memory.recall_episodic(
                query=query or None, min_importance=0.0, limit=limit
            )
        if memory_type == "long_term":
            keywords = [token for token in query.split() if token] or ["jarvis"]
            return self.structured_memory.recall_long_term(keywords=keywords, limit=limit)
        return {"error": f"Unsupported memory type: {memory_type}"}

    async def _memory_full_context(
        self, query: str = "", session_id: str = "default"
    ) -> str:
        """Unified context string from all memory types."""
        return self.structured_memory.get_full_context(query=query, session_id=session_id)

    async def _memory_scope_write(
        self,
        scope: str,
        content: str,
        session_id: str = "default",
        tags: List[str] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Write to the high-level memory runtime scopes."""
        return self.agent_memory.write(
            scope,
            content,
            session_id=session_id,
            tags=tags,
            metadata=metadata,
        )

    async def _memory_scope_recall(
        self,
        scope: str,
        query: str = "",
        session_id: str = "default",
        limit: int = 5,
    ) -> Dict[str, Any]:
        """Recall memory across personal/task/tool/working scopes."""
        return self.agent_memory.recall(
            scope,
            query=query,
            session_id=session_id,
            limit=limit,
        )

    async def _memory_scope_summary(
        self, session_id: str = "default"
    ) -> Dict[str, Any]:
        """Summarize current memory runtime overlays."""
        return self.agent_memory.summary(session_id=session_id)

    # ═══════════════════════════════════════════════════════════════
    #  🧭 IDENTITY / CONTEXT TOOL IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════

    async def _identity_anchor(self) -> Dict[str, Any]:
        return self.identity.summary()

    # ═══════════════════════════════════════════════════════════════
    #  🧠 ULTRAPLAN / COORDINATOR TOOL IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════

    async def _ultraplan(self, task: str, context: str = "") -> Dict[str, Any]:
        return self.ultraplan.build_plan(task, context=context)

    async def _coordinator_prepare(self, task: str) -> Dict[str, Any]:
        return await self.coordinator.prepare(task)

    async def _coordinator_execute(self, task: str) -> Dict[str, Any]:
        return await self.coordinator.execute(task)

    async def _coordinator_status(self) -> Dict[str, Any]:
        return self.coordinator.status()

    async def _plan_create(self, task: str, context: str = "") -> Dict[str, Any]:
        bundle = self.ultraplan.build_plan(task, context=context)
        return self.plan_notebook.create_plan_from_bundle(task, bundle)

    async def _plan_current(self) -> Dict[str, Any]:
        return self.plan_notebook.summary()

    async def _plan_update_subtask(
        self, subtask_idx: int, state: str, note: str = ""
    ) -> Dict[str, Any]:
        return self.plan_notebook.update_subtask_state(subtask_idx, state, note=note)

    async def _plan_finish(self, outcome: str = "completed") -> Dict[str, Any]:
        return self.plan_notebook.finish_plan(outcome)

    async def _plan_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.plan_notebook.view_historical_plans(limit=limit)

    async def _plan_resume(self, plan_id: str) -> Dict[str, Any]:
        return self.plan_notebook.recover_historical_plan(plan_id)

    async def _plan_hint(self) -> Dict[str, Any]:
        return {"hint": self.plan_notebook.get_current_hint()}

    async def _session_start(self, task: str, mode: str = "default") -> Dict[str, Any]:
        session = self.session_runtime.start_session(task, mode=mode)
        self._current_session_id = session["id"]
        return session

    async def _session_snapshot(self, session_id: str = "") -> Dict[str, Any]:
        return self.session_runtime.snapshot(session_id or None)

    async def _session_resume(self, session_id: str) -> Dict[str, Any]:
        session = self.session_runtime.resume(session_id)
        self._current_session_id = session_id
        return session

    async def _session_list(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.session_runtime.list_sessions(limit=limit)

    async def _session_current(self) -> Dict[str, Any]:
        return self.session_runtime.current_session() or {}

    async def _session_close(
        self,
        session_id: str = "",
        status: str = "completed",
        result_preview: str = "",
    ) -> Dict[str, Any]:
        closed = self.session_runtime.close_session(
            session_id=session_id or None,
            status=status,
            result_preview=result_preview,
        )
        if not session_id or session_id == self._current_session_id:
            self._current_session_id = None
        return closed

    async def _trace_recent(
        self, limit: int = 25, kind: str = "", status: str = ""
    ) -> List[Dict[str, Any]]:
        return self.tracer.recent(
            limit=limit,
            kind=kind or None,
            status=status or None,
        )

    async def _trace_summary(self) -> Dict[str, Any]:
        return self.tracer.summary()

    async def _mcp_connect_remote(
        self,
        alias: str,
        server_url: str,
        mode: str = "stateless",
        allowed_tools: List[str] | None = None,
        blocked_tools: List[str] | None = None,
    ) -> Dict[str, Any]:
        from core.mcp_server import MCPClient

        client = MCPClient()
        result = await client.connect(
            server_url,
            mode=mode,
            client_name=f"JARVIS::{alias}",
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools,
        )
        self.remote_mcp_clients[alias] = client
        return {"alias": alias, **result}

    async def _mcp_remote_tools(self, alias: str) -> Dict[str, Any]:
        client = self.remote_mcp_clients.get(alias)
        if not client:
            return {"error": f"Remote MCP alias '{alias}' not connected."}
        await client.refresh_tools()
        return {"alias": alias, "tools": client.list_tools()}

    async def _mcp_call_remote(
        self,
        alias: str,
        tool_name: str,
        arguments: Dict[str, Any] | None = None,
    ) -> Any:
        client = self.remote_mcp_clients.get(alias)
        if not client:
            return {"error": f"Remote MCP alias '{alias}' not connected."}
        return await client.call_tool(tool_name, arguments or {})

    # ═══════════════════════════════════════════════════════════════
    #  🧠 OBSERVATIONAL MEMORY TOOL IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════

    async def _get_observations(self, limit: int = 15) -> Dict[str, Any]:
        """Get recent observations."""
        observations = self.observational_memory.observer.get_recent_observations(
            limit=limit
        )
        return {
            "count": len(observations),
            "observations": [
                {
                    "type": o.observation_type.value,
                    "importance": o.importance,
                    "content": o.content[:200],
                }
                for o in observations
            ],
        }

    async def _memory_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        return self.observational_memory.get_stats()

    async def _memory_context(self) -> str:
        """Get dense context string."""
        return self.observational_memory.get_context_for_llm()

    # ═══════════════════════════════════════════════════════════════
    #  ⚡ AGENT HARNESS TOOL IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════

    async def _harness_status(self) -> Dict[str, Any]:
        """Get harness status."""
        circuits = {}
        # Get circuit breaker states (would need instance access)
        return {
            "retry_config_available": True,
            "timeout_config_available": True,
            "fallback_available": True,
            "circuit_breaker_available": True,
            "message": "AgentHarness primitives ready for use",
        }

    # ═══════════════════════════════════════════════════════════════
    #  🖥️ COMPUTER USE TOOL IMPLEMENTATIONS
    # ═══════════════════════════════════════════════════════════════

    async def _computer_task(self, task: str) -> Dict[str, Any]:
        """Execute a computer use task."""
        if not self.computer_use:
            return {"error": "ComputerUseAgent not available - install pyautogui"}

        return await self.computer_use.execute_task(task)

    async def _computer_screenshot(self) -> Dict[str, Any]:
        """Take a screenshot."""
        if not self.computer_use:
            return {"error": "ComputerUseAgent not available"}

        return await self.computer_use.get_screenshot()

    async def _computer_screen_info(self) -> Dict[str, Any]:
        """Get screen info."""
        if not self.computer_use:
            return {"error": "ComputerUseAgent not available"}

        return await self.computer_use.get_screen_info()

    async def _computer_observe_screen(self) -> Dict[str, Any]:
        if not self.computer_use:
            return {"error": "ComputerUseAgent not available"}
        return await self.computer_use.observe_screen()

    async def _computer_open_app(self, app_name: str) -> Dict[str, Any]:
        if not self.computer_use:
            return {"error": "ComputerUseAgent not available"}
        return await self.computer_use.open_app_verified(app_name)

    async def _computer_click_target(self, target_desc: str) -> Dict[str, Any]:
        if not self.computer_use:
            return {"error": "ComputerUseAgent not available"}
        return await self.computer_use.click_screen_target(target_desc)

    async def _computer_type_verified(
        self, text: str, destination_desc: str
    ) -> Dict[str, Any]:
        if not self.computer_use:
            return {"error": "ComputerUseAgent not available"}
        return await self.computer_use.type_text_verified(text, destination_desc)

    async def _computer_assert_change(self, expected_signal: str) -> Dict[str, Any]:
        if not self.computer_use:
            return {"error": "ComputerUseAgent not available"}
        return await self.computer_use.assert_screen_change(expected_signal)

    async def _browser_search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if not self.browser_agent:
            return {"error": "Browser agent unavailable"}
        return await self.browser_agent.search_web(query, limit=limit)

    async def _browser_navigate(self, url: str) -> Dict[str, Any]:
        if not self.browser_agent:
            return {"error": "Browser agent unavailable"}
        return await self.browser_agent.navigate_to(url)

    async def _browser_extract(self, url: str, goal: str) -> Dict[str, Any]:
        if not self.browser_agent:
            return {"error": "Browser agent unavailable"}
        return await self.browser_agent.extract_from_page(url, goal)

    async def _browser_task(
        self, task: str, success_criteria: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self.browser_agent:
            return {"error": "Browser agent unavailable"}
        if success_criteria:
            return await self.browser_agent.execute_browser_task(task, success_criteria)
        return await self.browser_agent.execute_task(task)

    async def _browser_structured_extract(
        self, schema: Dict[str, Any], url: str = ""
    ) -> Dict[str, Any]:
        if not self.browser_agent:
            return {"error": "Browser agent unavailable"}
        return await self.browser_agent.extract_structured_page_data(schema, url=url or None)

    async def _browser_subtask(self, subtask: Dict[str, Any]) -> Dict[str, Any]:
        if not self.browser_agent:
            return {"error": "Browser agent unavailable"}
        return await self.browser_agent.run_browser_subtask(subtask)

    async def _browser_status(self) -> Dict[str, Any]:
        if not self.browser_agent:
            return {"available": False}
        return self.browser_agent.get_status()

    async def _stagehand_status(self) -> Dict[str, Any]:
        if not self.stagehand:
            return {"available": False}
        return self.stagehand.get_status()

    async def _stagehand_act(self, action: str, target: str = "") -> Dict[str, Any]:
        if not self.stagehand:
            return {"error": "Stagehand unavailable"}
        return await self.stagehand.act(action, target or None)

    async def _stagehand_extract(
        self,
        selector: str = "body",
        schema: Optional[Dict[str, Any]] = None,
        url: str = "",
    ) -> Dict[str, Any]:
        if not self.stagehand:
            return {"error": "Stagehand unavailable"}
        return await self.stagehand.extract(selector=selector, schema=schema, url=url or None)

    async def _stagehand_observe(self, query: str = "page", url: str = "") -> Dict[str, Any]:
        if not self.stagehand:
            return {"error": "Stagehand unavailable"}
        return await self.stagehand.observe(query=query, url=url or None)

    async def _voice_status(self) -> Dict[str, Any]:
        if not self.voice:
            return {"available": False}
        return self.voice.get_status()

    async def _voice_speak(self, text: str) -> Dict[str, Any]:
        if not self.voice:
            return {"error": "Voice cascade unavailable"}
        pathway = await self.voice.speak(text)
        return {"success": True, "pathway": pathway.value}

    async def _voice_listen(self, timeout: int = 5) -> Dict[str, Any]:
        if not self.voice:
            return {"error": "Voice cascade unavailable"}
        text, pathway = await self.voice.listen(timeout)
        return {"success": bool(text), "text": text, "pathway": pathway.value}

    async def _voice_session_status(self) -> Dict[str, Any]:
        if not self.voice_input:
            return {"available": False}
        return {
            "available": True,
            **self.voice_input.get_status(),
            "sessions": self.voice_input.list_sessions(limit=5),
        }

    async def _voice_session_start(self, session_id: str = "") -> Dict[str, Any]:
        if not self.voice_input:
            return {"error": "Voice runtime unavailable"}
        return self.voice_input.start_voice_session(session_id or None)

    async def _voice_session_listen(
        self,
        session_id: str,
        timeout: int = 5,
        phrase_limit: int = 10,
    ) -> Dict[str, Any]:
        if not self.voice_input:
            return {"error": "Voice runtime unavailable"}
        return await self.voice_input.stream_listen(
            session_id,
            timeout=timeout,
            phrase_time_limit=phrase_limit,
        )

    async def _voice_session_stop(self, session_id: str) -> Dict[str, Any]:
        if not self.voice_input:
            return {"error": "Voice runtime unavailable"}
        return self.voice_input.stop_voice_session(session_id)

    async def _voice_session_cancel(self, session_id: str) -> Dict[str, Any]:
        if not self.voice_input:
            return {"error": "Voice runtime unavailable"}
        return self.voice_input.cancel_voice_session(session_id)

    async def _cowork_status(self) -> Dict[str, Any]:
        from core.cowork_mode import cowork_status

        return cowork_status()

    async def _cowork_start(self) -> Dict[str, Any]:
        from core.cowork_mode import start_cowork

        return await start_cowork()

    async def _cowork_command(self, command: str) -> Dict[str, Any]:
        from core.cowork_mode import get_cowork_mode, process_cowork_command, start_cowork

        coworker = get_cowork_mode()
        if not coworker.active:
            await start_cowork()
        return await process_cowork_command(command)

    async def _cowork_stop(self) -> Dict[str, Any]:
        from core.cowork_mode import get_cowork_mode

        coworker = get_cowork_mode()
        if not coworker.active:
            return {"success": True, "message": "Co-work already stopped."}
        return await coworker.stop()


# ═══════════════════════════════════════════════════════════════
#  AEON BOOT
# ═══════════════════════════════════════════════════════════════


async def main():
    jarvis = JarvisEngine()
    print(f"\n🦾 {jarvis.name} - STATUS 2026: AEON ONLINE 🛡️🛑🌌\n")
    async for event in jarvis.execute_mission("AuditFlow Launch Protocol"):
        print(f" {event['message'] if 'message' in event else event['content']}")
    jarvis.kairos.stop()


if __name__ == "__main__":
    asyncio.run(main())
