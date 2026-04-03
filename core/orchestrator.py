"""Intelligent CrewAI orchestrator with dynamic routing and auto-learning.

Architecture:
  Mission → CLASSIFY → MEMORY → RESEARCH → EXECUTE → QA → Result
                                                        ↓
                                                   RETRY if score < 6/10

Features:
- Mission classifier (business, code, research, design, general)
- Dynamic agent selection (only activates relevant agents)
- 5-phase pipeline with quality gate
- Auto-learning from every mission
- Anti-repetition guard from past failures
"""

from __future__ import annotations

import os
import json
import re
import subprocess
import logging
import asyncio
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import AsyncGenerator, Any

from core.runtime_config import (
    configure_inception_openai_alias,
    load_project_env,
    resolve_obsidian_vault_path,
)
from core.definition_of_done import DefinitionOfDoneEvaluator
from core.mission_metrics import MetricsCollector
from core.neuro_maintenance import NeuroMaintenanceJournal
from core.context_graph import get_context_graph
from core.episodic_memory import EpisodicMemory
from core.memory_consolidation import get_memory_consolidation
from core.state_manager import MissionState, StateManager
from core.task_contracts import (
    ExecutionResult,
    FailureCode,
    PlanStep,
    SuccessCriteria,
    TaskContract,
    TaskRisk,
    TaskStatus,
    contract_to_dict,
    create_mission,
    normalize_tool_response,
)

load_project_env()
configure_inception_openai_alias()
_definition_of_done = DefinitionOfDoneEvaluator()

try:
    from crewai import Agent, Crew, Process, Task
    from crewai.tools import tool

    CREWAI_AVAILABLE = True
    CREWAI_IMPORT_ERROR = None
except Exception as exc:
    Agent = Crew = Task = None
    Process = None
    CREWAI_AVAILABLE = False
    CREWAI_IMPORT_ERROR = exc

    def tool(_name: str):
        """Fallback decorator so the module stays importable without CrewAI."""

        def decorator(func):
            return func

        return decorator

from core.brain import get_llm_for_role, call_brain, PRO_MODEL, CHEAP_MODEL
from core.jarvis_engine import JarvisEngine
from core.ensemble_oracle import EnsembleOracle, ReasoningHub
from core.architecture_oracle import SymbolOracle
from core.context_compactor import ContextManager
from tools.file_manager import read_text_file, write_text_file
from tools.memory_tool import (
    load_memory,
    save_to_memory,
    save_lesson,
    get_memory_summary,
    get_relevant_lessons,
    get_anti_repetition_guard,
    search_memory,
)
from tools.search_tool import duckduckgo_search

# ── Neuro Brain import (graceful fallback if not installed) ──────
try:
    from core.neuro import get_neuro_brain, NeuroBrain
    from core.neuro.routing_adaptation import classify_context
    from core.neuro.async_trigger_graph import (
        MISSION_COMPLETE, ANOMALY_DETECTED, ERROR_BURST
    )
    _NEURO_AVAILABLE = True
except Exception:
    _NEURO_AVAILABLE = False

# ── V3 components (graceful fallback) ────────────────────────────
try:
    from core.event_log import get_event_log, E
    from core.improvement_proposals import (
        get_proposals, TargetType as _PT, RiskLevel as _RL
    )
    _V3_AVAILABLE = True
except Exception:
    _V3_AVAILABLE = False

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  GLOBAL INSTANCES (Singleton Pattern)
# ═══════════════════════════════════════════════════════════════

_jarvis_engine: JarvisEngine = None
_symbol_oracle: SymbolOracle = None
_ensemble_oracle: EnsembleOracle = None
_reasoning_hub: ReasoningHub = None
_context_manager: ContextManager = None


def _episodic_memory() -> EpisodicMemory:
    vault = os.path.join(os.getcwd(), ".agent", "brain_vault")
    os.makedirs(vault, exist_ok=True)
    return EpisodicMemory(vault)


def _ensure_crewai() -> None:
    """Raise a clear error when the CrewAI runtime is unavailable."""
    if not CREWAI_AVAILABLE:
        raise RuntimeError(
            "CrewAI nu este disponibil. Instalează dependența `crewai` pentru "
            "orchestrarea multi-agent."
        ) from CREWAI_IMPORT_ERROR


def get_jarvis() -> JarvisEngine:
    global _jarvis_engine
    if _jarvis_engine is None:
        _jarvis_engine = JarvisEngine()
    return _jarvis_engine


def get_symbol_oracle() -> SymbolOracle:
    global _symbol_oracle
    if _symbol_oracle is None:
        _symbol_oracle = SymbolOracle(os.getcwd())
    return _symbol_oracle


def get_ensemble_oracle() -> EnsembleOracle:
    global _ensemble_oracle
    if _ensemble_oracle is None:
        _ensemble_oracle = EnsembleOracle()
    return _ensemble_oracle


def get_reasoning_hub() -> ReasoningHub:
    global _reasoning_hub
    if _reasoning_hub is None:
        _reasoning_hub = ReasoningHub()
    return _reasoning_hub


def get_context_manager() -> ContextManager:
    global _context_manager
    if _context_manager is None:
        vault_path = os.path.join(os.getcwd(), ".agent/brain_vault")
        os.makedirs(vault_path, exist_ok=True)
        _context_manager = ContextManager(vault_path)
    return _context_manager


def _get_neuro() -> "NeuroBrain | None":
    """Return NeuroBrain singleton if available and not disabled."""
    if not _NEURO_AVAILABLE:
        return None
    try:
        vault = os.path.join(os.getcwd(), ".agent/neuro")
        return get_neuro_brain(vault)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
#  PERMISSIONS & SECURITY (Claude Code Pattern - 7 Modes)
# ═══════════════════════════════════════════════════════════════


class PermissionMode:
    """
    7 Permission Modes (like Claude Code):
    - plan: Read-only - deny all writes
    - default: Ask for suspicious/destructive commands
    - auto: Auto-allow safe commands, notify for others
    - dontAsk: Auto-deny anything that would normally prompt (background)
    - bypassPermissions: Allow everything without prompting
    - bubble: For sub-agents that escalate to parent
    - acceptEdits: Auto-allow file edits, prompt for others
    """

    PLAN = "plan"  # Read-only, deny all writes
    DEFAULT = "default"  # Ask for suspicious/destructive
    AUTO = "auto"  # Auto-allow safe, notify others
    DONT_ASK = "dontAsk"  # Auto-deny prompts (background agents)
    BYPASS = "bypass"  # Fully autonomous
    BUBBLE = "bubble"  # Sub-agents escalate to parent
    ACCEPT_EDITS = "acceptEdits"  # Auto-allow file edits


# Commands that are always safe to run in parallel and in PLAN mode
BASH_READ_COMMANDS = {
    "ls",
    "cat",
    "grep",
    "rg",
    "find",
    "git status",
    "git diff",
    "head",
    "tail",
    "wc",
    "stat",
    "du",
    "df",
    "echo",
    "pwd",
}

IMPLEMENTATION_EXCLUDED_PARTS = {
    ".git",
    ".agent",
    ".jarvis",
    ".next",
    ".venv",
    "node_modules",
    "__pycache__",
    "workspace",
    "dist",
    "build",
    "coverage",
}

IMPLEMENTATION_SOURCE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".scss",
    ".html",
    ".json",
    ".md",
}


def check_tool_permission(
    tool_name: str, command: str = None, mode: str = PermissionMode.DEFAULT
) -> tuple[bool, str]:
    """Verify if a tool call is permitted in the current mode.

    Implements Claude Code's 7-mode permission system with resolution chain:
    1. Hook decision (if already decided)
    2. Rule matching (alwaysAllow/alwaysDeny/alwaysAsk)
    3. Tool-specific check
    4. Mode-based default
    5. Interactive prompt (if needed)
    """

    # ═══════════════════════════════════════════════════════════════
    # MODE 1: PLAN - Read-only, deny all writes
    # ═══════════════════════════════════════════════════════════════
    if mode == PermissionMode.PLAN:
        write_tools = ["file_write", "save_lesson", "execute_command"]
        if tool_name in write_tools:
            if tool_name == "execute_command":
                cmd_base = command.split()[0] if command else ""
                if cmd_base not in BASH_READ_COMMANDS:
                    return (
                        False,
                        f"❌ [PLAN MODE] Doar comenzi READ permise. '{cmd_base}' blocată.",
                    )
            else:
                return (
                    False,
                    f"❌ [PLAN MODE] '{tool_name}' este interzisă (doar citire).",
                )
        return True, ""

    # ═══════════════════════════════════════════════════════════════
    # MODE 2: DONT_ASK - Auto-deny prompts (for background agents)
    # ═══════════════════════════════════════════════════════════════
    if mode == PermissionMode.DONT_ASK:
        # Deny anything that would normally prompt
        if tool_name in ["file_write", "execute_command"]:
            return (
                False,
                f"❌ [DONT_ASK MODE] '{tool_name}' blocat pentru agenți background.",
            )
        return True, ""

    # ═══════════════════════════════════════════════════════════════
    # MODE 3: BYPASS - Allow everything without prompting
    # ═══════════════════════════════════════════════════════════════
    if mode == PermissionMode.BYPASS:
        return True, ""  # Everything allowed

    # ═══════════════════════════════════════════════════════════════
    # MODE 4: BUBBLE - Sub-agents escalate to parent
    # ═══════════════════════════════════════════════════════════════
    if mode == PermissionMode.BUBBLE:
        # For now, allow but mark for escalation
        return True, f"🔵 [BUBBLE] '{tool_name}' va escalada la părinte."

    # ═══════════════════════════════════════════════════════════════
    # MODE 5: ACCEPT_EDITS - Auto-allow file edits, prompt for others
    # ═══════════════════════════════════════════════════════════════
    if mode == PermissionMode.ACCEPT_EDITS:
        if tool_name == "file_write":
            return True, ""  # Auto-allow writes
        if tool_name == "execute_command":
            cmd_base = command.split()[0] if command else ""
            if cmd_base not in BASH_READ_COMMANDS:
                return (
                    False,
                    f"❌ [ACCEPT_EDITS] Doar comenzi READ permise. '{cmd_base}' blocată.",
                )
        return True, ""

    # ═══════════════════════════════════════════════════════════════
    # MODE 6: AUTO - Auto-allow safe, notify for others
    # ═══════════════════════════════════════════════════════════════
    if mode == PermissionMode.AUTO:
        # Auto-allow known safe tools
        safe_tools = [
            "file_read",
            "duck_duck_go_search",
            "obsidian_search",
            "memory_summary",
            "search_memory",
        ]
        if tool_name in safe_tools:
            return True, ""
        # Prompt for others
        if tool_name in ["file_write", "execute_command"]:
            return True, f"🔔 [AUTO MODE] '{tool_name}' va solicita permisiune."
        return True, ""

    # ═══════════════════════════════════════════════════════════════
    # MODE 7: DEFAULT - Ask for suspicious/destructive (fallback)
    # ═══════════════════════════════════════════════════════════════
    # DEFAULT MODE: Check for dangerous commands
    blocked_patterns = [
        "rm -rf /",
        "sudo",
        "mkfs",
        "dd if=",
        "> /dev/",
        "chmod -R 777",
        "curl | sh",
        "wget | sh",
        ":(){:|:&};:",
        "fork()",
        "chown -R",
        "sed -i",
    ]
    if command:
        for blocked in blocked_patterns:
            if blocked in command:
                return False, f"❌ [SECURITATE] Comanda blocată: '{blocked}'"

    return True, ""


# ═══════════════════════════════════════════════════════════════
#  TOOL DEFINITIONS
# ═══════════════════════════════════════════════════════════════

# Import Obsidian Research Tool
from tools.obsidian_researcher import obsidian_search, obsidian_get_note

# Global state for permission mode (can be changed by agents)
CURRENT_PERMISSION_MODE = PermissionMode.DEFAULT


@tool("duck_duck_go_search")
def duckduckgo_tool(query: str) -> str:
    """Search the web and return curated text results."""
    return duckduckgo_search(query=query, max_results=5)


@tool("obsidian_search")
def obsidian_search_tool(query: str) -> str:
    """Caută în Vault-ul Obsidian (memorie pe termen lung)."""
    return obsidian_search(query, vault_path=str(resolve_obsidian_vault_path()))


@tool("obsidian_read_note")
def obsidian_read_note_tool(note_name: str) -> str:
    """Citește o notă specifică din Vault-ul Obsidian."""
    return obsidian_get_note(note_name)


@tool("file_read")
def file_read_tool(path: str) -> str:
    """Read a UTF-8 text file from disk."""
    return read_text_file(path)


@tool("file_write")
def file_write_tool(path: str, content: str) -> str:
    """Write UTF-8 content to disk."""
    allowed, msg = check_tool_permission("file_write", mode=CURRENT_PERMISSION_MODE)
    if not allowed:
        return msg
    return write_text_file(path, content)


@tool("memory_summary")
def memory_summary_tool() -> str:
    """Obține un rezumat al memoriei organizaționale (misiuni trecute + lecții învățate)."""
    return get_memory_summary()


@tool("search_memory")
def search_memory_tool(keywords: str) -> str:
    """Caută în memorie după cuvinte cheie (separate prin virgulă). Returnează misiuni relevante."""
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    results = search_memory(kw_list, limit=5)
    if not results:
        return "Nu s-au găsit rezultate relevante în memorie."
    lines = []
    for r in results:
        score = f" (Scor: {r['quality_score']}/10)" if r.get("quality_score") else ""
        lines.append(
            f"• [{r.get('mission_type', '?')}]{score} {r['observation'][:200]}"
        )
    return "\n".join(lines)


@tool("save_lesson")
def save_lesson_tool(lesson: str, category: str, severity: str) -> str:
    """Salvează o lecție învățată pentru misiunile viitoare."""
    allowed, msg = check_tool_permission("save_lesson", mode=CURRENT_PERMISSION_MODE)
    if not allowed:
        return msg
    entry = save_lesson(lesson=lesson, category=category, severity=severity)
    return f"✅ Lecție salvată (#{entry['id']}): {lesson}"


@tool("execute_command")
def execute_command_tool(command: str) -> str:
    """Rulează o comandă bash (ex: python train.py, mkdir, touch) în folderul proiectului."""
    allowed, msg = check_tool_permission(
        "execute_command", command=command, mode=CURRENT_PERMISSION_MODE
    )
    if not allowed:
        return msg

    try:
        result = subprocess.run(
            command,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            shell=True,
            capture_output=True,
            text=True,
            timeout=360,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return f"✅ Succes:\n{result.stdout[-2000:]}"
        else:
            return f"❌ Eroare (cod {result.returncode}):\n{result.stderr[-1000:]}\n{result.stdout[-1000:]}"
    except subprocess.TimeoutExpired:
        return "⏰ Eroare: Comanda a depășit limita de 6 minute (Timeout)."
    except Exception as e:
        return f"💥 Comanda a eșuat critic: {str(e)}"


@tool("spawn_subagent_task")
def spawn_subagent_task(description: str, agent_type: str = "general") -> str:
    """Delegă o sub-sarcină specifică unui agent nou și returnează rezultatul real.

    Utilizează pipeline-ul complet CrewAI pentru sub-misiunea dată.
    Rezultatul real este injectat înapoi în contextul agentului apelant.
    """
    allowed, msg = check_tool_permission(
        "spawn_subagent_task", mode=CURRENT_PERMISSION_MODE
    )
    if not allowed:
        return msg

    try:
        logger.info(f"🚀 [SUBAGENT] Spawning sub-agent: {description[:80]}")
        result = run_mission(description)
        return f"🚀 [SUBAGENT RESULT]\n{str(result)[:2000]}"
    except Exception as e:
        logger.error(f"❌ [SUBAGENT] Failed: {e}")
        return f"❌ Sub-agent eșuat: {e}"


@tool("compact_context")
def compact_context_tool(text_to_summarize: str) -> str:
    """Rezultatele anterioare sunt prea lungi? Folosește această unealtă pentru a le comprima.

    Rulează un model rapid pentru a păstra doar esența, eliberând spațiu de gândire (tokens).
    """
    # Logic simplified: in production this calls a faster LLM to summarize
    summary_hint = (
        text_to_summarize[:500] + "..."
        if len(text_to_summarize) > 500
        else text_to_summarize
    )
    return f"📦 CONTEXT COMPRIMAT: Rezumatul datelor brute: {summary_hint}"


# ═══════════════════════════════════════════════════════════════
#  MISSION CLASSIFIER
# ═══════════════════════════════════════════════════════════════

MISSION_PATTERNS = {
    "code": [
        r"(?:scrie|creeaz[aă]|genereaz[aă]|implementeaz[aă])\s+(?:cod|program|script|ap[li]ca[tț]ie|site|web|html|css|javascript|python)",
        r"(?:fix|debu[g]|repar[aă]|corecteaz[aă])",
        r"(?:landing\s*page|frontend|backend|\bapi\b|server|database)",
        r"(?:optimizeaz[aă]|refactorizeaz[aă]|imbun[aă]t[aă][tț]ește|imbunatateste)\s+(?:componenta|componentele|pagina|paginile|modulul|modulele|imagin(?:ea|ile)|înc[aă]rcarea|incarcarea|performan[tț]a|codul|repo(?:ul)?)",
        r"(?:lazy\s+loading|code\s+splitting|performance|bundle|render(?:izare)?|component(?:a|ele)?|imag(?:ine|ini)|tsx|jsx|typescript|react|next\.js|repo(?:ul)?|fișier(?:ul|ele)?|fisier(?:ul|ele)?)",
    ],
    "business": [
        r"(?:plan\s+de\s+afaceri|strategi[ea]|marketing|startup|lansare|busin[e]ss)",
        r"(?:pre[tț]|pie[tț][aă]|competi[tț]|analiz[aă]\s+de|\bkpi\b|\broi\b|vânz[aă]ri)",
        r"(?:brand|copywriting|\bseo\b|growth|funnel|target\s+audience)",
    ],
    "research": [
        r"(?:cerceteaz[aă]|investigh?eaz[aă]|analizeaz[aă]|compar[aă]|studiu)",
        r"(?:\bml\b|machine\s+learning|train|antren|val_bpb|model|neural|deep\s+learn)",
        r"(?:trend|dat[ae]|surse|statistic[aă])",
    ],
    "design": [
        r"(?:design|\bui\b|\bux\b|interfa[tț][aă]|wireframe|mockup|prototip|logo)",
        r"(?:vizual|culori|font|layout|responsive|animat[aă]|estetic)",
    ],
}


def _looks_like_implementation_request(mission: str) -> bool:
    """Detect implementation intent that must touch real project files."""
    mission_lower = (mission or "").lower()
    implementation_verbs = [
        "implementează",
        "implementeaza",
        "optimizează",
        "optimizeaza",
        "refactorizează",
        "refactorizeaza",
        "îmbunătățește",
        "imbunatateste",
        "fix",
        "debug",
        "repară",
        "repara",
        "corectează",
        "corecteaza",
    ]
    code_targets = [
        "component",
        "componenta",
        "module",
        "modul",
        "pagina",
        "page",
        "ui",
        "frontend",
        "backend",
        "api",
        "server",
        "repo",
        "cod",
        "code",
        "script",
        "tsx",
        "jsx",
        "react",
        "next",
        "lazy loading",
        "performan",
        "imag",
        "încărc",
        "incarc",
        "fișier",
        "fisier",
    ]
    return any(token in mission_lower for token in implementation_verbs) and any(
        token in mission_lower for token in code_targets
    )


def _looks_like_code_audit_request(mission: str) -> bool:
    mission_lower = (mission or "").lower()
    audit_verbs = [
        "audit",
        "auditează",
        "auditeaza",
        "review",
        "revizuiește",
        "revizuieste",
        "analizează codul",
        "analizeaza codul",
        "verifică codul",
        "verifica codul",
    ]
    code_targets = [
        "cod",
        "code",
        "repo",
        "workspace",
        "agent fram",
        "propriului tău cod",
        "propriului tau cod",
        "modul",
        "module",
        "fișier",
        "fisier",
    ]
    return any(token in mission_lower for token in audit_verbs) and any(
        token in mission_lower for token in code_targets
    )


def classify_mission(mission: str) -> str:
    """Classify a mission into a type: code, business, research, design, or general.

    Uses regex pattern matching with scoring. Returns the type with highest match score.
    """
    mission_lower = mission.lower()
    if _looks_like_implementation_request(mission):
        return "code"
    if _looks_like_code_audit_request(mission):
        return "code"
    scores = {}

    for mtype, patterns in MISSION_PATTERNS.items():
        score = 0
        for pattern in patterns:
            matches = re.findall(pattern, mission_lower)
            score += len(matches) * 2
        scores[mtype] = score

    # If nothing matched well, it's general
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "general"
    return best


def get_project_rules() -> str:
    """Read project-specific rules from CLAUDE.md or .agent/rules.md."""
    paths = ["CLAUDE.md", ".agent/rules.md", "RULES.md"]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f"\n📜 REGULI PROIECT (din {p}):\n{f.read()}\n"
            except:
                pass
    return ""


# ═══════════════════════════════════════════════════════════════
#  AGENT BUILDER (with professional backstories)
# ═══════════════════════════════════════════════════════════════


def build_agents() -> dict[str, Agent]:
    """Build all available agents with role-optimized LLM configs."""
    _ensure_crewai()

    chronos = Agent(
        role="Chronos — Arhivist & Analist al Memoriei",
        goal=(
            "Extrage lecții acționabile din memoria organizațională. "
            "Identifică tipare în succesele și eșecurile trecute. "
            "Oferă context relevant pentru misiunea curentă."
        ),
        backstory=(
            "Ești arhivarul-șef al echipei. Ai acces la memoria pe termen lung și la lecțiile învățate. "
            "Rolul tău este CRUCIAL: previi echipa de la a repeta greșeli. "
            "Analizezi misiunile anterioare, extragi patterns și oferi guidance. "
            "REGULI: 1) Mereu citește memoria înainte de orice decizie, "
            "2) Identifică misiuni similare cu cea curentă, "
            "3) Evidențiază lecțiile critice, "
            "4) Dacă găsești o misiune similară căreia i-a fost dat un scor mic, AVERTIZEAZĂ explicit."
        ),
        tools=[
            memory_summary_tool,
            search_memory_tool,
            obsidian_search_tool,
            obsidian_read_note_tool,
        ],
        llm=get_llm_for_role("chronos"),
        allow_delegation=False,
        max_iter=5,
    )

    scout = Agent(
        role="Scout — Cercetaș Web & Intelligence",
        goal=(
            "Adună informații actualizate din web despre subiectul misiunii. "
            "Validează date cu surse reale. Oferă context competitiv."
        ),
        backstory=(
            "Ești cercetașul echipei — ochii și urechile în lumea digitală. "
            "Cauți rapid pe web și extragi informații relevante: prețuri, trenduri, concurenți, "
            "statistici, articole tehnice. Ești analitic și nu inventezi date. "
            "REGULI: 1) Fă minim 2 căutări diferite pentru perspective variate, "
            "2) Citează sursele (URL), "
            "3) Evidențiază cifre concrete (prețuri, procentaje, dimensiuni piață), "
            "4) Rezumatul tău trebuie să fie structurat cu bullet points."
        ),
        tools=[duckduckgo_tool],
        llm=get_llm_for_role("scout"),
        allow_delegation=False,
        max_iter=8,
    )

    architect = Agent(
        role="Architect — Planificator Strategic",
        goal=(
            "Transformă datele brute de la Scout și Chronos în planuri de execuție "
            "structurate, practice și acționabile."
        ),
        backstory=(
            "Ești arhitectul de business și tehnic al echipei. Primești informații brute "
            "și le transformi în planuri clare cu pași concreți. "
            "FOCUS: viziune, riscuri, mitigări, timeline, resurse necesare. "
            "REGULI: 1) Planul TREBUIE să aibă minim 5 pași concreti, "
            "2) Fiecare pas are estimated time, "
            "3) Identifică minim 3 riscuri cu plan de mitigare, "
            "4) Output-ul e format Markdown structurat."
        ),
        tools=[memory_summary_tool],
        llm=get_llm_for_role("architect"),
        allow_delegation=False,
        max_iter=5,
    )

    researcher = Agent(
        role="ML Researcher — Expert Machine Learning",
        goal=(
            "Îmbunătățește performanța modelelor de ML. "
            "Editează cod, rulează experimente, monitorizează metrici."
        ),
        backstory=(
            "Ești cercetătorul de ML al echipei. Ai experiență practică cu training de modele. "
            "Poți edita cod Python, rula scripturi, monitoriza metrici (val_bpb, loss). "
            "REGULI: 1) Mereu citește codul existent ÎNAINTE de modificare, "
            "2) Fă backup înainte de edit-uri majore, "
            "3) Documentează ce ai modificat și de ce, "
            "4) Raportează metrici CONCRETE (numerice) nu calitative."
        ),
        tools=[file_read_tool, file_write_tool, execute_command_tool],
        llm=get_llm_for_role("researcher"),
        allow_delegation=False,
        max_iter=10,
    )

    ui_designer = Agent(
        role="UI/UX Designer — Expert Interfețe",
        goal=(
            "Proiectează interfețe intuitive, estetice și responsive. "
            "Gândește palete de culori, tipografie, layout, și user flows."
        ),
        backstory=(
            "Ești designerul echipei — experu în UX/UI modern. "
            "Cunoști trendurile 2026: glassmorphism, dark mode, gradient mesh, micro-animații. "
            "REGULI: 1) Specifică exact codurile de culoare (hex/HSL), "
            "2) Recomandă font-uri specifice (Google Fonts), "
            "3) Descrie layout-ul cu grid/flex, "
            "4) Gândește mobile-first."
        ),
        tools=[duckduckgo_tool, file_write_tool],
        llm=get_llm_for_role("ui designer"),
        allow_delegation=False,
        max_iter=6,
    )

    marketing_guru = Agent(
        role="Marketing Guru — Strateg & Copywriter",
        goal=(
            "Creează strategii de marketing complete: pricing, segmentare, positioning, "
            "copy persuasiv și plan de lansare."
        ),
        backstory=(
            "Ești guru-ul de marketing al echipei — expert în growth hacking, SEO, "
            "copywriting persuasiv și strategii de piață. "
            "REGULI: 1) Strategia TREBUIE să includă analiza competitivă (tabel), "
            "2) Include mereu KPI-uri măsurabile cu target-uri concrete, "
            "3) Propune un buget realist defalcat pe canale, "
            "4) Copywriting-ul trebuie să fie convingător, nu generic, "
            "5) Scrie MINIM 500 de cuvinte — interzis răspunsuri scurte."
        ),
        tools=[duckduckgo_tool, file_write_tool],
        llm=get_llm_for_role("marketing"),
        allow_delegation=False,
        max_iter=8,
    )

    web_developer = Agent(
        role="Web Developer — Programator Full-Stack",
        goal=(
            "Scrie cod funcțional, valid și bine structurat: HTML, CSS, JS, Python. "
            "Implementează designul și salvează fișierele pe disk."
        ),
        backstory=(
            "Ești dev-ul echipei — transformi concepte în cod real. "
            "Scrii HTML semantic, CSS modern (grid, flex, variables), JavaScript curat. "
            "REGULI: 1) MEREU citește codul existent înainte de editare, "
            "2) Codul trebuie să fie COMPLET — nu lăsa TODO-uri sau placeholders, "
            "3) Folosește best practices: semantic HTML, responsive CSS, accesibilitate, "
            "4) Salvează fișierele cu File Write pe disk."
        ),
        tools=[file_read_tool, file_write_tool, execute_command_tool],
        llm=get_llm_for_role("developer"),
        allow_delegation=False,
        max_iter=10,
    )

    critic = Agent(
        role="Critic — Quality Assurance & Auto-Evaluare",
        goal=(
            "Evaluează calitatea rezultatului final. "
            "Dă un scor 1-10 și identifică ce trebuie îmbunătățit. "
            "Salvează lecții pentru misiunile viitoare."
        ),
        backstory=(
            "Ești criticul echipei — ultima linie de apărare a calității. "
            "Evaluezi OBIECTIV fiecare rezultat. Nu ești generos cu scorurile. "
            "REGULI: 1) Evaluează pe 5 criterii: completitudine, acuratețe, "
            "structură, detaliu, utilizabilitate, "
            "2) Scor FINAL 1-10 cu justificare, "
            "3) Dacă scorul < 6, specifică EXACT ce lipsește, "
            "4) Salvează minim 1 lecție învățată cu Save Lesson, "
            "5) Fii SINCER — un 10/10 este excepțional, nu normal."
        ),
        tools=[save_lesson_tool, memory_summary_tool],
        llm=get_llm_for_role("critic"),
        allow_delegation=False,
        max_iter=5,
    )

    return {
        "chronos": chronos,
        "scout": scout,
        "architect": architect,
        "researcher": researcher,
        "ui": ui_designer,
        "marketing": marketing_guru,
        "dev": web_developer,
        "critic": critic,
    }


# ═══════════════════════════════════════════════════════════════
#  DYNAMIC PIPELINE BUILDER
# ═══════════════════════════════════════════════════════════════

# Which agents participate in each mission type
PIPELINE_CONFIG = {
    "business": {
        "agents": ["chronos", "scout", "architect", "marketing", "critic"],
        "description": "Pipeline Business: Memory → Research → Planning → Marketing Strategy → QA",
    },
    "code": {
        "agents": ["chronos", "scout", "architect", "dev", "critic"],
        "description": "Pipeline Code: Memory → Research → Planning → Implementation → QA",
    },
    "research": {
        "agents": ["chronos", "scout", "researcher", "critic"],
        "description": "Pipeline Research: Memory → Web Intel → Deep Research → QA",
    },
    "design": {
        "agents": ["chronos", "scout", "ui", "dev", "critic"],
        "description": "Pipeline Design: Memory → Inspiration → UI Design → Implementation → QA",
    },
    "general": {
        "agents": ["chronos", "scout", "architect", "marketing", "critic"],
        "description": "Pipeline General: Memory → Research → Planning → Delivery → QA",
    },
}


def build_tasks(
    user_goal: str,
    mission_type: str,
    agents_map: dict[str, Agent],
    anti_repetition: str,
    relevant_lessons: list[dict],
    project_rules: str = "",
) -> list[Task]:
    """Build a dynamic task pipeline based on mission type.

    Returns an ordered list of Tasks for the Crew to execute.
    """
    _ensure_crewai()
    lessons_text = (
        "\n".join(
            f"  • [{l.get('severity', 'info').upper()}] {l['lesson']}"
            for l in relevant_lessons
        )
        if relevant_lessons
        else "Nu există lecții relevante anterioare."
    )

    global_context = f"{project_rules}\n{lessons_text}\n"

    tasks = []

    # ─── PHASE 1: Memory & Context (always first) ─────────
    task_memory = Task(
        description=(
            f"MISIUNE: {user_goal}\n\n"
            f"Ești Chronos. Consultă memoria organizațională și oferă context relevant.\n"
            f"{global_context}\n"
            f"AVERTISMENTE:\n{anti_repetition}\n\n"
            "TREBUIE SĂ:\n"
            "1. Citești rezumatul memoriei cu Memory Summary\n"
            "2. Cauți misiuni similare cu Search Memory\n"
            "3. Sintetizezi: ce a mers bine, ce a mers prost, ce trebuie evitat\n"
            "4. Oferă RECOMANDĂRI concrete pentru echipă"
        ),
        expected_output=(
            "Raport de context cu: (a) misiuni similare anterioare, "
            "(b) lecții aplicabile, (c) recomandări concrete pentru misiunea curentă."
        ),
        agent=agents_map["chronos"],
    )
    tasks.append(task_memory)

    # ─── PHASE 2: Research & Intelligence ─────────────────
    pipeline_agents = PIPELINE_CONFIG.get(mission_type, PIPELINE_CONFIG["general"])[
        "agents"
    ]

    if "scout" in pipeline_agents:
        research_focus = {
            "business": "trenduri de piață, competitori, statistici de industrie, prețuri",
            "code": "technologii, librării, best practices, exemple de implementare",
            "research": "papers, date, metrici, benchmarks, metodologii",
            "design": "trenduri UI/UX 2026, inspirație, pallete de culori, best practices",
            "general": "informații relevante, context, date actualizate",
        }.get(mission_type, "informații relevante")

        task_research = Task(
            description=(
                f"MISIUNE: {user_goal}\n\n"
                f"Cercetează web-ul pentru: {research_focus}.\n"
                "TREBUIE SĂ:\n"
                "1. Faci minim 2 căutări web diferite cu DuckDuckGo Search\n"
                "2. Extragi date CONCRETE (cifre, prețuri, statistici)\n"
                "3. Citezi sursele (URL-uri)\n"
                "4. Structurezi informațiile cu bullet points\n"
                "5. Evidențiezi cele mai importante 3 descoperiri"
            ),
            expected_output=(
                "Raport de cercetare structurat cu: surse web, date concrete, "
                "analiză competitivă, și top 3 insights cheie."
            ),
            agent=agents_map["scout"],
            context=[task_memory],
        )
        tasks.append(task_research)

    # ─── PHASE 3: Planning (for business/code/design) ─────
    if "architect" in pipeline_agents:
        task_plan = Task(
            description=(
                f"MISIUNE: {user_goal}\n\n"
                "Analizează rapoartele de la Chronos și Scout. Creează un PLAN DE EXECUȚIE.\n"
                "STRUCTURĂ OBLIGATORIE:\n"
                "## Obiectiv Principal\n"
                "## Pași de Execuție (minim 5, numerotați, cu timp estimat)\n"
                "## Riscuri & Mitigări (minim 3)\n"
                "## Resurse Necesare\n"
                "## Criteriu de Succes (cum măsurăm că e gata)\n"
            ),
            expected_output="Plan de execuție complet, structurat, cu pași numerotați și riscuri.",
            agent=agents_map["architect"],
            context=tasks[-2:],  # Memory + Research context
        )
        tasks.append(task_plan)

    # ─── PHASE 4: Execution (domain-specific) ─────────────
    execution_agent = None
    exec_description = ""

    if mission_type == "business" and "marketing" in pipeline_agents:
        execution_agent = agents_map["marketing"]
        exec_description = (
            f"MISIUNE FINALĂ: {user_goal}\n\n"
            "Primești contextul de la Chronos, cercetarea Scout-ului și planul Arhitectului.\n"
            "CREEAZĂ un document PROFESIONAL complet.\n\n"
            "STRUCTURĂ OBLIGATORIE:\n"
            "# 📋 DOCUMENT STRATEGIC\n"
            "## 1. Rezumat Executiv (viziune + obiective SMART)\n"
            "## 2. Analiză de Piață (tabel competitiv cu minim 3 concurenți)\n"
            "## 3. Strategie de Marketing (4P: Product, Price, Place, Promotion)\n"
            "## 4. Plan de Lansare (timeline cu date concrete)\n"
            "## 5. Buget Defalcat (tabel cu sume pe canal)\n"
            "## 6. KPI-uri & Metrici de Succes\n\n"
            "IMPORTANT:\n"
            "- Scrie MINIM 600 cuvinte\n"
            "- Include TABELE markdown (minim 2)\n"
            "- Folosește date REALE din cercetarea Scout-ului\n"
            "- INTERZIS: răspunsuri scurte, generic, sau 'Sarcină îndeplinită'"
        )
    elif mission_type == "code" and "dev" in pipeline_agents:
        execution_agent = agents_map["dev"]
        exec_description = (
            f"MISIUNE FINALĂ: {user_goal}\n\n"
            "Implementează codul conform planului.\n"
            "TREBUIE SĂ:\n"
            "1. Citești planul Arhitectului cu atenție\n"
            "2. Scrii cod COMPLET (nu schițe sau pseudo-cod)\n"
            "3. Folosești File Write pentru a salva fișierele pe disk\n"
            "4. Testezi cu Execute Command dacă e posibil\n"
            "5. Codul trebuie să fie: semantic, responsive, accesibil\n"
            "6. INTERZIS: TODO-uri, placeholders, cod incomplet"
        )
    elif mission_type == "research" and "researcher" in pipeline_agents:
        execution_agent = agents_map["researcher"]
        exec_description = (
            f"MISIUNE FINALĂ: {user_goal}\n\n"
            "Execută cercetarea aprofundată.\n"
            "TREBUIE SĂ:\n"
            "1. Citești codul/datele existente cu File Read\n"
            "2. Faci modificările necesare cu File Write\n"
            "3. Rulezi experimente cu Execute Command\n"
            "4. Raportezi metrici CONCRETE (valori numerice)\n"
            "5. Documentezi toate modificările făcute"
        )
    elif mission_type == "design" and "ui" in pipeline_agents:
        execution_agent = agents_map["ui"]
        exec_description = (
            f"MISIUNE FINALĂ: {user_goal}\n\n"
            "Proiectează interfața conform planului.\n"
            "LIVRABILE:\n"
            "1. Paletă de culori (minim 5 culori hex)\n"
            "2. Recomandare font (Google Fonts)\n"
            "3. Layout description (grid/flexbox)\n"
            "4. Componente cheie cu descrieri\n"
            "5. Salvează specificațiile cu File Write"
        )

    if execution_agent:
        task_execute = Task(
            description=exec_description,
            expected_output="Rezultatul complet al execuției: document/cod/design profesional.",
            agent=execution_agent,
            context=tasks[-2:],  # Last 2 tasks as context
        )
        tasks.append(task_execute)

        # If code mission and we have UI agent, chain it
        if mission_type == "code" and "ui" in pipeline_agents:
            task_design = Task(
                description=(
                    f"MISIUNE DESIGN: {user_goal}\n\n"
                    "Revizuiește codul scris de Developer și asigură-te că e vizual frumos.\n"
                    "Propune îmbunătățiri CSS dacă e nevoie."
                ),
                expected_output="Review de design cu sugestii concrete.",
                agent=agents_map["ui"],
                context=[task_execute],
            )
            tasks.append(task_design)

    # ─── PHASE 5: Quality Assurance (always last) ─────────
    task_qa = Task(
        description=(
            f"MISIUNEA ORIGINALĂ: {user_goal}\n\n"
            "Ești Criticul. Evaluează OBIECTIV rezultatul echipei.\n\n"
            "CRITERIILE DE EVALUARE (fiecare 1-10):\n"
            "1. **Completitudine** — Sunt toate elementele cerute prezente?\n"
            "2. **Acuratețe** — Informațiile sunt corecte și actualizate?\n"
            "3. **Structură** — E bine organizat, ușor de citit?\n"
            "4. **Detaliu** — Suficient de detaliat pentru a fi util?\n"
            "5. **Utilizabilitate** — Poate fi folosit imediat de client?\n\n"
            "FORMAT OBLIGATORIU al răspunsului:\n"
            "```\n"
            "EVALUARE CALITATE:\n"
            "Completitudine: X/10 — [comentariu]\n"
            "Acuratețe: X/10 — [comentariu]\n"
            "Structură: X/10 — [comentariu]\n"
            "Detaliu: X/10 — [comentariu]\n"
            "Utilizabilitate: X/10 — [comentariu]\n"
            "SCOR TOTAL: X/10\n"
            "```\n\n"
            "TREBUIE SĂ:\n"
            "1. Salvezi minim 1 lecție cu Save Lesson\n"
            "2. Fii sincer — un scor 10/10 e excepțional\n"
            "3. Dacă scorul < 6, specifică EXACT ce trebuie refăcut\n"
        ),
        expected_output=(
            "Evaluare structurată cu scoruri pe 5 criterii, scor total, "
            "și cel puțin o lecție învățată salvată."
        ),
        agent=agents_map["critic"],
        context=tasks[-2:],  # Last execution + planning context
    )
    tasks.append(task_qa)

    return tasks


# ═══════════════════════════════════════════════════════════════
#  MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════


def _run_skill_evolution_bg(
    mission_id: str,
    mission: str,
    result: str,
    quality_score: int,
    *,
    context: dict[str, Any] | None = None,
    governance_signal: dict[str, Any] | None = None,
    report_path: str | None = None,
    latest_path: str | None = None,
):
    """Run post-mission skill evolution in a background thread (fire-and-forget)."""
    import threading

    def _worker():
        try:
            import asyncio
            from core.self_evolving_skills import SelfEvolvingSkills

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            engine = SelfEvolvingSkills(
                os.path.join(os.getcwd(), ".jarvis/skills")
            )
            governance = loop.run_until_complete(
                engine.post_mission_hook(
                    mission,
                    result,
                    quality_score,
                    context=context or {"mission_id": mission_id},
                )
            )
            if governance:
                _persist_post_mission_governance(
                    mission_id,
                    governance,
                    governance_signal=governance_signal,
                    report_path=report_path,
                    latest_path=latest_path,
                )
            loop.close()
        except Exception as e:
            logger.debug(f"[SKILL EVOLUTION BG] {e}")

    threading.Thread(target=_worker, daemon=True).start()


def _persist_post_mission_governance(
    mission_id: str,
    governance: dict[str, Any],
    governance_signal: dict[str, Any] | None = None,
    report_path: str | None = None,
    latest_path: str | None = None,
) -> None:
    """Merge post-mission governance into persisted runtime reports."""
    targets = [Path(path) for path in [report_path, latest_path] if path]
    for target in targets:
        try:
            if not target.exists():
                continue
            payload = json.loads(target.read_text(encoding="utf-8"))
            if payload.get("mission_id") not in {None, mission_id}:
                continue
            payload["post_mission_governance"] = governance
            payload["mission_closure"] = _build_mission_closure(
                mission_id,
                success=bool(payload.get("success")),
                verified_success=bool(payload.get("verified_success")),
                dod_report=payload.get("definition_of_done") or {},
                governance_signal=governance_signal or payload.get("governance_signal") or {},
                post_mission_governance=governance,
            )
            target.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("[POST-MISSION GOVERNANCE] Persist failed for %s: %s", target, exc)

    try:
        base_dir = (
            Path(report_path).parent
            if report_path
            else Path(latest_path).parent
            if latest_path
            else Path(os.getcwd()) / ".agent" / "runtime_reports"
        )
        base_dir.mkdir(parents=True, exist_ok=True)
        history_path = base_dir / "governance_history.jsonl"
        history_record = {
            "mission_id": mission_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "action": governance.get("action"),
            "status": governance.get("status"),
            "gate_decision": governance.get("gate_decision"),
            "gate_reason": governance.get("gate_reason"),
            "candidate_skill_id": governance.get("candidate_skill_id"),
            "candidate_skill_name": governance.get("candidate_skill_name"),
            "matched_skill_id": governance.get("matched_skill_id"),
            "matched_skill_name": governance.get("matched_skill_name"),
            "proposal_id": governance.get("proposal_id"),
            "eval_suite_name": governance.get("eval_suite_name"),
            "quality_score": governance.get("quality_score"),
            "governance_signal": governance_signal or {},
        }
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(history_record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("[POST-MISSION GOVERNANCE] History append failed: %s", exc)

    try:
        NeuroMaintenanceJournal(Path(os.getcwd()) / ".agent" / "neuro").record_governance(
            mission_id,
            governance,
            governance_signal=governance_signal,
        )
    except Exception as exc:
        logger.debug("[POST-MISSION GOVERNANCE] Neuro maintenance sync failed: %s", exc)

    if _V3_AVAILABLE:
        try:
            payload = {
                "action": governance.get("action"),
                "status": governance.get("status"),
                "proposal_id": governance.get("proposal_id"),
                "candidate_skill_id": governance.get("candidate_skill_id"),
                "candidate_skill_name": governance.get("candidate_skill_name"),
                "eval_suite_name": governance.get("eval_suite_name"),
                "gate_decision": governance.get("gate_decision"),
                "gate_reason": governance.get("gate_reason"),
                "quality_score": governance.get("quality_score"),
                "governance_signal": governance_signal or {},
            }
            if governance.get("proposal_id"):
                get_event_log().emit(
                    E.IMPROVEMENT_PROPOSED,
                    mission_id,
                    actor_role="governance",
                    payload=payload,
                )
            if governance.get("gate_decision"):
                get_event_log().emit(
                    E.PROMOTION_DECIDED,
                    mission_id,
                    actor_role="governance",
                    payload=payload,
                )
                if governance.get("gate_decision") == "promote":
                    get_event_log().emit(
                        E.IMPROVEMENT_PROMOTED,
                        mission_id,
                        actor_role="governance",
                        payload=payload,
                    )
                elif governance.get("gate_decision") == "reject":
                    get_event_log().emit(
                        E.IMPROVEMENT_REJECTED,
                        mission_id,
                        actor_role="governance",
                        payload=payload,
                    )
        except Exception as exc:
            logger.debug("[POST-MISSION GOVERNANCE] Event emission failed: %s", exc)


def _build_governance_signal(
    mission_id: str,
    qa_text: str,
    metrics_dict: dict[str, Any],
    dod_report: dict[str, Any],
    failure_codes: list[str],
) -> dict[str, Any]:
    """Build a compact control-plane signal safe to feed into maintenance layers."""
    rates = metrics_dict.get("rates", {}) if isinstance(metrics_dict, dict) else {}
    return {
        "mission_id": mission_id,
        "quality_score": _extract_quality_score(qa_text) or 0,
        "verification_rate": float(rates.get("verification_rate", 0.0)),
        "dod_done": bool(dod_report.get("done")),
        "dod_score": float(dod_report.get("score", 0.0)),
        "critical_failure_count": len(
            [
                code
                for code in failure_codes
                if code in {"RISK_POLICY_BLOCK", "VERIFICATION_FAIL", "HALLUCINATED_SUCCESS", "RECOVERY_FAIL", "UI_GROUNDING_FAIL"}
            ]
        ),
        "failure_codes": list(failure_codes),
    }


def _build_mission_closure(
    mission_id: str,
    *,
    success: bool,
    verified_success: bool,
    dod_report: dict[str, Any],
    governance_signal: dict[str, Any] | None = None,
    post_mission_governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an operator-facing closure verdict for the latest mission."""
    governance_signal = governance_signal or {}
    post_mission_governance = post_mission_governance or {}
    failed_criteria = [
        criterion.get("name")
        for criterion in dod_report.get("criteria", [])
        if not criterion.get("passed")
    ]
    gate_decision = (
        post_mission_governance.get("gate_decision")
        or post_mission_governance.get("status")
        or "none"
    )

    status = "closed"
    summary = "Mission closed cleanly."
    next_action = "No operator action required."
    operator_action_required = False

    if str(gate_decision).lower() == "hold":
        status = "awaiting_operator"
        operator_action_required = True
        summary = "Mission completed, but governance is holding the follow-up improvement."
        next_action = "Review the held proposal and decide approve, queue eval, or reject."
    elif str(gate_decision).lower() == "reject":
        status = "closed_with_rejection"
        summary = "Mission closed; the follow-up improvement was rejected by governance."
        next_action = "Review rejection rationale if you want to retry with a safer candidate."
    elif not bool(dod_report.get("done")):
        status = "needs_review"
        operator_action_required = True
        summary = "Mission finished, but Definition of Done is incomplete."
        next_action = "Inspect the failed DoD criteria and rerun or repair the mission."
    elif success and not verified_success:
        status = "needs_review"
        operator_action_required = True
        summary = "Mission executed successfully, but verification did not fully close."
        next_action = "Review verification gaps before treating this mission as complete."

    return {
        "mission_id": mission_id,
        "status": status,
        "summary": summary,
        "operator_action_required": operator_action_required,
        "next_action": next_action,
        "gate_decision": gate_decision,
        "dod_done": bool(dod_report.get("done")),
        "verified_success": bool(verified_success),
        "failed_criteria": failed_criteria,
        "quality_score": governance_signal.get("quality_score"),
    }


def _extract_quality_score(result_text: str) -> int | None:
    """Try to extract quality score from Critic's output."""
    # Look for "SCOR TOTAL: X/10" pattern
    patterns = [
        r"SCOR\s+TOTAL[:\s]+(\d+)\s*/\s*10",
        r"(?:scor|score)\s*(?:total|final)[:\s]+(\d+)\s*/\s*10",
        r"(\d+)\s*/\s*10\s*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, result_text, re.IGNORECASE | re.MULTILINE)
        if match:
            score = int(match.group(1))
            if 1 <= score <= 10:
                return score
    return None


def _extract_tags(mission: str) -> list[str]:
    """Auto-extract tags from mission text."""
    tag_keywords = {
        "cafea": "cafea",
        "coffee": "cafea",
        "marketing": "marketing",
        "strategi": "strategie",
        "html": "web",
        "css": "web",
        "javascript": "web",
        "site": "web",
        "landing": "landing-page",
        "page": "web",
        "startup": "startup",
        "afacer": "business",
        "ml": "ml",
        "machine": "ml",
        "train": "ml",
        "model": "ml",
        "design": "design",
        "ui": "design",
        "ux": "design",
        "python": "python",
        "cod": "code",
        "script": "code",
    }
    mission_lower = mission.lower()
    tags = set()
    for keyword, tag in tag_keywords.items():
        if keyword in mission_lower:
            tags.add(tag)
    return list(tags)


def _mission_workspace(mission_id: str) -> Path:
    """Return a stable orchestrator workspace for deliverables."""
    path = Path(os.getcwd()) / "workspace" / "orchestrator"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{mission_id}.md"


def _collect_real_artifacts(results: list[dict], deliverable_path: str | None = None) -> list[str]:
    """Return artifacts that reflect project changes, not orchestrator reports."""
    ignored_paths: set[Path] = set()
    if deliverable_path:
        ignored_paths.add(Path(deliverable_path).resolve())

    runtime_roots = [
        (Path(os.getcwd()) / "workspace" / "orchestrator").resolve(),
        (Path(os.getcwd()) / ".agent" / "runtime_reports").resolve(),
    ]
    artifacts: list[str] = []
    seen: set[str] = set()

    for item in results:
        result_payload = item.get("result") or {}
        for artifact in result_payload.get("artifacts", []) or []:
            try:
                resolved = Path(artifact).resolve()
            except Exception:
                continue
            if resolved in ignored_paths:
                continue
            if any(root in resolved.parents or resolved == root for root in runtime_roots):
                continue
            normalized = str(resolved)
            if normalized not in seen:
                seen.add(normalized)
                artifacts.append(normalized)

    return artifacts


def _is_allowed_repo_target(path: str) -> bool:
    """Allow writes only inside the repo and outside protected/generated zones."""
    try:
        target = Path(path)
        if target.is_absolute():
            target = target.resolve().relative_to(Path(os.getcwd()).resolve())
        normalized = Path(str(target).lstrip("/"))
    except Exception:
        return False

    if any(part in IMPLEMENTATION_EXCLUDED_PARTS for part in normalized.parts):
        return False
    if ".." in normalized.parts:
        return False
    return bool(normalized.parts)


def _extract_implementation_keywords(user_goal: str, limit: int = 8) -> list[str]:
    stopwords = {
        "te", "rog", "aceasta", "această", "sugestie", "care", "tu", "ai", "generat",
        "anterior", "pentru", "prin", "să", "sa", "the", "and", "with", "that",
        "this", "into", "from", "este", "sunt", "fara", "fără", "doar", "daca",
        "dacă", "real", "reale", "fișierele", "fisierele", "proiectului", "project",
    }
    tokens = re.findall(r"[A-Za-zĂÂÎȘȚăâîșț0-9_.-]+", (user_goal or "").lower())
    keywords: list[str] = []
    for token in tokens:
        if len(token) < 3 or token in stopwords:
            continue
        if token not in keywords:
            keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def _collect_autonomous_execution_hints(runtime_ctx: dict) -> list[str]:
    """Collect high-signal coordinator/plan hints for implementation targeting."""
    hints: list[str] = []
    mission_preflight = runtime_ctx.get("mission_preflight") or {}

    for step in mission_preflight.get("first_steps") or []:
        if isinstance(step, str) and step.strip():
            hints.append(step.strip())

    for spec in mission_preflight.get("coordinator_task_specs") or []:
        if not isinstance(spec, dict):
            continue
        description = str(spec.get("description") or "").strip()
        expected = str(spec.get("expected_output") or "").strip()
        if description:
            hints.append(description)
        if expected:
            hints.append(expected)

    ultraplan_bundle = runtime_ctx.get("ultraplan_bundle") or {}
    for step in ultraplan_bundle.get("steps") or []:
        if not isinstance(step, dict):
            continue
        title = str(step.get("title") or "").strip()
        objective = str(step.get("objective") or "").strip()
        if title:
            hints.append(title)
        if objective:
            hints.append(objective)

    execution_guidance = str(runtime_ctx.get("execution_guidance") or "").strip()
    if execution_guidance:
        hints.append(execution_guidance)

    # Keep the prompt and candidate scorer tight; high-signal first.
    deduped: list[str] = []
    for hint in hints:
        if hint not in deduped:
            deduped.append(hint)
        if len(deduped) >= 8:
            break
    return deduped


def _find_candidate_source_files(
    user_goal: str,
    limit: int = 6,
    extra_hints: list[str] | None = None,
) -> list[dict[str, str]]:
    """Find likely source files to edit for an implementation request."""
    root = Path(os.getcwd())
    keywords = _extract_implementation_keywords(user_goal)
    hint_keywords: list[str] = []
    for hint in extra_hints or []:
        for keyword in _extract_implementation_keywords(hint, limit=10):
            if keyword not in hint_keywords:
                hint_keywords.append(keyword)
    candidates: list[tuple[int, Path]] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IMPLEMENTATION_EXCLUDED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in IMPLEMENTATION_SOURCE_EXTENSIONS:
            continue
        if path.stat().st_size > 200_000:
            continue

        rel = path.relative_to(root)
        rel_text = str(rel).lower()
        score = 0
        for keyword in keywords:
            if keyword in rel_text:
                score += 4
        for keyword in hint_keywords:
            if keyword in rel_text:
                score += 2
        if rel.suffix.lower() in {".tsx", ".ts", ".jsx", ".js"}:
            score += 1
        if "nucleus_ui" in rel.parts or "app" in rel.parts or "components" in rel.parts:
            score += 1
        if score > 0:
            candidates.append((score, path))

    candidates.sort(key=lambda item: (-item[0], str(item[1])))
    selected = [path for _, path in candidates[:limit]]

    if not selected:
        fallbacks = [
            root / "nucleus_ui" / "app" / "page.tsx",
            root / "nucleus_ui" / "app" / "layout.tsx",
            root / "core" / "orchestrator.py",
        ]
        selected = [path for path in fallbacks if path.exists()][:limit]

    payload: list[dict[str, str]] = []
    for path in selected:
        rel = path.relative_to(root)
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        payload.append(
            {
                "path": str(rel),
                "content": _safe_excerpt(content, 6000),
            }
        )
    return payload


def _parse_brain_json_payload(raw_text: str) -> dict[str, Any]:
    """Parse JSON returned by the brain, tolerating fenced blocks."""
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


async def _generate_autonomous_code_plan(user_goal: str, runtime_ctx: dict) -> dict[str, Any]:
    """Generate a concrete file-change plan for an autonomous implementation request."""
    execution_hints = _collect_autonomous_execution_hints(runtime_ctx)
    candidate_files = _find_candidate_source_files(
        user_goal,
        extra_hints=execution_hints,
    )
    if not candidate_files:
        return {"error": "No candidate project files found for implementation."}

    project_rules = get_project_rules()
    memory_context = _safe_excerpt(runtime_ctx["step_outputs"].get("memory_context"), 1200)
    research_context = _safe_excerpt(runtime_ctx["step_outputs"].get("web_research"), 1600)
    plan_context = _safe_excerpt(runtime_ctx["step_outputs"].get("execution_plan"), 1800)
    execution_guidance = _safe_excerpt(runtime_ctx.get("execution_guidance"), 1200)
    coordinator_context = _safe_excerpt(runtime_ctx["step_outputs"].get("coordinator_execution"), 2200)
    mission_preflight = runtime_ctx.get("mission_preflight") or {}
    coordinator_specs = mission_preflight.get("coordinator_task_specs") or []
    ultraplan_bundle = runtime_ctx.get("ultraplan_bundle") or {}
    candidate_blob = "\n\n".join(
        f"FILE: {item['path']}\n{item['content']}" for item in candidate_files
    )

    system_prompt = (
        "You are J.A.R.V.I.S. autonomous implementation engine.\n"
        "Return STRICT JSON only with this shape:\n"
        "{"
        "\"summary\": string, "
        "\"files\": [{\"path\": string, \"content\": string}], "
        "\"notes\": [string]"
        "}\n"
        "Rules:\n"
        "- Propose only real source changes inside the repo.\n"
        "- Never target .agent, .jarvis, workspace, node_modules, .next, dist, build, or .venv.\n"
        "- Prefer editing the provided candidate files.\n"
        "- Respect mission preflight, coordinator task specs, and ULTRAPLAN sequencing when they are present.\n"
        "- Prefer the smallest file set that satisfies the prepared task specs.\n"
        "- If the request cannot be implemented from the provided context, return files as []."
    )
    user_prompt = (
        f"Goal:\n{user_goal}\n\n"
        f"Project rules:\n{project_rules or 'No extra project rules.'}\n\n"
        f"Memory context:\n{memory_context or 'None'}\n\n"
        f"Fresh context:\n{research_context or 'None'}\n\n"
        f"Execution plan:\n{plan_context or 'None'}\n\n"
        f"Principal execution guidance:\n{execution_guidance or 'None'}\n\n"
        f"Execution hints:\n{json.dumps(execution_hints, ensure_ascii=False, indent=2) if execution_hints else 'None'}\n\n"
        f"Mission preflight:\n{json.dumps(mission_preflight, ensure_ascii=False, indent=2) if mission_preflight else 'None'}\n\n"
        f"Coordinator task specs:\n{json.dumps(coordinator_specs, ensure_ascii=False, indent=2) if coordinator_specs else 'None'}\n\n"
        f"UltraPlan bundle:\n{json.dumps(ultraplan_bundle, ensure_ascii=False, indent=2)[:2200] if ultraplan_bundle else 'None'}\n\n"
        f"Coordinator execution:\n{coordinator_context or 'None'}\n\n"
        f"Candidate files:\n{candidate_blob}"
    )
    raw = await call_brain(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=PRO_MODEL,
        profile="coder",
    )
    if str(raw).startswith("ERROR:"):
        return {"error": str(raw), "raw": raw}
    try:
        payload = _parse_brain_json_payload(str(raw))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not parse implementation plan: {exc}", "raw": raw}
    payload.setdefault("files", [])
    payload.setdefault("notes", [])
    payload.setdefault("summary", "")
    payload["candidate_files"] = [item["path"] for item in candidate_files]
    payload["execution_hints"] = execution_hints
    return payload


async def _execute_autonomous_code_apply(step: PlanStep, runtime_ctx: dict) -> dict[str, Any]:
    """Apply autonomous implementation changes directly to the repo."""
    user_goal = runtime_ctx["user_goal"]
    deliverable_path = runtime_ctx["contract"].context["deliverable_path"]
    plan = await _generate_autonomous_code_plan(user_goal, runtime_ctx)
    if plan.get("error"):
        return {
            "success": False,
            "error_code": FailureCode.PLANNING_FAIL.value,
            "error": plan["error"],
            "artifacts": [],
            "signals": [],
        }

    proposed_files = plan.get("files") or []
    valid_files = [
        file_entry
        for file_entry in proposed_files
        if isinstance(file_entry, dict)
        and file_entry.get("path")
        and isinstance(file_entry.get("content"), str)
        and _is_allowed_repo_target(str(file_entry["path"]))
    ]
    if not valid_files:
        return {
            "success": False,
            "error_code": FailureCode.PLANNING_FAIL.value,
            "error": "Implementation plan did not produce any safe repo file changes.",
            "artifacts": [],
            "signals": [],
            "raw_plan": plan,
        }

    from core.symbolic_check import SymbolicValidator

    validator = SymbolicValidator(os.getcwd())
    backups_dir = Path(os.getcwd()) / "workspace" / "orchestrator" / "backups" / runtime_ctx["contract"].mission_id
    files_written: list[str] = []
    notes: list[str] = []

    for file_entry in valid_files:
        rel_path = str(file_entry["path"]).strip()
        content = str(file_entry["content"])
        full_path = Path(os.getcwd()) / rel_path
        if not validator.validate(rel_path, content):
            notes.append(f"Blocked by symbolic validation: {rel_path}")
            continue
        if full_path.exists():
            backup_path = backups_dir / rel_path
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_text(full_path.read_text(encoding="utf-8"), encoding="utf-8")
        write_result = file_write_tool(str(full_path), content)
        if str(write_result).startswith("Saved") or str(write_result).startswith("✅"):
            files_written.append(str(full_path.resolve()))
        else:
            notes.append(f"Write failed for {rel_path}: {write_result}")

    summary_lines = [
        "# Autonomous Implementation Report",
        "",
        f"Goal: {user_goal}",
        "",
        f"Summary: {plan.get('summary') or 'No summary provided.'}",
        "",
        "## Changed Files",
    ]
    if files_written:
        summary_lines.extend(f"- {path}" for path in files_written)
    else:
        summary_lines.append("- No files were changed.")
    plan_notes = [str(note) for note in (plan.get("notes") or []) if str(note).strip()]
    summary_lines.extend(["", "## Notes"])
    if plan_notes or notes:
        summary_lines.extend(f"- {note}" for note in [*plan_notes, *notes])
    else:
        summary_lines.append("- None")

    file_write_tool(deliverable_path, "\n".join(summary_lines))
    artifacts = [deliverable_path, *files_written]
    return {
        "success": bool(files_written),
        "verified": bool(files_written),
        "summary": plan.get("summary") or "",
        "artifacts": artifacts,
        "files_written": files_written,
        "signals": ["file_created", "filesystem_modified", "source_changes_applied"]
        if files_written
        else ["file_created"],
        "notes": [*plan_notes, *notes],
        "raw_plan": plan,
    }


def _call_async_blocking(async_fn, *args, **kwargs):
    """Run an async function from sync orchestrator code safely."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_fn(*args, **kwargs))

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _worker():
        try:
            result["value"] = asyncio.run(async_fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001
            error["value"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join()
    if "value" in error:
        raise error["value"]
    return result.get("value")


def _safe_excerpt(value: Any, max_chars: int = 1600) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _keywords_for_memory(user_goal: str, mission_type: str) -> str:
    words = re.findall(r"[A-Za-zĂÂÎȘȚăâîșț0-9_-]+", user_goal.lower())
    shortlist: list[str] = []
    for token in words:
        if len(token) < 3:
            continue
        if token not in shortlist:
            shortlist.append(token)
        if len(shortlist) >= 6:
            break
    if mission_type not in shortlist:
        shortlist.insert(0, mission_type)
    return ", ".join(shortlist[:6])


def _detect_grounding_mode(user_goal: str) -> str:
    lowered = user_goal.lower()
    if re.search(r"https?://\S+", user_goal) or any(
        word in lowered for word in ["browser", "site", "website", "page", "navigate", "url"]
    ):
        return "browser"
    if any(
        word in lowered
        for word in [
            "desktop",
            "screen",
            "app",
            "application",
            "window",
            "click",
            "type",
            "launch",
            "finder",
            "safari",
            "chrome",
            "terminal",
        ]
    ):
        return "desktop"
    return "none"


def _extract_grounding_target(user_goal: str, mode: str) -> str:
    if mode == "browser":
        url_match = re.search(r"https?://\S+", user_goal)
        return url_match.group(0) if url_match else user_goal
    if mode == "desktop":
        match = re.search(
            r"(?:open|launch|application|app)\s+([A-Za-z0-9 ._-]+)",
            user_goal,
            re.IGNORECASE,
        )
        return match.group(1).strip() if match else user_goal
    return ""


def _build_plan_markdown(user_goal: str, runtime_ctx: dict) -> str:
    """Create a deterministic mission plan from the gathered context."""
    mission_type = runtime_ctx["mission_type"]
    memory_context = _safe_excerpt(runtime_ctx["step_outputs"].get("memory_context"), 1200)
    research_context = _safe_excerpt(runtime_ctx["step_outputs"].get("web_research"), 1600)
    anti_repetition = runtime_ctx.get("anti_repetition", "")
    execution_guidance = _safe_excerpt(runtime_ctx.get("execution_guidance"), 1200)
    mission_preflight = runtime_ctx.get("mission_preflight") or {}

    lines = [
        "# Plan de execuție",
        "",
        f"## Obiectiv",
        user_goal,
        "",
        "## Context util",
        memory_context or "Nu există context istoric relevant.",
        "",
        "## Cercetare curentă",
        research_context or "Nu există cercetare externă disponibilă; folosim fallback local.",
        "",
        "## Pași recomandați",
        "1. Confirmă criteriul de succes și rezultatul final așteptat.",
        "2. Execută pasul principal cu tool-ul cel mai sigur disponibil.",
        "3. Observă starea după execuție și verifică dovada produsă.",
        "4. Dacă verificarea eșuează, schimbă tool-ul sau replănuiește local.",
        "5. Salvează un livrabil clar și o lecție pentru misiunile viitoare.",
        "",
        "## Riscuri & mitigări",
        "- Drift de context: recapitulare din memorie înainte de livrare.",
        "- Tool indisponibil: fallback pe tool alternativ sau plan local.",
        "- Succes fabricat: nicio etapă nu este marcată complet fără verificare.",
        "",
        "## Tip misiune",
        mission_type,
    ]
    if mission_preflight:
        mode = mission_preflight.get("execution_mode", "default")
        complexity = mission_preflight.get("complexity_score")
        roles = mission_preflight.get("coordinator_roles") or []
        first_steps = mission_preflight.get("first_steps") or []
        lines.extend(["", "## Mission preflight", f"- Mod recomandat: {mode}"])
        if complexity is not None:
            lines.append(f"- Complexitate estimată: {complexity}")
        if roles:
            lines.append(f"- Roluri coordinator armate: {', '.join(roles)}")
        if first_steps:
            lines.append(f"- Primele mișcări recomandate: {' -> '.join(first_steps)}")
    if execution_guidance:
        lines.extend(["", "## Ghidaj de execuție principal", execution_guidance])
    if anti_repetition:
        lines.extend(["", "## Anti-repetition guard", anti_repetition])
    return "\n".join(lines).strip()


def _extract_markdown_section_lines(text: str, heading: str) -> list[str]:
    if not text:
        return []

    pattern = rf"^## {re.escape(heading)}\s*$"
    lines = text.splitlines()
    collecting = False
    section_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if re.match(pattern, stripped):
            collecting = True
            continue
        if collecting and stripped.startswith("## "):
            break
        if collecting and stripped:
            section_lines.append(stripped)

    return section_lines


def _extract_markdown_bullets(text: str, heading: str) -> list[str]:
    return [
        line[2:].strip()
        for line in _extract_markdown_section_lines(text, heading)
        if line.startswith("- ")
    ]


def _extract_audit_metric(text: str, label: str) -> int | None:
    match = re.search(rf"- {re.escape(label)}:\s*(\d+)", text or "")
    if not match:
        return None
    return int(match.group(1))


def _build_code_audit_deliverable_content(contract: TaskContract, runtime_ctx: dict) -> str:
    audit_context = _safe_excerpt(runtime_ctx["step_outputs"].get("web_research"), 6000)
    memory_context = _safe_excerpt(runtime_ctx["step_outputs"].get("memory_context"), 1200)
    plan_context = _safe_excerpt(runtime_ctx["step_outputs"].get("execution_plan"), 2000)
    qa_text = _safe_excerpt(runtime_ctx.get("qa_text", ""), 1200)

    files_scanned = _extract_audit_metric(audit_context, "Files scanned")
    total_source_lines = _extract_audit_metric(audit_context, "Total source lines")
    hotspots = _extract_markdown_bullets(audit_context, "Hotspots")
    heuristic_findings = _extract_markdown_bullets(audit_context, "Heuristic Findings")
    todo_signals = _extract_markdown_bullets(audit_context, "TODO / FIXME Signals")

    p1_findings: list[str] = []
    p2_findings: list[str] = []
    p3_findings: list[str] = []

    if (files_scanned or 0) == 0 or (total_source_lines or 0) == 0:
        p1_findings.append(
            "Audit snapshot-ul nu a reușit să scaneze fișiere relevante; verifică excluderile, cwd-ul și accesul la workspace."
        )

    if hotspots:
        priority_hotspots = hotspots[:3]
        p2_findings.append(
            "Revizuiește mai întâi fișierele cu suprafață mare de risc: "
            + ", ".join(priority_hotspots)
            + "."
        )

    p2_findings.extend(heuristic_findings[:4])

    if todo_signals and not (len(todo_signals) == 1 and todo_signals[0].startswith("No TODO/FIXME")):
        p3_findings.extend(todo_signals[:5])
    else:
        p3_findings.append("Nu există semnale TODO/FIXME urgente în fișierele scanate.")

    if not p1_findings:
        p1_findings.append("Nu am detectat blocaje critice în acest audit.")
    if not p2_findings:
        p2_findings.append("Nu am detectat riscuri structurale majore în acest audit.")

    return "\n".join(
        [
            "# Code Audit Report",
            "",
            f"- Mission ID: `{contract.mission_id}`",
            f"- Generated at: `{datetime.now().isoformat()}`",
            "",
            "## Audit Scope",
            contract.user_input,
            "",
            "## Delivery Snapshot",
            f"- Files scanned: {files_scanned or 0}",
            f"- Total source lines: {total_source_lines or 0}",
            "",
            "## Files To Review First",
            *([f"- {item}" for item in hotspots[:6]] or ["- No hotspots detected."]),
            "",
            "## Findings by Severity",
            "### P1 Critical blockers",
            *[f"- {item}" for item in p1_findings],
            "",
            "### P2 Delivery / structural risks",
            *[f"- {item}" for item in p2_findings],
            "",
            "### P3 Follow-up / cleanup",
            *[f"- {item}" for item in p3_findings],
            "",
            "## Historical Context",
            memory_context or "No relevant historical context found.",
            "",
            "## Review Plan",
            plan_context or "Audit plan unavailable.",
            "",
            "## Raw Repository Snapshot",
            audit_context or "Audit snapshot unavailable.",
            "",
            "## Quality Review",
            qa_text or "Quality review will be appended after verification.",
        ]
    ).strip()


def _build_deliverable_content(contract: TaskContract, runtime_ctx: dict) -> str:
    """Compose a concrete deliverable file from accumulated step outputs."""
    if runtime_ctx.get("audit_mode") == "code_review" or contract.context.get("audit_mode") == "code_review":
        return _build_code_audit_deliverable_content(contract, runtime_ctx)

    memory_context = _safe_excerpt(runtime_ctx["step_outputs"].get("memory_context"), 1200)
    research_context = _safe_excerpt(runtime_ctx["step_outputs"].get("web_research"), 2000)
    plan_context = _safe_excerpt(runtime_ctx["step_outputs"].get("execution_plan"), 2200)
    coordinator_context = _safe_excerpt(runtime_ctx["step_outputs"].get("coordinator_execution"), 2600)
    ultraplan_context = _safe_excerpt(runtime_ctx.get("ultraplan_bundle"), 2600)
    mission_type = runtime_ctx["mission_type"]
    mission_preflight = runtime_ctx.get("mission_preflight") or contract.context.get("mission_preflight") or {}
    execution_guidance = _safe_excerpt(runtime_ctx.get("execution_guidance"), 1200)

    return "\n".join(
        [
            f"# JARVIS Deliverable",
            "",
            f"- Mission ID: `{contract.mission_id}`",
            f"- Mission type: `{mission_type}`",
            f"- Generated at: `{datetime.now().isoformat()}`",
            "",
            "## User Goal",
            contract.user_input,
            "",
            "## Memory Context",
            memory_context or "No memory context available.",
            "",
            "## Web / External Context",
            research_context or "No external context available.",
            "",
            "## Execution Plan",
            plan_context or "Plan synthesis unavailable.",
            "",
            "## UltraPlan Output",
            ultraplan_context or "No UltraPlan output was produced.",
            "",
            "## Mission Preflight",
            json.dumps(mission_preflight, ensure_ascii=False, indent=2)
            if mission_preflight
            else "No mission preflight available.",
            "",
            "## Coordinator / Agent Execution",
            coordinator_context or "No coordinator execution was required.",
            "",
            "## Principal Execution Guidance",
            execution_guidance or "No explicit principal guidance was supplied.",
            "",
            "## Delivery Notes",
            "This file was produced through the orchestrator step loop with risk gating, observation, verification, and repair hooks.",
        ]
    ).strip()


def _build_quality_review(contract: TaskContract, results: list[dict]) -> str:
    verified_steps = sum(
        1
        for item in results
        if isinstance(item.get("verification"), dict)
        and item["verification"].get("verified")
    )
    total_steps = max(1, len(results))
    score = max(1, round((verified_steps / total_steps) * 10))
    failure_reasons = [
        item["verification"].get("mismatch_reason")
        for item in results
        if isinstance(item.get("verification"), dict)
        and not item["verification"].get("verified")
    ]
    if failure_reasons:
        notes = "; ".join(reason for reason in failure_reasons if reason)
    else:
        notes = "Livrabilul a trecut verificările etapei curente."

    return "\n".join(
        [
            "EVALUARE CALITATE:",
            f"Completitudine: {score}/10",
            f"Acuratețe: {score}/10",
            f"Structură: {score}/10",
            f"Detaliu: {max(1, score - 1)}/10",
            f"Utilizabilitate: {score}/10",
            f"SCOR TOTAL: {score}/10",
            f"NOTE: {notes}",
        ]
    )


@tool("workspace_code_audit")
def workspace_code_audit_tool(query: str = "") -> str:
    """Build a deterministic read-only audit snapshot of the current workspace."""
    root = Path(os.getcwd())
    ignored_dirs = IMPLEMENTATION_EXCLUDED_PARTS | {".agent", ".git", "node_modules", ".next"}
    tracked_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".scss", ".md"}

    def _should_ignore_path_parts(parts: tuple[str, ...]) -> bool:
        for part in parts:
            lowered = part.lower()
            if lowered in ignored_dirs:
                return True
            if lowered.startswith(".venv") or lowered.startswith(".next"):
                return True
            if lowered in {"site-packages", "dist-packages", "build", "coverage"}:
                return True
        return False

    total_files = 0
    total_lines = 0
    todo_hits: list[str] = []
    hotspot_files: list[tuple[int, str]] = []

    for current_root, dirs, files in os.walk(root):
        rel_root = Path(current_root).relative_to(root)
        dirs[:] = [
            entry
            for entry in dirs
            if not _should_ignore_path_parts(tuple(rel_root.parts + (entry,)))
        ]
        if _should_ignore_path_parts(rel_root.parts):
            continue

        for file_name in files:
            path = Path(current_root) / file_name
            if path.suffix.lower() not in tracked_exts:
                continue
            if _should_ignore_path_parts(path.relative_to(root).parts):
                continue

            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue

            total_files += 1
            lines = text.splitlines()
            total_lines += len(lines)
            hotspot_files.append((len(lines), str(path.relative_to(root))))

            lowered = text.lower()
            if "todo" in lowered or "fixme" in lowered:
                todo_count = lowered.count("todo") + lowered.count("fixme")
                todo_hits.append(f"- {path.relative_to(root)}: {todo_count} TODO/FIXME marker(s)")

    hotspot_files.sort(reverse=True)
    hotspots = hotspot_files[:8]

    heuristic_findings: list[str] = []
    page_path = root / "nucleus_ui" / "app" / "page.tsx"
    if page_path.exists():
        try:
            page_lines = len(page_path.read_text(encoding="utf-8").splitlines())
            if page_lines > 1800:
                heuristic_findings.append(
                    f"- nucleus_ui/app/page.tsx este foarte mare ({page_lines} linii) și merită decompoziție."
                )
        except Exception:
            pass

    bridge_path = root / "bridge" / "nucleus_bridge.py"
    if bridge_path.exists():
        try:
            bridge_text = bridge_path.read_text(encoding="utf-8")
            if "@app.on_event(" in bridge_text:
                heuristic_findings.append(
                    "- bridge/nucleus_bridge.py folosește FastAPI on_event; există debt de migrare la lifespan handlers."
                )
        except Exception:
            pass

    lines = [
        "## Repository Audit Snapshot",
        f"- Scope query: {query or 'general workspace audit'}",
        f"- Files scanned: {total_files}",
        f"- Total source lines: {total_lines}",
        "",
        "## Hotspots",
    ]

    if hotspots:
        lines.extend([f"- {rel_path}: {count} lines" for count, rel_path in hotspots])
    else:
        lines.append("- No hotspots detected.")

    lines.extend(["", "## Heuristic Findings"])
    if heuristic_findings:
        lines.extend(heuristic_findings)
    else:
        lines.append("- No obvious structural heuristic findings detected.")

    lines.extend(["", "## TODO / FIXME Signals"])
    if todo_hits:
        lines.extend(todo_hits[:12])
    else:
        lines.append("- No TODO/FIXME markers detected in scanned files.")

    return "\n".join(lines).strip()


def build_mission_contract(user_input: str, context: dict) -> TaskContract:
    """Create the blueprint-aligned mission contract used by the step loop."""
    mission_type = context["mission_type"]
    contract = create_mission(user_input, context=context)
    deliverable_path = str(_mission_workspace(contract.mission_id))
    contract.context["deliverable_path"] = deliverable_path
    memory_consolidation = get_memory_consolidation()
    episodic = _episodic_memory()
    context_graph = get_context_graph()
    autonomous_protocol = "[misiune autonomă]" in user_input.lower()
    audit_mode = "code_review" if _looks_like_code_audit_request(user_input) else ""
    mission_preflight = context.get("mission_preflight") or {}
    execution_mode = mission_preflight.get("execution_mode", "default")
    coordinator_roles = list(mission_preflight.get("coordinator_roles") or [])
    coordinator_task_specs = list(mission_preflight.get("coordinator_task_specs") or [])
    first_steps = list(mission_preflight.get("first_steps") or [])

    context_graph.update_task(user_input)
    context_graph.set_active_goal(user_input)
    implementation_required = (
        _looks_like_implementation_request(user_input) or mission_type == "code"
    ) and not bool(audit_mode)
    grounding_mode = _detect_grounding_mode(user_input)
    grounding_target = _extract_grounding_target(user_input, grounding_mode)

    task_ctx = {
        "mission_type": mission_type,
        "task": user_input,
        "user_goal": user_input,
        "search_query": user_input,
        "tags": context.get("tags", []),
        "grounding_mode": grounding_mode,
    }
    execution_biases = memory_consolidation.get_execution_biases(task_ctx)
    similar_failures = episodic.find_similar_failures(task_ctx)
    best_known_strategy = episodic.get_best_known_strategy(task_ctx)

    memory_step = PlanStep(
        id="memory_context",
        title="Review memory context",
        description="Collect relevant memory, lessons, and vault notes before execution.",
        tool_candidates=["memory_search", "memory_summary", "obsidian_search"],
        success_criteria=SuccessCriteria(
            description="Relevant historical context was gathered.",
            observable_signals=["memory_updated"],
        ),
        risk=TaskRisk.R0,
    )
    research_step = PlanStep(
        id="web_research",
        title="Collect fresh context",
        description="Gather up-to-date external context for the mission.",
        tool_candidates=["browser_search", "memory_summary"],
        success_criteria=SuccessCriteria(
            description="Fresh context or a validated local fallback was gathered.",
            observable_signals=["action_completed"],
        ),
        risk=TaskRisk.R0,
    )
    plan_step = PlanStep(
        id="execution_plan",
        title="Synthesize execution plan",
        description="Build a concrete plan with risks, mitigations, and deliverable criteria.",
        tool_candidates=["compact_context"],
        success_criteria=SuccessCriteria(
            description="Execution plan synthesized with concrete next steps.",
            observable_signals=["action_completed"],
        ),
        risk=TaskRisk.R0,
        dependencies=["memory_context", "web_research"],
    )
    deliverable_step = PlanStep(
        id="deliverable_write",
        title="Write deliverable artifact",
        description="Persist a concrete deliverable to disk for the mission.",
        tool_candidates=["file_write"],
        success_criteria=SuccessCriteria(
            description="Deliverable was written and can be verified on disk.",
            observable_signals=["file_created"],
            required_artifacts=[deliverable_path],
            verification_method="artifact_exists",
        ),
        risk=TaskRisk.R1,
        dependencies=["execution_plan"],
    )
    qa_step = PlanStep(
        id="quality_review",
        title="Review and save lesson",
        description="Review mission quality and save a lesson for future runs.",
        tool_candidates=["save_lesson", "compact_context"],
        success_criteria=SuccessCriteria(
            description="Quality review completed and lesson persisted.",
            observable_signals=["memory_written"],
        ),
        risk=TaskRisk.R1,
        dependencies=["deliverable_write"],
    )
    coordinator_step = PlanStep(
        id="coordinator_execution",
        title="Coordinate specialized agents",
        description="Run coordinator mode to decompose the task and execute role-based specialist work before final delivery.",
        tool_candidates=["coordinator_execute"],
        success_criteria=SuccessCriteria(
            description="Coordinator mode executed specialist subtasks and produced a structured execution summary.",
            observable_signals=["action_completed"],
        ),
        risk=TaskRisk.R1,
        dependencies=["execution_plan"],
    )

    if grounding_mode == "browser":
        research_step.title = "Ground browser context"
        research_step.description = (
            "Open the relevant page, capture semantic state, and verify browser changes."
        )
        research_step.tool_candidates = [
            "browser_task",
            "browser_structured_extract",
            "browser_search",
            "memory_summary",
        ]
        research_step.success_criteria.observable_signals = [
            "semantic_state_captured",
            "page_ready",
        ]
        research_step.success_criteria.verification_method = "state_changed"
        research_step.risk = TaskRisk.R2

    elif grounding_mode == "desktop":
        research_step.title = "Ground desktop context"
        research_step.description = (
            "Observe desktop state, interact with the target app when needed, and verify screen changes."
        )
        research_step.tool_candidates = [
            "computer_task",
            "computer_observe_screen",
            "memory_summary",
        ]
        research_step.success_criteria.observable_signals = [
            "desktop_observed",
            "screen_captured",
        ]
        research_step.success_criteria.verification_method = "state_changed"
        research_step.risk = TaskRisk.R2

    if audit_mode == "code_review":
        research_step.title = "Inspect repository state"
        research_step.description = (
            "Build a read-only audit snapshot of the current workspace and identify code hotspots."
        )
        research_step.tool_candidates = ["workspace_code_audit"]
        research_step.success_criteria.description = (
            "A deterministic repository audit snapshot and hotspot list were produced."
        )
        research_step.success_criteria.observable_signals = ["action_completed"]
        research_step.success_criteria.verification_method = "contains"
        research_step.risk = TaskRisk.R0
        plan_step.title = "Synthesize audit findings"
        plan_step.description = (
            "Turn the repository snapshot into prioritized code audit findings and next steps."
        )
        deliverable_step.title = "Write audit report"
        deliverable_step.description = (
            "Persist a structured code audit report with findings, hotspots, and recommendations."
        )
        deliverable_step.success_criteria.description = (
            "Audit report was written and can be verified on disk."
        )

    if implementation_required:
        plan_step.description = (
            f"{plan_step.description} [Implementation mission: success requires real source changes in the project, not just a report.]"
        )
        deliverable_step.title = "Apply source changes"
        deliverable_step.description = (
            "Apply concrete source changes or capture verified implementation evidence; a workspace report alone does not count."
        )
        deliverable_step.success_criteria.description = (
            "Implementation evidence includes real project artifacts beyond the orchestrator workspace."
        )
        deliverable_step.success_criteria.observable_signals = ["file_created", "file_modified"]
        deliverable_step.tool_candidates = ["autonomous_code_apply"]

    if execution_mode == "ultraplan":
        plan_step.title = "Build deep execution plan"
        plan_step.description = (
            f"{plan_step.description} [ULTRAPLAN mode armed for deeper sequencing and checkpointing.]"
        )
        plan_step.tool_candidates = ["ultraplan", "compact_context"]

    if execution_mode == "coordinator":
        plan_step.title = "Build coordinated execution plan"
        plan_step.description = (
            f"{plan_step.description} [Coordinator mode armed for specialist delegation and review.]"
        )
        plan_step.tool_candidates = ["ultraplan", "compact_context"]
        if coordinator_roles:
            coordinator_step.description = (
                f"{coordinator_step.description} Armed roles: {', '.join(coordinator_roles)}."
            )
        if coordinator_task_specs:
            coordinator_step.description = (
                f"{coordinator_step.description} Prepared task specs: {len(coordinator_task_specs)}."
            )
        deliverable_step.dependencies = ["coordinator_execution"]

    if first_steps:
        plan_step.description = (
            f"{plan_step.description} [Preflight first steps: {' -> '.join(first_steps)}]"
        )

    contract.steps = [memory_step, research_step, plan_step]
    if execution_mode == "coordinator":
        contract.steps.append(coordinator_step)
    contract.steps.extend([deliverable_step, qa_step])
    if best_known_strategy:
        plan_step.description = (
            f"{plan_step.description} [Best known strategy: {best_known_strategy['strategy']}]"
        )
    memory_consolidation.apply_memory_biases_to_plan(contract.steps, execution_biases)
    contract.context["execution_biases"] = [memory.to_dict() for memory in execution_biases]
    contract.context["similar_failures"] = similar_failures
    contract.context["best_known_strategy"] = best_known_strategy
    contract.context["world_state"] = context_graph.get_world_state()
    contract.context["grounding_mode"] = grounding_mode
    contract.context["grounding_target"] = grounding_target
    contract.context["audit_mode"] = audit_mode
    contract.context["mission_preflight"] = mission_preflight
    contract.context["execution_mode"] = execution_mode
    contract.context["coordinator_roles"] = coordinator_roles
    contract.context["coordinator_task_specs"] = coordinator_task_specs
    contract.context["requires_real_source_changes"] = implementation_required
    contract.context["delivery_mode"] = (
        "source_changes"
        if implementation_required
        else "audit_report"
        if audit_mode
        else "document"
    )
    contract.context["autonomous_protocol"] = autonomous_protocol
    contract.overall_risk = max(
        (step.risk for step in contract.steps),
        key=lambda item: {"R0": 0, "R1": 1, "R2": 2, "R3": 3}[item.value],
    )
    contract.requires_approval = any(step.risk in {TaskRisk.R2, TaskRisk.R3} for step in contract.steps)
    contract.status = TaskStatus.PLANNING
    return contract


async def _execute_grounded_browser_tool(
    tool_name: str, step: PlanStep, runtime_ctx: dict
) -> Dict[str, Any]:
    from tools.browser_agent import get_browser_agent

    agent = get_browser_agent()
    query = runtime_ctx["search_query"]
    grounding_target = runtime_ctx["contract"].context.get("grounding_target") or query

    if tool_name == "browser_search":
        return await agent.search_web(query)
    if tool_name == "browser_structured_extract":
        schema = {
            "title": {"type": "string"},
            "url": {"type": "string"},
            "summary": {"type": "string"},
            "primary_actions": {"type": "array"},
        }
        return await agent.extract_structured_page_data(
            schema,
            url=grounding_target if grounding_target.startswith("http") else None,
        )
    if tool_name == "browser_subtask":
        subtask = runtime_ctx.get("browser_subtask") or {
            "action": "extract",
            "url": grounding_target if grounding_target.startswith("http") else None,
            "goal": query,
            "task": query,
        }
        return await agent.run_browser_subtask(subtask)
    success_criteria = {
        "goal": query,
        "schema": runtime_ctx.get("browser_schema"),
    }
    return await agent.execute_browser_task(grounding_target, success_criteria)


async def _execute_grounded_computer_tool(
    tool_name: str, runtime_ctx: dict
) -> Dict[str, Any]:
    from core.computer_use_agent import ComputerUseAgent

    agent = runtime_ctx.setdefault("_computer_agent", ComputerUseAgent())
    target = runtime_ctx["contract"].context.get("grounding_target") or runtime_ctx["user_goal"]

    if tool_name == "computer_observe_screen":
        return await agent.observe_screen()
    if tool_name == "computer_open_app":
        return await agent.open_app_verified(target)
    if tool_name == "computer_click_target":
        return await agent.click_screen_target(target)
    if tool_name == "computer_type_verified":
        text = runtime_ctx.get("computer_text") or runtime_ctx["user_goal"]
        return await agent.type_text_verified(text, target)
    if tool_name == "computer_assert_change":
        signal = runtime_ctx.get("expected_signal", "screen_changed")
        return await agent.assert_screen_change(signal)
    return await agent.execute_task(runtime_ctx["user_goal"])


def _grounded_observation_payload(raw_output: Any, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw_output, dict):
        return fallback

    payload = dict(fallback)
    after_state = raw_output.get("after") or raw_output.get("state") or {}
    before_state = raw_output.get("before") or {}
    if after_state:
        payload["after"] = after_state
    if before_state:
        payload["before"] = before_state
    if raw_output.get("signals"):
        payload["signals"] = list(raw_output.get("signals", []))
    if raw_output.get("verified") is not None:
        payload["verified"] = bool(raw_output.get("verified"))
    if raw_output.get("url"):
        payload.setdefault("url", raw_output.get("url"))
    if raw_output.get("title"):
        payload.setdefault("title", raw_output.get("title"))
    if raw_output.get("browser_dom_hash"):
        payload.setdefault("browser_dom_hash", raw_output.get("browser_dom_hash"))
    return payload


def _execute_step_tool(step: PlanStep, tool_name: str, runtime_ctx: dict) -> tuple[ExecutionResult, str, dict]:
    """Execute the concrete tool or fallback operation for a step."""
    result = ExecutionResult(
        step_id=step.id,
        tool_name=tool_name,
        raw_output=None,
        retry_count=step.retry_count,
    )
    mission_type = runtime_ctx["mission_type"]
    query = runtime_ctx["search_query"]
    observation_type = tool_name
    observation_params: dict[str, Any] = {}

    if tool_name == "memory_search":
        raw_output = search_memory_tool(_keywords_for_memory(query, mission_type))
        ok = True
        observation_type = "memory_search"
        observation_params = {"memory_id": f"{step.id}:{mission_type}"}
    elif tool_name == "memory_summary":
        raw_output = memory_summary_tool()
        ok = True
        observation_type = "memory_search"
        observation_params = {"memory_id": f"summary:{mission_type}"}
    elif tool_name == "obsidian_search":
        raw_output = obsidian_search_tool(query)
        ok = not str(raw_output).lower().startswith("nu s-au găsit")
        observation_type = "memory_search"
        observation_params = {"memory_id": f"vault:{mission_type}"}
    elif tool_name == "browser_search":
        try:
            raw_output = _call_async_blocking(
                _execute_grounded_browser_tool, tool_name, step, runtime_ctx
            )
            ok = bool(raw_output.get("success", False))
            if not ok:
                result.error_code = raw_output.get("error_code") or FailureCode.TOOL_NOT_AVAILABLE.value
            observation_type = "browser_search"
            observation_params = _grounded_observation_payload(
                raw_output,
                {
                    "url": raw_output.get("url", "search://browser"),
                    "title": raw_output.get("title", f"Search results for {query}"),
                    "signals": ["semantic_state_captured"] if ok else [],
                },
            )
        except Exception:
            raw_output = duckduckgo_tool(query)
            lowered = str(raw_output).lower()
            ok = "unavailable" not in lowered and "no results" not in lowered
            if not ok:
                result.error_code = FailureCode.TOOL_NOT_AVAILABLE.value
            observation_type = "browser_search"
            observation_params = {
                "url": "search://duckduckgo",
                "title": f"Search results for {query}",
            }
    elif tool_name == "workspace_code_audit":
        raw_output = workspace_code_audit_tool(query)
        ok = bool(str(raw_output).strip())
        observation_type = "memory_search"
        observation_params = {"memory_id": f"audit:{mission_type}"}
    elif tool_name == "ultraplan":
        try:
            engine = get_jarvis()
            raw_output = _call_async_blocking(
                engine.mcp.call_tool,
                "ultraplan",
                {
                    "task": runtime_ctx["user_goal"],
                    "context": runtime_ctx.get("execution_guidance", ""),
                },
            )
            runtime_ctx["ultraplan_bundle"] = raw_output
            ok = isinstance(raw_output, dict) and bool(raw_output.get("steps"))
            if not ok:
                result.error_code = FailureCode.PLANNING_FAIL.value
            observation_type = "plan_synthesis"
            observation_params = {"signals": ["action_completed"]}
        except Exception as exc:
            raw_output = {"error": str(exc)}
            ok = False
            result.error_code = FailureCode.PLANNING_FAIL.value
            observation_type = "plan_synthesis"
            observation_params = {"signals": []}
    elif tool_name == "coordinator_execute":
        try:
            engine = get_jarvis()
            raw_output = _call_async_blocking(
                engine.mcp.call_tool,
                "coordinator_execute",
                {"task": runtime_ctx["user_goal"]},
            )
            runtime_ctx["coordinator_execution"] = raw_output
            ok = isinstance(raw_output, dict) and bool(raw_output.get("success"))
            if not ok:
                result.error_code = FailureCode.TOOL_RUNTIME_ERROR.value
            observation_type = "action_completed"
            observation_params = {"signals": ["action_completed"]}
        except Exception as exc:
            raw_output = {"error": str(exc)}
            runtime_ctx["coordinator_execution"] = raw_output
            ok = False
            result.error_code = FailureCode.TOOL_RUNTIME_ERROR.value
            observation_type = "action_completed"
            observation_params = {"signals": []}
    elif tool_name in {"browser_task", "browser_structured_extract", "browser_subtask"}:
        raw_output = _call_async_blocking(
            _execute_grounded_browser_tool, tool_name, step, runtime_ctx
        )
        ok = bool(raw_output.get("success", False))
        if not ok:
            result.error_code = raw_output.get("error_code") or FailureCode.TOOL_RUNTIME_ERROR.value
        observation_type = (
            "browser_navigate"
            if tool_name == "browser_task"
            else "browser_click_verified"
            if tool_name == "browser_subtask"
            else "browser_search"
        )
        observation_params = _grounded_observation_payload(
            raw_output,
            {
                "url": raw_output.get("url", ""),
                "title": raw_output.get("title", ""),
                "signals": list(raw_output.get("signals", [])),
            },
        )
    elif tool_name == "compact_context":
        if step.id == "execution_plan":
            raw_output = _build_plan_markdown(runtime_ctx["user_goal"], runtime_ctx)
            runtime_ctx["deliverable_content"] = _build_deliverable_content(
                runtime_ctx["contract"], runtime_ctx
            )
        else:
            raw_output = compact_context_tool(
                runtime_ctx["step_outputs"].get("deliverable_write", "")
            )
        ok = bool(str(raw_output).strip())
        observation_type = "plan_synthesis"
        observation_params = {"signals": ["action_completed"]}
    elif tool_name == "file_write":
        path = runtime_ctx["contract"].context["deliverable_path"]
        content = runtime_ctx.get("deliverable_content") or _build_deliverable_content(
            runtime_ctx["contract"], runtime_ctx
        )
        raw_output = file_write_tool(path, content)
        ok = str(raw_output).startswith("Saved") or str(raw_output).startswith("✅")
        result.artifacts = [path]
        observation_type = "file_write"
        observation_params = {"filename": path}
    elif tool_name == "autonomous_code_apply":
        raw_output = _call_async_blocking(
            _execute_autonomous_code_apply, step, runtime_ctx
        )
        ok = bool(raw_output.get("success", False))
        if not ok:
            result.error_code = raw_output.get("error_code") or FailureCode.TOOL_RUNTIME_ERROR.value
        result.artifacts = list(raw_output.get("artifacts", []))
        observation_type = "file_write"
        observation_params = {
            "filename": runtime_ctx["contract"].context["deliverable_path"],
        }
    elif tool_name == "save_lesson":
        qa_text = _build_quality_review(runtime_ctx["contract"], runtime_ctx["results"])
        runtime_ctx["qa_text"] = qa_text
        raw_output = save_lesson_tool(
            lesson=f"{runtime_ctx['mission_type']}: {_safe_excerpt(qa_text, 180)}",
            category=runtime_ctx["mission_type"],
            severity="info",
        )
        ok = str(raw_output).startswith("✅")
        observation_type = "memory_write"
        observation_params = {"memory_id": f"lesson:{runtime_ctx['contract'].mission_id}"}
    elif tool_name in {
        "computer_task",
        "computer_observe_screen",
        "computer_open_app",
        "computer_click_target",
        "computer_type_verified",
        "computer_assert_change",
    }:
        raw_output = _call_async_blocking(
            _execute_grounded_computer_tool, tool_name, runtime_ctx
        )
        ok = bool(raw_output.get("success", False))
        if not ok:
            result.error_code = raw_output.get("error_code") or FailureCode.TOOL_RUNTIME_ERROR.value
        observation_type = (
            "observe_screen"
            if tool_name == "computer_observe_screen"
            else "open_app_verified"
            if tool_name == "computer_open_app"
            else "click_screen_target"
            if tool_name == "computer_click_target"
            else "type_text_verified"
            if tool_name == "computer_type_verified"
            else "observe_screen"
        )
        observation_params = _grounded_observation_payload(
            raw_output,
            {
                "screen_state": raw_output.get("after") or raw_output,
                "signals": list(raw_output.get("signals", [])),
            },
        )
    else:
        raw_output = f"Tool {tool_name} is not wired in the orchestrator pipeline."
        ok = False
        result.error_code = FailureCode.TOOL_NOT_AVAILABLE.value
        observation_type = "action_completed"

    result.raw_output = raw_output
    result.metadata["step_title"] = step.title
    if not ok and not result.error_code:
        result.error_code = FailureCode.TOOL_RUNTIME_ERROR.value
    result.mark_complete(ok, None if ok else _safe_excerpt(raw_output, 200))
    result.metadata["tool_response"] = normalize_tool_response(
        tool_name=tool_name,
        result=raw_output,
        success=ok,
        error_code=result.error_code,
        error_message=result.error_message,
        observed_signals=observation_params.get("signals", []),
        artifacts=result.artifacts,
        metadata={"step_id": step.id, "step_title": step.title},
    )
    return result, observation_type, observation_params


def handle_step_failure(step: PlanStep, failure_ctx: dict) -> dict:
    """Apply repair logic after a failed or unverified step."""
    state: StateManager = failure_ctx["state_manager"]
    metrics: MetricsCollector = failure_ctx["metrics"]
    result: ExecutionResult = failure_ctx["result"]
    verification: VerificationResult | None = failure_ctx.get("verification")

    repair = state.repair_engine.choose_repair_action(step, result, verification)
    applied = state.repair_engine.apply_repair(repair, step, failure_ctx)

    if repair.action.value == "replan":
        metrics.record_replan()
    if repair.failure_code:
        metrics.record_failure(repair.failure_code)
        state.record_failure({"code": repair.failure_code, "reason": repair.reason})
    if verification and verification.mismatch_reason and "hallucination" in verification.mismatch_reason.lower():
        metrics.record_hallucination()

    applied["repair_action"] = repair.action.value
    applied["repair_reason"] = repair.reason
    return applied


def execute_step_pipeline(step: PlanStep, runtime_ctx: dict) -> dict:
    """Run risk -> execute -> observe -> verify -> repair for one step."""
    state: StateManager = runtime_ctx["state_manager"]
    metrics: MetricsCollector = runtime_ctx["metrics"]
    contract: TaskContract = runtime_ctx["contract"]
    context_graph = get_context_graph()

    while True:
        contract.current_step_index = runtime_ctx["step_order"][step.id]
        step.status = TaskStatus.EXECUTING

        state.transition_to(MissionState.RISK_REVIEW, f"Risk check for {step.id}")
        assessment = state.risk_engine.classify_step_risk(step)
        step.risk = assessment.risk_level
        policy = state.risk_engine.enforce_policy(step, runtime_ctx)
        if not policy.get("allowed"):
            metrics.record_failure(FailureCode.RISK_POLICY_BLOCK.value)
            state.record_failure(
                {
                    "code": FailureCode.RISK_POLICY_BLOCK.value,
                    "reason": policy.get("reason"),
                    "step_id": step.id,
                }
            )
            if policy.get("approval_required"):
                metrics.record_approval(False)
                state.enter_waiting_approval(step.id, policy.get("risk_level", "unknown"))
                step.status = TaskStatus.WAITING_APPROVAL
            else:
                step.status = TaskStatus.BLOCKED
            return {
                "step_id": step.id,
                "result": None,
                "verification": None,
                "policy": policy,
                "verified": False,
                "terminal_failure": True,
            }

        tool_name = step.tool_candidates[0]

        # ── Neuro: routing_adapter override (only when mode=on) ──
        _neuro_rt = _get_neuro()
        if _neuro_rt and _neuro_rt.active and len(step.tool_candidates) > 1:
            try:
                ctx_class = runtime_ctx.get("neuro_ctx_class", "general")
                best = _neuro_rt.router.best_route(ctx_class, step.tool_candidates)
                if best != tool_name:
                    logger.info(f"[NeuroBrain] Router override: {tool_name} → {best}")
                    tool_name = best
            except Exception:
                pass
        # ── End routing override ──────────────────────────────────

        context_graph.record_tool_edge(tool_name, "attempt")
        state.transition_to(MissionState.EXECUTING_STEP, f"{step.id} via {tool_name}")
        metrics.record_tool_call()
        result, action_type, action_params = _execute_step_tool(step, tool_name, runtime_ctx)

        state.enter_observing(step.id)
        snapshot = state.observe_action(
            action_type,
            action_params,
            step_id=step.id,
            session_id=contract.mission_id,
        )
        result.observed_signals = list(snapshot.signals)

        state.enter_verifying(step.id)
        verification = state.verify_result(result)
        verified = bool(verification.verified)
        metrics.record_step(verified=verified, is_retry=step.retry_count > 0)

        serialized_result = {
            "step_id": step.id,
            "tool_name": result.tool_name,
            "raw_output": _safe_excerpt(result.raw_output, 3000),
            "status": result.status.value,
            "artifacts": list(result.artifacts),
            "error_code": result.error_code,
        }
        serialized_verification = {
            "verified": verification.verified,
            "confidence": verification.confidence.value,
            "evidence": list(verification.evidence),
            "mismatch_reason": verification.mismatch_reason,
            "recommended_action": verification.recommended_action,
        }

        runtime_ctx["step_outputs"][step.id] = serialized_result["raw_output"]
        runtime_ctx["results"].append(
            {
                "step": step.title,
                "result": serialized_result,
                "verification": serialized_verification,
            }
        )
        context_graph.record_tool_edge(
            tool_name,
            "success" if verified else result.error_code or "verification_failed",
        )
        if result.error_code:
            context_graph.record_failure_edge(step.id, result.error_code)

        if verified:
            contract.mark_step_complete(step.id, result, verification)
            return {
                "step_id": step.id,
                "result": serialized_result,
                "verification": serialized_verification,
                "policy": policy,
                "verified": True,
                "terminal_failure": False,
            }

        state.transition_to(MissionState.REPAIRING, f"Repairing {step.id}")
        repair_outcome = handle_step_failure(
            step,
            {
                "state_manager": state,
                "metrics": metrics,
                "result": result,
                "verification": verification,
                "runtime_ctx": runtime_ctx,
            },
        )
        if repair_outcome.get("retry") and repair_outcome.get("new_step"):
            step = repair_outcome["new_step"]
            if repair_outcome.get("replan"):
                metrics.record_replan()
            continue

        if repair_outcome.get("replan"):
            step.status = TaskStatus.FAILED
            return {
                "step_id": step.id,
                "result": serialized_result,
                "verification": serialized_verification,
                "policy": policy,
                "verified": False,
                "terminal_failure": True,
                "repair": repair_outcome,
            }

        if repair_outcome.get("escalate") or repair_outcome.get("abort"):
            step.status = TaskStatus.BLOCKED
            return {
                "step_id": step.id,
                "result": serialized_result,
                "verification": serialized_verification,
                "policy": policy,
                "verified": False,
                "terminal_failure": True,
                "repair": repair_outcome,
            }

        return {
            "step_id": step.id,
            "result": serialized_result,
            "verification": serialized_verification,
            "policy": policy,
            "verified": False,
            "terminal_failure": True,
            "repair": repair_outcome,
        }


def finalize_mission(mission_id: str, results: list[dict], runtime_ctx: dict) -> dict:
    """Finalize mission state, metrics, memory writeback, and output."""
    contract: TaskContract = runtime_ctx["contract"]
    metrics: MetricsCollector = runtime_ctx["metrics"]
    state: StateManager = runtime_ctx["state_manager"]
    memory_consolidation = get_memory_consolidation()

    success = all(item.get("verified") for item in results) and bool(results)
    verified_success = success
    deliverable_path = contract.context.get("deliverable_path")
    real_artifacts = _collect_real_artifacts(results, deliverable_path)
    final_output = ""
    if deliverable_path and Path(deliverable_path).exists():
        final_output = read_text_file(deliverable_path)
    else:
        final_output = runtime_ctx.get("qa_text") or _build_quality_review(contract, results)

    qa_text = runtime_ctx.get("qa_text") or _build_quality_review(contract, results)

    implementation_guard_failed = bool(contract.context.get("requires_real_source_changes")) and not real_artifacts
    if implementation_guard_failed:
        success = False
        verified_success = False
        guard_note = (
            "Mission requested real source changes, but no project artifacts outside the orchestrator workspace were produced."
        )
        if guard_note not in qa_text:
            qa_text = f"{qa_text}\nNOTE: {guard_note}"
        final_output = "\n".join(
            [
                "# Mission Not Completed",
                "",
                "JARVIS planned and documented the work, but did not verify any real source-code changes in the project.",
                "Treat this run as a draft or planning pass, not an implementation.",
                "",
                "## Requested Goal",
                contract.user_input,
                "",
                "## Why It Failed Honestly",
                guard_note,
                "",
                "## Next Step",
                "Run a dedicated coding flow that edits real project files, then verify the changed artifacts.",
            ]
        )
        guard_code = FailureCode.HALLUCINATED_SUCCESS.value
        if guard_code not in state.failure_codes:
            metrics.record_failure(guard_code)
            state.record_failure(
                {
                    "code": guard_code,
                    "reason": guard_note,
                    "step_id": "deliverable_write",
                }
            )

    contract.context["real_artifacts"] = list(real_artifacts)

    if metrics.current_metrics:
        for item in results:
            result_payload = item.get("result") or {}
            for artifact in result_payload.get("artifacts", []):
                if artifact not in metrics.current_metrics.artifacts:
                    metrics.current_metrics.artifacts.append(artifact)
        for code in state.failure_codes:
            metrics.record_failure(code)

    memory_entry = save_to_memory(
        observation=f"Misiune: {contract.user_input}. Success={success}. Steps={len(results)}.",
        source="Orchestrator",
        tags=_extract_tags(contract.user_input),
        quality_score=_extract_quality_score(qa_text),
        mission_type=runtime_ctx["mission_type"],
    )
    for bias in contract.context.get("execution_biases", []):
        memory_id = bias.get("memory_id")
        if memory_id:
            memory_consolidation.validate_memory_effectiveness(
                memory_id,
                {"success": success, "verified": verified_success},
            )

    episode = _episodic_memory().record_episode(
        {
            "mission_id": mission_id,
            "task": contract.user_input,
            "mission_type": runtime_ctx["mission_type"],
            "status": "SUCCESS" if success else "FAILURE",
            "learning": _safe_excerpt(qa_text, 240),
            "failures": list(state.failure_codes),
            "strategy": (contract.context.get("best_known_strategy") or {}).get("strategy"),
            "tags": _extract_tags(contract.user_input),
            "metrics": metrics.get_latest_metrics().to_dict() if metrics.get_latest_metrics() else {},
        }
    )
    if metrics.current_metrics:
        metrics.current_metrics.memories_written.append(str(memory_entry.get("id")))
        metrics.current_metrics.memories_written.append(str(episode.get("episode_id")))
    metrics.finish_mission(success=success, verified=verified_success)
    metrics_dict = metrics.get_latest_metrics().to_dict() if metrics.get_latest_metrics() else {}
    dod_report = _definition_of_done.evaluate(
        mission_id=mission_id,
        contract=contract,
        results=results,
        metrics=metrics_dict,
        final_output=final_output,
        qa_text=qa_text,
        memory_written=[str(memory_entry.get("id")), str(episode.get("episode_id"))],
    )
    verified_success = verified_success and bool(dod_report.get("done"))
    if metrics.current_metrics:
        metrics.current_metrics.verified_success = verified_success
        metrics._save_metrics(metrics.current_metrics)
    contract.status = TaskStatus.SUCCESS if verified_success else TaskStatus.FAILURE
    contract.completed_at = datetime.now()
    contract.context["definition_of_done"] = dod_report
    governance_signal = _build_governance_signal(
        mission_id,
        qa_text,
        metrics_dict,
        dod_report,
        list(state.failure_codes),
    )
    mission_closure = _build_mission_closure(
        mission_id,
        success=success,
        verified_success=verified_success,
        dod_report=dod_report,
        governance_signal=governance_signal,
        post_mission_governance=None,
    )

    final_report = {
        "mission_id": mission_id,
        "success": success,
        "verified_success": verified_success,
        "final_output": final_output,
        "qa_text": qa_text,
        "metrics": metrics_dict,
        "real_artifacts": list(real_artifacts),
        "definition_of_done": dod_report,
        "governance_signal": governance_signal,
        "mission_closure": mission_closure,
        "contract": contract_to_dict(contract),
        "results": results,
        "memory_written": [str(memory_entry.get("id")), str(episode.get("episode_id"))],
        "post_mission_governance": None,
    }
    reports_dir = Path(os.getcwd()) / ".agent" / "runtime_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    report_path = reports_dir / f"{mission_id}_{timestamp}.json"
    latest_path = reports_dir / "latest_mission.json"
    final_report["report_path"] = str(report_path)
    final_report["latest_report_path"] = str(latest_path)
    try:
        serialized = json.dumps(final_report, indent=2, ensure_ascii=False)
        report_path.write_text(serialized, encoding="utf-8")
        latest_path.write_text(serialized, encoding="utf-8")
    except Exception as exc:
        logger.debug("[MISSION REPORT] Persist failed for %s: %s", mission_id, exc)

    _run_skill_evolution_bg(
        contract.mission_id,
        contract.user_input,
        qa_text,
        _extract_quality_score(qa_text) or 5,
        context={
            "mission_id": mission_id,
            "mission_type": runtime_ctx["mission_type"],
            "metrics": metrics_dict,
            "failure_codes": list(state.failure_codes),
            "definition_of_done": dod_report,
        },
        governance_signal=governance_signal,
        report_path=str(report_path),
        latest_path=str(latest_path),
    )
    return final_report


def run_mission(
    user_goal: str,
    execution_guidance: str | None = None,
    mission_preflight: dict[str, Any] | None = None,
) -> str:
    """Run the blueprint-aligned orchestrator step loop."""
    print(f"\n{'=' * 60}")
    print(f"🎯 MISIUNE: {user_goal}")
    print(f"{'=' * 60}\n")

    mission_type = classify_mission(user_goal)
    anti_repetition = get_anti_repetition_guard(user_goal)
    relevant_lessons = get_relevant_lessons(mission_type)
    project_rules = get_project_rules()

    context = {
        "mission_type": mission_type,
        "anti_repetition": anti_repetition,
        "relevant_lessons": relevant_lessons,
        "project_rules": project_rules,
        "tags": _extract_tags(user_goal),
        "execution_guidance": execution_guidance or "",
        "mission_preflight": mission_preflight or {},
    }
    contract = build_mission_contract(user_goal, context)
    state = StateManager(max_steps=max(50, len(contract.steps) * 10))
    state.reset()
    state.set_contract(contract)
    metrics = MetricsCollector(storage_path=str(Path(os.getcwd()) / ".agent" / "metrics"))
    metrics.start_mission(contract.mission_id)

    runtime_ctx = {
        "user_goal": user_goal,
        "mission_type": mission_type,
        "search_query": user_goal,
        "anti_repetition": anti_repetition,
        "execution_guidance": execution_guidance or "",
        "mission_preflight": mission_preflight or {},
        "contract": contract,
        "state_manager": state,
        "metrics": metrics,
        "step_outputs": {},
        "results": [],
        "step_order": {step.id: idx for idx, step in enumerate(contract.steps)},
    }

    state.transition_to(MissionState.INTAKE, "Mission received")
    state.transition_to(MissionState.PLANNING, "Mission contract created")

    # ── V3 Event Log: run.created ────────────────────────────────
    if _V3_AVAILABLE:
        try:
            get_event_log().emit(E.RUN_CREATED, contract.mission_id, {
                "user_goal": user_goal,
                "mission_type": mission_type,
                "steps": len(contract.steps),
            })
        except Exception:
            pass
    # ── End V3 event log ─────────────────────────────────────────

    # ── Neuro Brain: mission start ───────────────────────────────
    neuro = _get_neuro()
    neuro_belief = None
    neuro_ctx_class = mission_type
    if neuro and neuro.shadow:
        try:
            # 1. Semantic encoding of this mission
            neuro_mem = neuro.binder.encode_mission(contract.mission_id, {
                "goal": user_goal,
                "mission_type": mission_type,
                "risk": context.get("tags", {}).get("risk", "unknown"),
            })
            runtime_ctx["neuro_mem"] = neuro_mem

            # 2. MetaReasoner: derive constraints and check plan safety
            step_texts = [s.title + " " + (s.description or "") for s in contract.steps]
            plan_safe, conflicts = neuro.meta.plan_is_safe({"steps": step_texts})
            if conflicts:
                crit = [c for c in conflicts if c["type"] in ("deny", "require") and c["severity"] in ("critical", "high")]
                if crit:
                    logger.warning(f"[NeuroBrain] MetaReasoner: {len(crit)} critical conflicts in plan")
                    for c in crit[:3]:
                        print(f"   ⚠️  [NeuroBrain] {c['description']} → {c.get('suggestion', '')}")

            # 3. Context classification for routing
            neuro_ctx_class = classify_context(user_goal)
            runtime_ctx["neuro_ctx_class"] = neuro_ctx_class

            # 4. BeliefState init
            neuro_belief = neuro.belief
            neuro_belief.reset()
            runtime_ctx["neuro_belief"] = neuro_belief

            logger.info(f"[NeuroBrain] Active — mode={neuro.mode}, ctx={neuro_ctx_class}")
        except Exception as _ne:
            logger.debug(f"[NeuroBrain] Init error (non-fatal): {_ne}")
    # ── End Neuro Brain init ─────────────────────────────────────

    print(f"📊 Tip misiune detectat: {mission_type.upper()}")
    print(f"📋 Contract generat: {len(contract.steps)} pași")
    for index, step in enumerate(contract.steps, start=1):
        print(f"   {index}. {step.title} [{step.risk.value}]")
    print()

    results: list[dict] = []
    for step in contract.steps:
        outcome = execute_step_pipeline(step, runtime_ctx)
        results.append(outcome)

        # ── Neuro Brain: per-step feedback ───────────────────────
        if neuro and neuro.shadow:
            try:
                tool_used = outcome.get("result", {}).get("tool_name", "unknown")
                obs_status = "success" if outcome.get("verified") else "failure"

                # Update temporal memory
                neuro.temporal.observe({
                    "tool": tool_used,
                    "action": step.id,
                    "outcome": obs_status,
                    "mission_type": mission_type,
                })

                # Update belief state
                if neuro_belief:
                    neuro_belief.update_from_observation({"status": obs_status})

                # Anomaly detection
                anomaly = neuro.temporal.anomaly_score({
                    "tool": tool_used,
                    "action": step.id,
                    "outcome": obs_status,
                    "mission_type": mission_type,
                })

                # Event gate — decide if anomaly warrants attention
                gate_event = {
                    "status": obs_status,
                    "anomaly_score": anomaly,
                    "retry_count": getattr(step, "retry_count", 0),
                }
                gate_decision = neuro.event_gate.evaluate(gate_event)
                if gate_decision.should_fire:
                    logger.info(
                        f"[NeuroBrain] EventGate fired — step={step.id} "
                        f"anomaly={anomaly:.2f} reasons={gate_decision.reasons}"
                    )
                    try:
                        NeuroMaintenanceJournal(Path(os.getcwd()) / ".agent" / "neuro").record_anomaly(
                            contract.mission_id,
                            step.id,
                            anomaly,
                            reasons=list(gate_decision.reasons),
                            gate_fired=True,
                        )
                    except Exception as exc:
                        logger.debug("[NeuroMaintenance] anomaly sync failed: %s", exc)
                    # Fire async maintenance (non-blocking)
                    neuro.trigger_graph.fire(ANOMALY_DETECTED, {
                        "step_id": step.id,
                        "anomaly": anomaly,
                        "mission_id": contract.mission_id,
                    })

                outcome["neuro"] = {
                    "anomaly_score": round(anomaly, 3),
                    "gate_fired": gate_decision.should_fire,
                    "belief": neuro_belief.snapshot() if neuro_belief else {},
                }
            except Exception as _ne:
                logger.debug(f"[NeuroBrain] Step feedback error (non-fatal): {_ne}")
        # ── End per-step neuro feedback ──────────────────────────

        # ── V3 Event Log: tool.call.completed per step ───────────
        if _V3_AVAILABLE:
            try:
                _step_tool = outcome.get("result", {}).get("tool_name", step.id)
                _step_ok = outcome.get("verified", False)
                get_event_log().emit(E.TOOL_COMPLETED, contract.mission_id, {
                    "step_id": step.id,
                    "tool": _step_tool,
                    "success": _step_ok,
                    "anomaly_score": outcome.get("neuro", {}).get("anomaly_score"),
                })
            except Exception:
                pass
        # ── End V3 per-step event ─────────────────────────────────

        if outcome.get("terminal_failure"):
            state.transition_to(MissionState.FAILURE, f"Step failed: {step.id}")
            break

    if results and all(item.get("verified") for item in results):
        state.transition_to(MissionState.SUCCESS, "All steps verified")

    final = finalize_mission(contract.mission_id, results, runtime_ctx)

    # ── V3 Event Log: run.completed + auto improvement proposal ──
    if _V3_AVAILABLE:
        try:
            _mission_ok = all(r.get("verified") for r in results) if results else False
            _failed_steps = [r for r in results if not r.get("verified")]
            get_event_log().emit(E.RUN_COMPLETED, contract.mission_id, {
                "success": _mission_ok,
                "steps_total": len(results),
                "steps_failed": len(_failed_steps),
                "mission_type": mission_type,
            })
            # Auto-propose improvement when ≥2 steps failed — Jarvis notices patterns
            if len(_failed_steps) >= 2:
                _prop_summary = (
                    f"Retry strategy for {mission_type} missions "
                    f"({len(_failed_steps)}/{len(results)} steps failed)"
                )
                get_proposals().propose(
                    source_run_id=contract.mission_id,
                    target_type=_PT.RETRY_STRATEGY,
                    summary=_prop_summary,
                    rationale=(
                        f"Mission '{user_goal[:80]}' had {len(_failed_steps)} failed steps. "
                        "A better retry/backoff strategy may improve success rate."
                    ),
                    evidence=[
                        f"step={r.get('step_id', '?')} failed"
                        for r in _failed_steps[:5]
                    ],
                    expected_gain=0.10,
                    risk_level=_RL.LOW,
                )
        except Exception:
            pass
    # ── End V3 event log + proposals ─────────────────────────────

    # ── Neuro Brain: mission complete rewards ────────────────────
    if neuro and neuro.shadow:
        try:
            mission_success = all(r.get("verified") for r in results) if results else False
            # Reward routing adapter for each step's tool
            for r in results:
                tool_used = r.get("result", {}).get("tool_name", "unknown")
                step_ok = r.get("verified", False)
                neuro.router.reward(neuro_ctx_class, tool_used, step_ok)

            # Fire MISSION_COMPLETE trigger (async maintenance)
            neuro.trigger_graph.fire(MISSION_COMPLETE, {
                "mission_id": contract.mission_id,
                "success": mission_success,
                "steps": len(results),
                "governance": final.get("governance_signal", {}),
            })

            if neuro.shadow:
                print(f"   🧠 [NeuroBrain] Status: {neuro.status()}")
        except Exception as _ne:
            logger.debug(f"[NeuroBrain] Mission complete error (non-fatal): {_ne}")
    # ── End Neuro Brain rewards ──────────────────────────────────

    print(f"\n{'=' * 60}")
    if final.get("verified_success"):
        print("✅ MISIUNE FINALIZATĂ")
    else:
        print("⚠️ MISIUNE NECONFIRMATĂ")
        closure = final.get("mission_closure") or {}
        if closure.get("summary"):
            print(closure["summary"])
    print(f"{'=' * 60}\n")

    return str(final["final_output"])


# ═══════════════════════════════════════════════════════════════
#  🚀 ADVANCED: STREAMING + REPLANNING + JARVIS INTEGRATION
# ═══════════════════════════════════════════════════════════════


async def run_mission_stream(
    user_goal: str,
    execution_guidance: str | None = None,
    mission_preflight: dict[str, Any] | None = None,
) -> AsyncGenerator[str, None]:
    """Streaming view over the blueprint-aligned step pipeline."""
    yield f"\n{'=' * 60}\n"
    yield f"🎯 MISIUNE: {user_goal}\n"
    yield f"{'=' * 60}\n\n"

    mission_type = classify_mission(user_goal)
    anti_repetition = get_anti_repetition_guard(user_goal)
    relevant_lessons = get_relevant_lessons(mission_type)
    project_rules = get_project_rules()

    contract = build_mission_contract(
        user_goal,
        {
            "mission_type": mission_type,
            "anti_repetition": anti_repetition,
            "relevant_lessons": relevant_lessons,
            "project_rules": project_rules,
            "tags": _extract_tags(user_goal),
            "execution_guidance": execution_guidance or "",
            "mission_preflight": mission_preflight or {},
        },
    )
    state = StateManager(max_steps=max(50, len(contract.steps) * 10))
    state.reset()
    state.set_contract(contract)
    metrics = MetricsCollector(storage_path=str(Path(os.getcwd()) / ".agent" / "metrics"))
    metrics.start_mission(contract.mission_id)

    runtime_ctx = {
        "user_goal": user_goal,
        "mission_type": mission_type,
        "search_query": user_goal,
        "anti_repetition": anti_repetition,
        "execution_guidance": execution_guidance or "",
        "mission_preflight": mission_preflight or {},
        "contract": contract,
        "state_manager": state,
        "metrics": metrics,
        "step_outputs": {},
        "results": [],
        "step_order": {step.id: idx for idx, step in enumerate(contract.steps)},
    }

    state.transition_to(MissionState.INTAKE, "Mission received")
    state.transition_to(MissionState.PLANNING, "Mission contract created")
    yield f"📊 Tip misiune detectat: {mission_type.upper()}\n"
    yield f"📋 Contract generat: {len(contract.steps)} pași\n"
    for index, step in enumerate(contract.steps, start=1):
        yield f"   {index}. {step.title} [{step.risk.value}]\n"
    yield "\n"

    results: list[dict] = []
    for step in contract.steps:
        yield f"⚙️ {step.title}\n"
        outcome = execute_step_pipeline(step, runtime_ctx)
        results.append(outcome)
        verification = outcome.get("verification") or {}
        yield (
            f"   → tool={outcome.get('result', {}).get('tool_name', 'n/a')} "
            f"verified={verification.get('verified', False)} "
            f"action={verification.get('recommended_action', 'n/a')}\n"
        )
        if outcome.get("repair"):
            yield f"   → repair={outcome['repair'].get('repair_action')}: {outcome['repair'].get('repair_reason')}\n"
        if outcome.get("terminal_failure"):
            state.transition_to(MissionState.FAILURE, f"Step failed: {step.id}")
            break

    if results and all(item.get("verified") for item in results):
        state.transition_to(MissionState.SUCCESS, "All steps verified")

    final = finalize_mission(contract.mission_id, results, runtime_ctx)
    quality_score = _extract_quality_score(final.get("qa_text", "")) or 0
    yield f"\n📊 Scor QA: {quality_score}/10\n"
    yield f"\n{'=' * 60}\n"
    if final.get("verified_success"):
        yield f"✅ MISIUNE FINALIZATĂ (Scor: {quality_score}/10)\n"
    else:
        closure = final.get("mission_closure") or {}
        yield "⚠️ MISIUNE NECONFIRMATĂ\n"
        if closure.get("summary"):
            yield f"{closure['summary']}\n"
    yield f"{'=' * 60}\n\n"
    yield str(final["final_output"])
