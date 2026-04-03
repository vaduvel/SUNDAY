"""J.A.R.V.I.S. NUCLEUS BRIDGE — API V2

The local API hub for the J.A.R.V.I.S. NUCLEUS app.
Uses FastAPI + WebSockets to sync the Python Engine with the Next.js UI.

Endpoints:
   WS  /ws/events           – Real-time event stream to UI
   POST /api/mission         – Submit a new mission (CrewAI workflow)
   POST /api/chat            – Primary chat with JARVIS agentic runtime
   POST /api/mission/cancel  – Cancel running mission
   GET  /api/status          – System health / agent status
   GET  /api/history         – Recent mission history
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# Add project root to path so we can import core modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.output_hygiene import chunk_text, sanitize_assistant_output
from pydantic import BaseModel

from core.runtime_config import (
    configure_inception_openai_alias,
    get_cors_origins,
    load_project_env,
    resolve_obsidian_vault_path,
)

load_project_env(PROJECT_ROOT)
configure_inception_openai_alias()

logger = logging.getLogger(__name__)
OBSIDIAN_VAULT_PATH = resolve_obsidian_vault_path(PROJECT_ROOT)

app = FastAPI(title="J.A.R.V.I.S. NUCLEUS Bridge", version="2.0.0")

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def awaken_daemon():
    try:
        from core.autonomy_daemon import jarvis_daemon

        await jarvis_daemon.start()
    except Exception as exc:
        logger.warning("[BRIDGE] Autonomy daemon start skipped: %s", exc)

    asyncio.create_task(_refresh_runtime_cockpit_cache())
    asyncio.create_task(_refresh_knowledge_graph_stats_cache())


@app.on_event("shutdown")
async def sleep_daemon():
    try:
        from core.autonomy_daemon import jarvis_daemon

        await jarvis_daemon.stop()
    except Exception as exc:
        logger.warning("[BRIDGE] Autonomy daemon stop skipped: %s", exc)


# ═══════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════


class NucleusState:
    """Global mutable state for the bridge."""

    def __init__(self):
        self.is_running = False
        self.current_mission: Optional[str] = None
        self.cancel_requested = False
        self.history: List[Dict[str, Any]] = []
        self.start_time: Optional[float] = None

    def start_mission(self, mission: str):
        self.is_running = True
        self.current_mission = mission
        self.cancel_requested = False
        self.start_time = time.time()

    def end_mission(self, result: str = ""):
        elapsed = time.time() - self.start_time if self.start_time else 0
        self.history.append(
            {
                "mission": self.current_mission,
                "result_preview": result[:200] if result else "",
                "timestamp": datetime.now().isoformat(),
                "duration_sec": round(elapsed, 1),
            }
        )
        # Keep last 50 missions
        self.history = self.history[-50:]
        self.is_running = False
        self.current_mission = None
        self.start_time = None


state = NucleusState()

COCKPIT_CACHE_TTL_SEC = float(os.getenv("JARVIS_COCKPIT_CACHE_TTL_SEC", "120"))
_runtime_cockpit_cache: Dict[str, Any] = {
    "data": None,
    "updated_at": 0.0,
    "refreshing": False,
    "error": None,
}
KNOWLEDGE_GRAPH_CACHE_TTL_SEC = float(
    os.getenv("JARVIS_KNOWLEDGE_GRAPH_CACHE_TTL_SEC", "900")
)
_knowledge_graph_cache: Dict[str, Any] = {
    "data": None,
    "updated_at": 0.0,
    "refreshing": False,
    "error": None,
    "project_root": None,
}


def _runtime_cockpit_age_sec() -> float:
    updated_at = float(_runtime_cockpit_cache.get("updated_at") or 0.0)
    if not updated_at:
        return float("inf")
    return max(0.0, time.time() - updated_at)


def _runtime_reports_dir() -> Path:
    reports_dir = Path(PROJECT_ROOT) / ".agent" / "runtime_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def _knowledge_graph_cache_path() -> Path:
    return _runtime_reports_dir() / "knowledge_graph_stats.json"


def _knowledge_graph_age_sec() -> float:
    updated_at = float(_knowledge_graph_cache.get("updated_at") or 0.0)
    if not updated_at:
        return float("inf")
    return max(0.0, time.time() - updated_at)


def _estimate_code_file_count() -> int:
    count = 0
    allowed_suffixes = {".py", ".ts", ".tsx"}
    ignored_dirs = {
        "__pycache__",
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".venv311",
        "pixel-agents-repo",
    }
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [entry for entry in dirs if entry not in ignored_dirs]
        for file_name in files:
            if Path(file_name).suffix in allowed_suffixes:
                count += 1
    return count


def _default_knowledge_graph_stats() -> Dict[str, Any]:
    return {
        "total_nodes": 0,
        "total_edges": 0,
        "files_indexed": _estimate_code_file_count(),
        "node_types": {},
        "cached": False,
    }


def _load_knowledge_graph_stats_snapshot() -> Dict[str, Any]:
    current_root = str(PROJECT_ROOT)
    if _knowledge_graph_cache.get("project_root") != current_root:
        _knowledge_graph_cache["data"] = None
        _knowledge_graph_cache["updated_at"] = 0.0
        _knowledge_graph_cache["project_root"] = current_root

    cached = _knowledge_graph_cache.get("data")
    if isinstance(cached, dict):
        return dict(cached)

    cache_path = _knowledge_graph_cache_path()
    if not cache_path.exists():
        return _default_knowledge_graph_stats()

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return _default_knowledge_graph_stats()

    updated_at = float(payload.pop("_cached_at", time.time()))
    _knowledge_graph_cache["data"] = dict(payload)
    _knowledge_graph_cache["updated_at"] = updated_at
    _knowledge_graph_cache["project_root"] = current_root
    return dict(payload)


def _rebuild_knowledge_graph_stats_sync() -> Dict[str, Any]:
    from core.knowledge_graph import CodeKnowledgeGraph

    knowledge = CodeKnowledgeGraph(PROJECT_ROOT)
    knowledge.index_directory(
        extensions=[".py", ".ts", ".tsx"],
        ignore_patterns=[
            "__pycache__",
            ".git",
            "node_modules",
            ".venv",
            "venv",
            "dist",
            "build",
            ".venv311",
            "pixel-agents-repo",
        ],
    )
    stats = knowledge.get_graph_stats()
    payload = dict(stats)
    payload["_cached_at"] = time.time()
    _knowledge_graph_cache_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return stats


async def _refresh_knowledge_graph_stats_cache() -> None:
    if _knowledge_graph_cache["refreshing"]:
        return

    _knowledge_graph_cache["refreshing"] = True
    try:
        payload = await asyncio.to_thread(_rebuild_knowledge_graph_stats_sync)
        _knowledge_graph_cache["data"] = payload
        _knowledge_graph_cache["updated_at"] = time.time()
        _knowledge_graph_cache["error"] = None
        _knowledge_graph_cache["project_root"] = str(PROJECT_ROOT)
    except Exception as exc:
        _knowledge_graph_cache["error"] = str(exc)
        logger.warning("[BRIDGE] Knowledge graph refresh failed: %s", exc)
    finally:
        _knowledge_graph_cache["refreshing"] = False


def _load_governance_history(limit: int = 5) -> List[Dict[str, Any]]:
    """Read the latest persisted governance decisions for cockpit and API views."""
    history_path = _runtime_reports_dir() / "governance_history.jsonl"
    if not history_path.exists():
        return []

    records: List[Dict[str, Any]] = []
    try:
        lines = history_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        records.append(
            {
                "mission_id": payload.get("mission_id"),
                "recorded_at": payload.get("recorded_at"),
                "action": payload.get("action"),
                "status": payload.get("status"),
                "gate_decision": payload.get("gate_decision"),
                "gate_reason": payload.get("gate_reason"),
                "candidate_skill_name": payload.get("candidate_skill_name"),
                "proposal_summary": payload.get("proposal_summary"),
                "proposal_id": payload.get("proposal_id"),
                "approved_by": payload.get("approved_by"),
                "quality_score": payload.get("quality_score"),
                "governance_signal": payload.get("governance_signal") or {},
            }
        )
        if len(records) >= max(0, int(limit)):
            break
    return records


def _filter_recent_proposals(
    proposals: List[Dict[str, Any]],
    *,
    proposal_status: str | None = None,
    target_type: str | None = None,
    query: str | None = None,
) -> List[Dict[str, Any]]:
    filtered = list(proposals)
    if proposal_status and proposal_status != "all":
        filtered = [
            proposal
            for proposal in filtered
            if str(proposal.get("status") or "").lower() == proposal_status.lower()
        ]
    if target_type and target_type != "all":
        filtered = [
            proposal
            for proposal in filtered
            if str(proposal.get("target_type") or "").lower() == target_type.lower()
        ]
    if query:
        needle = query.lower()
        filtered = [
            proposal
            for proposal in filtered
            if needle in json.dumps(proposal, ensure_ascii=False).lower()
        ]
    return filtered


def _proposal_priority_score(proposal: Dict[str, Any]) -> float:
    """Compute a stable operator-facing priority score for governance review."""
    status = str(proposal.get("status") or "").lower()
    risk_level = str(proposal.get("risk_level") or "low").lower()
    target_type = str(proposal.get("target_type") or "").lower()
    expected_gain = float(proposal.get("expected_gain") or 0.0)
    eval_score = proposal.get("eval_score")
    updated_at = float(proposal.get("updated_at") or proposal.get("created_at") or 0.0)
    age_hours = max(0.0, (time.time() - updated_at) / 3600.0) if updated_at else 0.0

    status_weight = {
        "eval_passed": 0.34,
        "drafted": 0.26,
        "on_hold": 0.22,
        "queued_for_eval": 0.18,
        "eval_failed": 0.08,
        "eval_running": 0.02,
        "promoted": -0.2,
        "rejected": -0.3,
    }.get(status, 0.0)
    risk_weight = {"low": 0.08, "medium": 0.16, "high": 0.24}.get(risk_level, 0.08)
    target_weight = 0.12 if target_type == "skill" else 0.04
    gain_weight = min(max(expected_gain, 0.0), 1.0) * 0.34
    eval_weight = (
        min(max(float(eval_score), 0.0), 1.0) * 0.18
        if isinstance(eval_score, (int, float))
        else 0.0
    )
    age_weight = min(age_hours / 24.0, 1.0) * 0.08
    score = status_weight + risk_weight + target_weight + gain_weight + eval_weight + age_weight
    return round(score, 4)


def _proposal_priority_band(score: float) -> str:
    if score >= 0.8:
        return "urgent"
    if score >= 0.55:
        return "high"
    return "normal"


def _sort_recent_proposals(
    proposals: List[Dict[str, Any]],
    sort_by: str,
) -> List[Dict[str, Any]]:
    items = list(proposals)
    normalized = (sort_by or "newest").lower()
    if normalized == "priority":
        items.sort(
            key=lambda proposal: (
                -_proposal_priority_score(proposal),
                -float(proposal.get("updated_at") or proposal.get("created_at") or 0.0),
            )
        )
        return items
    if normalized == "expected_gain":
        items.sort(
            key=lambda proposal: (
                -float(proposal.get("expected_gain") or 0.0),
                -float(proposal.get("updated_at") or proposal.get("created_at") or 0.0),
            )
        )
        return items
    if normalized == "eval_score":
        items.sort(
            key=lambda proposal: (
                -float(proposal.get("eval_score") or -1.0),
                -float(proposal.get("updated_at") or proposal.get("created_at") or 0.0),
            )
        )
        return items
    items.sort(
        key=lambda proposal: -float(proposal.get("updated_at") or proposal.get("created_at") or 0.0)
    )
    return items


def _build_approval_queue(proposals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return actionable skill proposals ordered for human review."""
    actionable: List[Dict[str, Any]] = []
    for proposal in proposals:
        status = str(proposal.get("status") or "drafted").lower()
        target_type = str(proposal.get("target_type") or "").lower()
        if target_type != "skill":
            continue
        if status in {"promoted", "rejected", "eval_running"}:
            continue
        priority_score = _proposal_priority_score(proposal)
        enriched = dict(proposal)
        enriched["priority_score"] = priority_score
        enriched["priority_band"] = _proposal_priority_band(priority_score)
        actionable.append(enriched)

    actionable.sort(
        key=lambda proposal: (
            -float(proposal.get("priority_score") or 0.0),
            -float(proposal.get("updated_at") or proposal.get("created_at") or 0.0),
        )
    )
    return actionable


def _filter_governance_history(
    records: List[Dict[str, Any]],
    *,
    action: str | None = None,
    gate_decision: str | None = None,
    human_only: bool = False,
    query: str | None = None,
) -> List[Dict[str, Any]]:
    filtered = list(records)
    if action and action != "all":
        filtered = [
            record
            for record in filtered
            if str(record.get("action") or "").lower() == action.lower()
        ]
    if gate_decision and gate_decision != "all":
        filtered = [
            record
            for record in filtered
            if str(record.get("gate_decision") or record.get("status") or "").lower()
            == gate_decision.lower()
        ]
    if human_only:
        filtered = [
            record
            for record in filtered
            if bool(record.get("approved_by"))
            or bool((record.get("governance_signal") or {}).get("human_action"))
        ]
    if query:
        needle = query.lower()
        filtered = [
            record
            for record in filtered
            if needle in json.dumps(record, ensure_ascii=False).lower()
        ]
    return filtered


def _append_governance_history_record(record: Dict[str, Any]) -> None:
    history_path = _runtime_reports_dir() / "governance_history.jsonl"
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _record_manual_governance_audit(record: Dict[str, Any]) -> None:
    _append_governance_history_record(record)
    try:
        from core.neuro_maintenance import NeuroMaintenanceJournal

        NeuroMaintenanceJournal(Path(PROJECT_ROOT) / ".agent" / "neuro").record_governance(
            record.get("mission_id") or f"manual:{record.get('proposal_id') or 'unknown'}",
            {
                "action": record.get("action"),
                "status": record.get("status"),
                "gate_decision": record.get("gate_decision"),
                "gate_reason": record.get("gate_reason"),
                "candidate_skill_name": record.get("candidate_skill_name"),
                "proposal_id": record.get("proposal_id"),
                "quality_score": record.get("quality_score"),
            },
            governance_signal=record.get("governance_signal") or {},
        )
    except Exception as exc:
        logger.warning("[BRIDGE] Manual governance audit sync failed: %s", exc)


def _governance_policy_presets() -> List[Dict[str, Any]]:
    return [
        {
            "id": "review_queue",
            "label": "Review Queue",
            "description": "Show actionable skill proposals sorted by operator priority.",
            "filters": {
                "proposal_status": "all",
                "target_type": "skill",
                "action": "all",
                "gate_decision": "all",
                "sort_by": "priority",
                "human_only": False,
                "query": "",
            },
        },
        {
            "id": "human_actions",
            "label": "Human Actions",
            "description": "Show only operator-driven governance events.",
            "filters": {
                "proposal_status": "all",
                "target_type": "all",
                "action": "all",
                "gate_decision": "all",
                "sort_by": "newest",
                "human_only": True,
                "query": "",
            },
        },
        {
            "id": "holds_and_blocks",
            "label": "Holds",
            "description": "Focus on proposals and mission follow-ups that still need operator attention.",
            "filters": {
                "proposal_status": "on_hold",
                "target_type": "skill",
                "action": "hold",
                "gate_decision": "hold",
                "sort_by": "priority",
                "human_only": True,
                "query": "",
            },
        },
        {
            "id": "promotions",
            "label": "Promotions",
            "description": "Review promoted improvements and promotion evidence.",
            "filters": {
                "proposal_status": "promoted",
                "target_type": "skill",
                "action": "approve",
                "gate_decision": "promote",
                "sort_by": "eval_score",
                "human_only": False,
                "query": "",
            },
        },
    ]


def _build_governance_export_markdown(payload: Dict[str, Any]) -> str:
    """Render a compact governance export for operators."""
    lines = [
        "# Governance Audit Export",
        "",
        f"Generated: {datetime.now().isoformat()}",
        "",
        "## Filters",
    ]
    filters = payload.get("filters") or {}
    for key, value in filters.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Proposal Summary"])
    summary = payload.get("proposal_summary") or {}
    lines.append(f"- total: {summary.get('total', 0)}")
    lines.append(f"- pending_eval: {summary.get('pending_eval', 0)}")

    lines.extend(["", "## Approval Queue"])
    approval_queue = payload.get("approval_queue") or []
    if approval_queue:
        for proposal in approval_queue:
            lines.append(
                f"- {proposal.get('proposal_summary') or proposal.get('proposal_id')}: "
                f"{proposal.get('status', 'unknown')} | "
                f"priority={proposal.get('priority_band', 'normal')} "
                f"({proposal.get('priority_score', 0)})"
            )
    else:
        lines.append("- No actionable proposals in queue.")

    lines.extend(["", "## Recent Governance"])
    recent_governance = payload.get("recent_governance") or []
    if recent_governance:
        for item in recent_governance:
            lines.append(
                f"- {(item.get('gate_decision') or item.get('status') or 'observe').upper()}: "
                f"{item.get('candidate_skill_name') or item.get('proposal_summary') or item.get('mission_id')}"
            )
    else:
        lines.append("- No recent governance events.")

    latest_mission = payload.get("latest_mission") or {}
    closure = latest_mission.get("mission_closure") or {}
    if closure:
        lines.extend(
            [
                "",
                "## Latest Mission Closure",
                f"- status: {closure.get('status')}",
                f"- summary: {closure.get('summary')}",
                f"- next_action: {closure.get('next_action')}",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def _build_runtime_cockpit_sync() -> Dict[str, Any]:
    """Build the expensive cockpit payload off the event loop."""
    from core.identity_context import IdentityContextManager
    from core.neuro import get_neuro_brain
    from core.neuro_maintenance import NeuroMaintenanceJournal
    from core.plan_notebook import PlanNotebook
    from core.session_runtime import SessionRuntime
    from core.self_evolving_skills import SelfEvolvingSkills
    from core.tracing_runtime import JarvisTracer
    from core.ultraplan import UltraPlanner
    from core.skill_library import SkillLibrary
    from tools.memory_tool import StructuredMemory, load_lessons, load_memory

    vault_path = Path(PROJECT_ROOT) / ".agent" / "brain_vault"
    identity = IdentityContextManager(
        os.path.join(PROJECT_ROOT, ".agent", "brain_vault"),
        PROJECT_ROOT,
    )
    planner = UltraPlanner()
    notebook = PlanNotebook(vault_path)
    sessions = SessionRuntime(vault_path)
    tracer = JarvisTracer(vault_path)
    library = SkillLibrary()
    skills = SelfEvolvingSkills(os.path.join(PROJECT_ROOT, ".jarvis", "skills"))
    structured_memory = StructuredMemory()
    neuro = get_neuro_brain(os.path.join(PROJECT_ROOT, ".agent", "neuro"))
    neuro_maintenance = NeuroMaintenanceJournal(Path(PROJECT_ROOT) / ".agent" / "neuro")
    knowledge_stats = _load_knowledge_graph_stats_snapshot()
    latest_report_path = Path(PROJECT_ROOT) / ".agent" / "runtime_reports" / "latest_mission.json"
    latest_report = None
    if latest_report_path.exists():
        try:
            latest_report = json.loads(latest_report_path.read_text(encoding="utf-8"))
        except Exception:
            latest_report = None

    skills_status = skills.get_skill_status()
    governance_history = _load_governance_history(limit=5)
    neuro_status = neuro.status()
    neuro_status.update(
        {
            "recent_sequence": neuro.temporal.context_summary(),
            "routing_summary": neuro.router.summary()[:5],
            "event_gate": neuro.event_gate.stats(),
            "maintenance": neuro_maintenance.status(limit=3),
        }
    )
    latest_dod = latest_report.get("definition_of_done") if isinstance(latest_report, dict) else None

    return {
        "identity": identity.summary(),
        "structured_memory": {
            "counts": {
                "short_term": len(structured_memory.recall_short_term(limit=30)),
                "long_term": len(load_memory()),
                "entity": len(structured_memory.recall_entity()),
                "episodic": len(structured_memory.recall_episodic(limit=30)),
                "lessons": len(load_lessons()),
            },
            "memory_signal": structured_memory.get_full_context(session_id="chat")[:800],
        },
        "planning": {
            "modes": ["default", "ultraplan", "coordinator"],
            "keywords": sorted(planner.COMPLEXITY_KEYWORDS.keys()),
            "notebook": notebook.summary(),
        },
        "sessions": sessions.list_sessions(limit=5),
        "tracing": tracer.summary(),
        "skill_library": {
            "count": len(library.skills),
            "categories": library.get_all_categories(),
        },
        "skill_governance": {
            "active_skills": skills_status.get("active_skills", 0),
            "total_skills": skills_status.get("total_skills", 0),
            "lifecycle_counts": skills_status.get("lifecycle_counts", {}),
            "proposal_summary": skills_status.get("proposal_summary", {}),
            "promotion_history": skills_status.get("promotion_history", []),
            "recent_proposals": skills_status.get("recent_proposals", []),
            "recent_governance": governance_history,
        },
        "neuro": neuro_status,
        "knowledge_graph": knowledge_stats,
        "latest_mission": {
            "mission_id": latest_report.get("mission_id") if latest_report else None,
            "success": latest_report.get("success") if latest_report else None,
            "verified_success": latest_report.get("verified_success") if latest_report else None,
            "definition_of_done": latest_dod,
            "governance_signal": latest_report.get("governance_signal") if latest_report else None,
            "post_mission_governance": latest_report.get("post_mission_governance") if latest_report else None,
            "mission_closure": latest_report.get("mission_closure") if latest_report else None,
        },
        "harness": {
            "retry": True,
            "timeout": True,
            "fallback": True,
            "circuit_breaker": True,
        },
}


async def _refresh_runtime_cockpit_cache() -> None:
    if _runtime_cockpit_cache["refreshing"]:
        return

    _runtime_cockpit_cache["refreshing"] = True
    try:
        payload = await asyncio.to_thread(_build_runtime_cockpit_sync)
        _runtime_cockpit_cache["data"] = payload
        _runtime_cockpit_cache["updated_at"] = time.time()
        _runtime_cockpit_cache["error"] = None
    except Exception as exc:
        _runtime_cockpit_cache["error"] = str(exc)
        logger.warning("[BRIDGE] Cockpit refresh failed: %s", exc)
    finally:
        _runtime_cockpit_cache["refreshing"] = False


class PlanningPreviewRequest(BaseModel):
    """Request body for ULTRAPLAN/coordinator preview."""

    task: str


class GovernanceProposalActionRequest(BaseModel):
    """Safe human governance actions for proposal lifecycle."""

    proposal_id: str
    action: str
    reason: str = ""
    approved_by: str = "operator"


class GovernanceBulkActionRequest(BaseModel):
    """Safe bulk human governance actions for proposal lifecycle."""

    proposal_ids: List[str]
    action: str
    reason: str = ""
    approved_by: str = "operator"


class SessionResumeRequest(BaseModel):
    """Request body for resuming a persisted runtime session."""

    session_id: str


# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET CONNECTION MANAGER
# ═══════════════════════════════════════════════════════════════


class ConnectionManager:
    """Manages active WebSocket connections to the UI."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[BRIDGE] UI connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(
            f"[BRIDGE] UI disconnected. Remaining: {len(self.active_connections)}"
        )

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast engine event to all connected UI clients."""
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════
#  ENDPOINTS
# ═══════════════════════════════════════════════════════════════


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Future: handle UI commands here
            try:
                cmd = json.loads(data)
                if cmd.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)


class MissionRequest(BaseModel):
    mission: str
    stream: bool = True
    timeout_seconds: int = 180


@app.post("/api/mission")
async def submit_mission(req: MissionRequest):
    """Submit a mission to the agent farm. Returns streaming text/event-stream."""
    if state.is_running:
        return {
            "error": "A mission is already running. Cancel it first.",
            "status": "busy",
        }

    mission_preflight = await _prepare_principal_mission(req.mission)
    execution_goal = _compose_principal_mission_goal(req.mission, mission_preflight)

    state.start_mission(req.mission)
    await _push_mission_preflight_event(req.mission, mission_preflight, source="api")
    await push_event("MISSION_START", f"Mission received: {req.mission[:80]}...")

    if req.stream:
        return StreamingResponse(
            _stream_mission(
                req.mission,
                req.timeout_seconds,
                mission_preflight=mission_preflight,
                execution_goal=execution_goal,
            ),
            media_type="text/event-stream",
        )
    else:
        # Synchronous mode
        try:
            result = await _run_principal_mission_sync(
                req.mission,
                mission_preflight=mission_preflight,
                execution_goal=execution_goal,
            )
            state.end_mission(result)
            await push_event("MISSION_COMPLETE", "Mission finished.")
            return {
                "result": result,
                "status": "done",
                "mission_preflight": mission_preflight,
            }
        except Exception as e:
            state.end_mission(str(e))
            await push_event("MISSION_ERROR", str(e))
            return {"error": str(e), "status": "error"}


class ChatRequest(BaseModel):
    message: str
    stream: bool = True
    voice: bool = False
    session_id: Optional[str] = None


class LiveSessionStartRequest(BaseModel):
    source: str = "gemini-live"
    mode: str = "voice"
    allow_agent_start: bool = True
    allow_browser_control: bool = True
    allow_computer_control: bool = True
    allow_cowork_control: bool = True


class LiveTurnRequest(BaseModel):
    session_id: str
    user_text: str
    source: str = "gemini-live"
    mode: str = "auto"
    allow_agent_start: Optional[bool] = None
    allow_browser_control: Optional[bool] = None
    allow_computer_control: Optional[bool] = None
    allow_cowork_control: Optional[bool] = None
    screen_summary: Optional[str] = None
    camera_summary: Optional[str] = None
    screen_active: bool = False
    camera_active: bool = False


class LiveSessionControlRequest(BaseModel):
    session_id: str
    reason: str = ""


_live_sessions: Dict[str, Dict[str, Any]] = {}
_active_background_tasks: set[asyncio.Task[Any]] = set()
_chat_sessions: Dict[str, Dict[str, Any]] = {}
_CHAT_SESSION_LIMIT = 8
_DEFAULT_CHAT_SESSION_ID = "primary-chat"


def _resolve_chat_session_id(session_id: Optional[str] = None) -> str:
    normalized = str(session_id or "").strip()
    return normalized or _DEFAULT_CHAT_SESSION_ID


def _evict_stale_chat_sessions() -> None:
    if len(_chat_sessions) <= _CHAT_SESSION_LIMIT:
        return

    oldest = sorted(
        _chat_sessions.items(),
        key=lambda item: float(item[1].get("updated_at") or 0.0),
    )
    for session_key, _payload in oldest[: max(0, len(_chat_sessions) - _CHAT_SESSION_LIMIT)]:
        _chat_sessions.pop(session_key, None)


def _get_or_create_chat_session(
    session_id: Optional[str] = None,
    *,
    mode_hint: str = "chat",
):
    from chat_jarvis import JarvisChat

    resolved_session_id = _resolve_chat_session_id(session_id)
    cached = _chat_sessions.get(resolved_session_id)
    chat = cached.get("chat") if isinstance(cached, dict) else None

    if not isinstance(chat, JarvisChat):
        try:
            chat = JarvisChat(session_id=resolved_session_id, mode_hint=mode_hint)
        except TypeError:
            chat = JarvisChat()
            try:
                setattr(chat, "session_id", resolved_session_id)
                setattr(chat, "mode_hint", mode_hint)
            except Exception:
                pass
        _chat_sessions[resolved_session_id] = {
            "chat": chat,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        _evict_stale_chat_sessions()
    else:
        setattr(chat, "session_id", resolved_session_id)
        setattr(chat, "mode_hint", mode_hint)
        cached["updated_at"] = time.time()

    return resolved_session_id, chat


def _new_live_session_id() -> str:
    return f"live_{int(time.time() * 1000)}"


def _live_session_permissions(
    session: Dict[str, Any], req: LiveTurnRequest | None = None
) -> Dict[str, bool]:
    permissions = dict(session.get("permissions") or {})
    if req is None:
        return permissions

    overrides = {
        "allow_agent_start": req.allow_agent_start,
        "allow_browser_control": req.allow_browser_control,
        "allow_computer_control": req.allow_computer_control,
        "allow_cowork_control": req.allow_cowork_control,
    }
    for key, value in overrides.items():
        if value is not None:
            permissions[key] = bool(value)
    return permissions


def _store_live_session_turn(
    session: Dict[str, Any],
    *,
    speaker: str,
    text: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if not text:
        return
    transcript = session.setdefault("transcript", [])
    transcript.append(
        {
            "speaker": speaker,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            "payload": payload or {},
        }
    )
    session["transcript"] = transcript[-80:]
    session["updated_at"] = time.time()


def _looks_like_browser_live_command(text: str) -> bool:
    lowered = text.lower()
    browser_markers = (
        "browser",
        "navighează",
        "navigheaza",
        "deschide site",
        "open site",
        "url",
        "caută pe web",
        "cauta pe web",
        "search web",
        "website",
        "pagina web",
        "page",
        "tab",
        "chrome",
        "safari",
        "firefox",
        "edge",
        "extract",
        "scrape",
        "http://",
        "https://",
    )
    return any(marker in lowered for marker in browser_markers)


def _looks_like_computer_live_command(text: str) -> bool:
    lowered = text.lower()
    computer_markers = (
        "click",
        "apasă",
        "apasa",
        "tastează",
        "tasteaza",
        "scrie în",
        "scrie in",
        "open app",
        "deschide aplica",
        "deschide aplicaț",
        "terminal",
        "finder",
        "settings",
        "setări",
        "mouse",
        "keyboard",
        "desktop",
        "screen",
    )
    return any(marker in lowered for marker in computer_markers)


def _looks_like_cowork_live_command(text: str) -> bool:
    lowered = text.lower()
    cowork_markers = (
        "cowork",
        "co-work",
        "co work",
        "lucrează cu mine",
        "lucreaza cu mine",
        "always on",
        "mereu activ",
        "monitorizează ecranul",
        "monitorizeaza ecranul",
    )
    return any(marker in lowered for marker in cowork_markers)


def _looks_like_visual_live_question(text: str) -> bool:
    lowered = text.lower()
    visual_markers = (
        "vezi",
        "vede",
        "văd",
        "vad",
        "ecran",
        "screen",
        "desktop",
        "monitor",
        "ce aplica",
        "ce aplicaț",
        "ce aplicatie",
        "ce ai pe ecran",
        "ce este deschis",
        "ce e deschis",
        "fereastra",
        "webcam",
        "camera",
        "ce observi",
        "ce se vede",
    )
    return any(marker in lowered for marker in visual_markers)


def _looks_like_visual_denial(text: str) -> bool:
    lowered = text.lower()
    denial_markers = (
        "nu am capacitatea de a vedea",
        "nu pot vedea",
        "nu văd",
        "nu vad",
        "nu am acces vizual",
        "nu pot analiza ecranul",
    )
    return any(marker in lowered for marker in denial_markers)


async def _observe_local_screen_summary() -> Optional[str]:
    try:
        from core.computer_use_agent import ComputerUseAgent

        observation = await ComputerUseAgent().observe_screen()
        if not observation.get("success"):
            return None

        active_app = observation.get("active_app") or "necunoscută"
        active_window = observation.get("active_window") or active_app
        screen = observation.get("screen_size") or {}
        width = screen.get("width") or "?"
        height = screen.get("height") or "?"
        mouse = observation.get("mouse_position") or {}
        mouse_x = mouse.get("x")
        mouse_y = mouse.get("y")
        mouse_hint = (
            f" Mouse-ul este la ({mouse_x}, {mouse_y})."
            if mouse_x is not None and mouse_y is not None
            else ""
        )
        return (
            f"Aplicația activă este {active_app}, cu fereastra activă {active_window}. "
            f"Desktopul observat are rezoluția {width}x{height}.{mouse_hint}"
        )
    except Exception as exc:
        logger.warning("[LIVE] Local screen observation unavailable: %s", exc)
        return None


def _compose_live_visual_context(
    *,
    screen_summary: Optional[str] = None,
    camera_summary: Optional[str] = None,
    screen_active: bool = False,
    camera_active: bool = False,
    session: Optional[Dict[str, Any]] = None,
    observed_screen_summary: Optional[str] = None,
) -> str:
    session = session or {}
    parts: List[str] = []

    if screen_active or session.get("screen_active"):
        parts.append("Screen share este activ în sesiunea live.")
    if camera_active or session.get("camera_active"):
        parts.append("Webcam-ul este activ în sesiunea live.")
    if screen_summary:
        parts.append(f"Rezumat ecran de la Gemini: {screen_summary}")
    elif observed_screen_summary:
        parts.append(f"Observație locală desktop: {observed_screen_summary}")
    if camera_summary:
        parts.append(f"Rezumat cameră de la Gemini: {camera_summary}")

    return "\n".join(parts).strip()


def _live_result_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return str(payload)

    for key in (
        "response",
        "message",
        "summary",
        "result",
        "content",
        "answer",
        "status",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if isinstance(payload.get("actions"), list) and payload["actions"]:
        first = payload["actions"][0]
        if isinstance(first, dict):
            description = first.get("description") or first.get("action_type")
            if description:
                return f"Am executat acțiuni de co-work. Primul pas: {description}"

    return json.dumps(payload, ensure_ascii=False)[:600]


def _select_browser_tool_call(text: str) -> tuple[str, Dict[str, Any]]:
    lowered = (text or "").strip().lower()
    url_match = re.search(r"https?://\S+", text or "")
    if url_match:
        url = url_match.group(0)
        if any(word in lowered for word in ("extract", "sumarizează", "sumarizeaza", "read", "citește", "citeste", "content", "conținut", "continut")):
            return "browser_extract", {"url": url, "goal": text}
        return "browser_navigate", {"url": url}

    search_prefixes = (
        "cauta pe web",
        "caută pe web",
        "search web",
        "cauta pe internet",
        "caută pe internet",
        "search ",
        "find ",
        "cauta ",
        "caută ",
    )
    for prefix in search_prefixes:
        if lowered.startswith(prefix):
            query = text[len(prefix) :].strip(" :,-")
            return "browser_search", {"query": query or text, "limit": 5}

    return "browser_task", {"task": text, "success_criteria": {}}


def _normalize_brain_error_for_user(text: str, *, context: str = "chat") -> str:
    normalized = (text or "").strip()
    lowered = normalized.lower()
    if not normalized:
        return normalized

    if "error: brain call timed out" in lowered or "error: brain stream timed out" in lowered:
        if context == "audit":
            return (
                "Am pornit auditul, dar modelul a întârziat prea mult pe sumarul final. "
                "Verifică Mission Artifacts pentru raportul complet sau cere-mi să reiau concluziile pe scurt."
            )
        return (
            "Modelul a întârziat prea mult la această cerere. "
            "Pot relua imediat răspunsul sau îl putem reformula mai țintit."
        )

    if "error: brain call failed" in lowered or "error: brain stream failed" in lowered:
        return (
            "Am întâmpinat o problemă internă la generarea răspunsului. "
            "Pot încerca din nou imediat."
        )

    return normalized


def _looks_like_audit_mission(text: str) -> bool:
    lowered = (text or "").strip().lower()
    audit_markers = (
        "audit",
        "auditează",
        "auditeaza",
        "review",
        "revizuiește",
        "revizuieste",
        "verifică codul",
        "verifica codul",
    )
    return any(marker in lowered for marker in audit_markers)


def _describe_live_mission_start(
    mission_text: str,
    mission_preflight: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    mode = (mission_preflight or {}).get("execution_mode", "default")
    complexity = (mission_preflight or {}).get("complexity_score")
    roles = (mission_preflight or {}).get("coordinator_roles") or []

    if _looks_like_audit_mission(mission_text):
        speech = "Am pornit auditul codului meu și îți aduc concluziile aici imediat ce termin."
        chat = (
            "Am pornit auditul codului prin orchestratorul JARVIS. "
            "Îți voi afișa aici concluziile și voi salva rezultatul complet în Mission Artifacts."
        )
        return speech, chat

    if mode == "coordinator" and roles:
        speech = "Am pornit misiunea și am armat coordonarea cu agenți specializați."
        chat = (
            "Am pornit misiunea prin orchestratorul JARVIS cu preflight de coordinator. "
            f"Roluri armate: {', '.join(roles)}. "
            "Evenimentele și artefactele vor apărea în Activity, Missions și Traces."
        )
        return speech, chat

    if mode == "ultraplan":
        detail = f" (complexitate {complexity})" if complexity is not None else ""
        speech = "Am pornit misiunea și folosesc ultraplan pentru execuție mai profundă."
        chat = (
            "Am pornit misiunea prin orchestratorul JARVIS cu preflight ULTRAPLAN"
            f"{detail}. "
            "Evenimentele și artefactele vor apărea în Activity, Missions și Traces."
        )
        return speech, chat

    speech = "Am pornit misiunea în modul JARVIS și urmăresc progresul."
    chat = (
        "Am pornit misiunea prin orchestratorul JARVIS. "
        "Evenimentele și artefactele vor apărea în Activity, Missions și Traces."
    )
    return speech, chat


async def _prepare_principal_mission(
    user_goal: str,
    *,
    allow_agent_start: bool = True,
) -> Dict[str, Any]:
    preflight: Dict[str, Any] = {
        "execution_mode": "default",
        "complexity_score": None,
        "first_steps": [],
        "coordinator_armed": False,
        "coordinator_roles": [],
        "coordinator_task_specs": [],
    }

    try:
        from chat_jarvis import _get_engine

        engine = _get_engine()
    except Exception as exc:
        preflight["error"] = str(exc)
        return preflight

    if not engine or not getattr(engine, "ultraplan", None):
        return preflight

    try:
        plan_bundle = engine.ultraplan.build_plan(user_goal)
        preflight["execution_mode"] = plan_bundle.get("mode", "default")
        preflight["complexity_score"] = plan_bundle.get("complexity_score")
        preflight["first_steps"] = [
            step.get("title", "")
            for step in (plan_bundle.get("steps") or [])[:2]
            if isinstance(step, dict) and step.get("title")
        ]
    except Exception as exc:
        preflight["error"] = str(exc)
        return preflight

    if (
        allow_agent_start
        and preflight["execution_mode"] == "coordinator"
        and getattr(engine, "coordinator", None)
    ):
        try:
            preview = await engine.coordinator.prepare(user_goal)
            preflight["coordinator_armed"] = True
            preflight["coordinator_roles"] = list(preview.get("roles") or [])
            preflight["coordinator_task_specs"] = list(preview.get("task_specs") or [])
        except Exception as exc:
            preflight["coordinator_error"] = str(exc)

    return preflight


def _compose_principal_mission_goal(
    user_goal: str,
    mission_preflight: Optional[Dict[str, Any]] = None,
) -> str:
    preflight = mission_preflight or {}
    mode = preflight.get("execution_mode", "default")
    complexity = preflight.get("complexity_score")
    first_steps = preflight.get("first_steps") or []
    roles = preflight.get("coordinator_roles") or []

    if mode == "default" and not first_steps and not roles:
        return user_goal

    lines = [
        user_goal,
        "",
        "[JARVIS PRINCIPAL PREFLIGHT]",
        f"Preferred execution mode: {mode}",
    ]
    if complexity is not None:
        lines.append(f"Complexity score: {complexity}")
    if first_steps:
        lines.append(f"Priority path: {' -> '.join(first_steps)}")
    if roles:
        lines.append(f"Coordinator roles armed: {', '.join(roles)}")
    lines.append(
        "Use this as execution guidance only. Keep the original user goal authoritative."
    )
    return "\n".join(lines).strip()


async def _push_mission_preflight_event(
    mission_text: str,
    mission_preflight: Optional[Dict[str, Any]],
    *,
    session_id: Optional[str] = None,
    source: str = "chat",
) -> None:
    preflight = mission_preflight or {}
    mode = preflight.get("execution_mode", "default")
    complexity = preflight.get("complexity_score")
    first_steps = preflight.get("first_steps") or []
    roles = preflight.get("coordinator_roles") or []

    if mode == "coordinator" and roles:
        detail = (
            f"Coordinator armed ({', '.join(roles)})"
            + (f" • complexity {complexity}" if complexity is not None else "")
        )
    elif mode == "ultraplan":
        detail = (
            "ULTRAPLAN armed"
            + (f" • complexity {complexity}" if complexity is not None else "")
        )
    else:
        detail = "Default mission path"

    if first_steps:
        detail += f" • {' -> '.join(first_steps)}"

    await push_event(
        "MISSION_PREFLIGHT",
        detail,
        {
            "session_id": session_id,
            "source": source,
            "mission_text": mission_text[:160],
            "mission_preflight": preflight,
        },
    )


def _mission_run_kwargs(
    mission_text: str,
    mission_preflight: Optional[Dict[str, Any]] = None,
    execution_goal: Optional[str] = None,
) -> Dict[str, Any]:
    guidance = ""
    if execution_goal and execution_goal.strip() and execution_goal.strip() != mission_text.strip():
        guidance = execution_goal
    return {
        "user_goal": mission_text,
        "execution_guidance": guidance or None,
        "mission_preflight": mission_preflight or None,
    }


async def _run_principal_mission_sync(
    mission_text: str,
    *,
    mission_preflight: Optional[Dict[str, Any]] = None,
    execution_goal: Optional[str] = None,
) -> str:
    from functools import partial
    from core.orchestrator import run_mission

    return await asyncio.to_thread(
        partial(
            run_mission,
            **_mission_run_kwargs(
                mission_text,
                mission_preflight=mission_preflight,
                execution_goal=execution_goal,
            ),
        )
    )


def _summarize_live_mission_result(
    mission_text: str,
    result: str,
    mission_meta: Optional[Dict[str, Any]] = None,
    max_chars: int = 1400,
) -> str:
    normalized = sanitize_assistant_output(result or "", user_message=mission_text)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if not normalized:
        if _looks_like_audit_mission(mission_text):
            return "Auditul s-a încheiat, dar nu am primit încă un rezumat util. Rezultatul complet este disponibil în Mission Artifacts."
        return "Misiunea s-a încheiat. Rezultatul complet este disponibil în Mission Artifacts."

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]

    # Ignore stale history/memory recap lines when building the spoken/live summary.
    def _is_noise(line: str) -> bool:
        lowered = line.lower()
        if re.match(r"^[•\-]\s*\[[^\]]+\]\s*\(scor:\s*\d+/10\)", line, re.IGNORECASE):
            return True
        return any(
            marker in lowered
            for marker in (
                "## memory context",
                "## web / external context",
                "## historical context",
                "📊 statistici memorie",
                "📋 ultimele 3 misiuni",
                "🎓 lecții învățate",
                "success=true. steps=",
                "success=false. steps=",
            )
        )

    lines = [line for line in lines if not _is_noise(line)]
    interesting: List[str] = []
    for line in lines:
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in (
                "misiune finalizată",
                "misiune neconfirmată",
                "scor qa",
                "user goal",
                "delivery notes",
                "rezultat",
                "concluz",
                "finding",
                "issue",
                "problem",
                "success=",
                "p1 ",
                "p2 ",
                "p3 ",
                "files to review first",
            )
        ):
            interesting.append(line)
        if len(interesting) >= 6:
            break

    if not interesting:
        interesting = lines[:6]

    summary = "\n".join(interesting).strip()
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rstrip() + "…"

    if _looks_like_audit_mission(mission_text) and isinstance(mission_meta, dict):
        files = mission_meta.get("files_to_review") or []
        p1 = mission_meta.get("p1_findings") or []
        p2 = mission_meta.get("p2_findings") or []
        summary_lines = ["Am terminat auditul."]
        if files:
            summary_lines.append(f"Fișiere de revizuit întâi: {', '.join(files[:3])}.")
        if p1:
            summary_lines.append(f"P1: {p1[0]}")
        elif p2:
            summary_lines.append(f"P2: {p2[0]}")
        summary_lines.append("Raportul complet este disponibil în Mission Artifacts.")
        composed = " ".join(part.strip() for part in summary_lines if part).strip()
        if len(composed) > max_chars:
            composed = composed[: max_chars - 1].rstrip() + "…"
        return composed

    if _looks_like_audit_mission(mission_text):
        return f"Am terminat auditul. Iată concluziile inițiale:\n\n{summary}"
    return f"Am terminat misiunea. Iată rezultatul pe scurt:\n\n{summary}"


def _extract_markdown_section_bullets(text: str, heading: str, level: int = 2) -> List[str]:
    if not text:
        return []

    prefix = "#" * level
    stop_prefix = "#" * level
    next_level_prefix = "#" * max(1, level - 1)
    pattern = rf"^{re.escape(prefix)}\s+{re.escape(heading)}\s*$"
    bullets: List[str] = []
    collecting = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if re.match(pattern, line):
            collecting = True
            continue
        if collecting and (
            line.startswith(f"{stop_prefix} ")
            or (level == 3 and line.startswith("## "))
            or (level == 2 and line.startswith("# ") and not line.startswith("## "))
        ):
            break
        if collecting and line.startswith("- "):
            bullets.append(line[2:].strip())
    return bullets


def _extract_markdown_metric(text: str, label: str) -> Optional[int]:
    match = re.search(rf"- {re.escape(label)}:\s*(\d+)", text or "")
    if not match:
        return None
    return int(match.group(1))


def _extract_code_audit_metadata(result: str) -> Optional[Dict[str, Any]]:
    if not isinstance(result, str) or "# Code Audit Report" not in result:
        return None

    files_scanned = _extract_markdown_metric(result, "Files scanned")
    total_source_lines = _extract_markdown_metric(result, "Total source lines")
    files_to_review = _extract_markdown_section_bullets(result, "Files To Review First", level=2)
    p1_findings = _extract_markdown_section_bullets(result, "P1 Critical blockers", level=3)
    p2_findings = _extract_markdown_section_bullets(result, "P2 Delivery / structural risks", level=3)
    p3_findings = _extract_markdown_section_bullets(result, "P3 Follow-up / cleanup", level=3)
    todo_signals = _extract_markdown_section_bullets(result, "TODO / FIXME Signals", level=2)
    hotspot_files = _extract_markdown_section_bullets(result, "Hotspots", level=2)

    return {
        "kind": "code_audit",
        "files_scanned": files_scanned,
        "total_source_lines": total_source_lines,
        "files_to_review": files_to_review,
        "hotspot_files": hotspot_files,
        "p1_findings": p1_findings,
        "p2_findings": p2_findings,
        "p3_findings": p3_findings,
        "todo_signals": todo_signals,
    }


async def _classify_principal_intent(
    text: str,
    *,
    explicit_mode: str = "auto",
    session: Optional[Dict[str, Any]] = None,
) -> str:
    normalized_mode = (explicit_mode or "").strip().lower()
    if normalized_mode and normalized_mode not in {"auto", "voice"}:
        return normalized_mode

    lowered = (text or "").strip().lower()
    if lowered in {"stop", "stop now", "cancel", "anulează", "anuleaza", "oprește", "opreste"}:
        return "interrupt"

    if _looks_like_strong_mission_request(text):
        return "mission"

    if _looks_like_cowork_live_command(text):
        return "cowork"

    if _looks_like_computer_live_command(text):
        return "computer"

    if _looks_like_browser_live_command(text):
        return "browser"

    if await _classify_chat_mode(text) == "MISSION":
        return "mission"

    if bool((session or {}).get("cowork_active")) and len(text.split()) >= 2:
        return "cowork"

    return "chat"


async def _classify_live_turn_intent(
    req: LiveTurnRequest,
    session: Dict[str, Any],
) -> str:
    return await _classify_principal_intent(
        req.user_text,
        explicit_mode=req.mode,
        session=session,
    )


async def _interrupt_runtime(
    *,
    session: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    reason: str = "",
    source: str = "chat",
) -> Dict[str, Any]:
    interrupted: List[str] = []
    if state.is_running:
        state.cancel_requested = True
        interrupted.append("mission")

    try:
        from core.cowork_mode import get_cowork_mode

        coworker = get_cowork_mode()
        if coworker.active:
            await coworker.stop()
            interrupted.append("cowork")
    except Exception:
        pass

    if session is not None:
        session["cowork_active"] = False
        session["last_intent"] = "interrupt"
        _store_live_session_turn(
            session,
            speaker="jarvis",
            text="Am întrerupt fluxurile active.",
            payload={"interrupted": interrupted, "reason": reason},
        )

    event_name = "LIVE_SESSION_INTERRUPT" if source == "gemini-live" else "JARVIS_INTERRUPT"
    await push_event(
        event_name,
        "Gemini Live requested interrupt." if source == "gemini-live" else "JARVIS interrupt requested.",
        {"session_id": session_id, "interrupted": interrupted, "source": source},
    )
    return {
        "ok": True,
        "session_id": session_id,
        "intent": "interrupt",
        "interrupted": interrupted,
        "speech_text": "Am întrerupt ce era activ.",
        "chat_text": "Am întrerupt fluxurile active și am readus sesiunea în standby.",
    }


async def _execute_principal_nonmission(
    *,
    intent: str,
    text: str,
    session_id: Optional[str],
    source: str,
    mode_hint: str,
    permissions: Optional[Dict[str, bool]] = None,
    session: Optional[Dict[str, Any]] = None,
    screen_summary: Optional[str] = None,
    camera_summary: Optional[str] = None,
    screen_active: bool = False,
    camera_active: bool = False,
) -> Dict[str, Any]:
    effective_permissions = dict(_default_principal_permissions())
    effective_permissions.update(permissions or {})

    if intent == "interrupt":
        return await _interrupt_runtime(
            session=session,
            session_id=session_id,
            reason=f"{source} command",
            source=source,
        )

    if intent == "cowork":
        if not effective_permissions.get("allow_cowork_control", True):
            return {
                "ok": True,
                "session_id": session_id,
                "intent": "cowork",
                "requires_confirmation": True,
                "speech_text": "Pot intra în co-work, dar am nevoie de confirmare.",
                "chat_text": "Co-work este blocat de policy-ul curent. Confirmă dacă vrei să-l activez.",
            }

        result = await _call_engine_tool("cowork_command", {"command": text})
        if session is not None:
            session["cowork_active"] = True
        speech_text = sanitize_assistant_output(_live_result_text(result), user_message=text)
        chat_text = speech_text
        if session is not None:
            _store_live_session_turn(
                session,
                speaker="jarvis",
                text=chat_text,
                payload={"intent": intent, "result": result},
            )
        await push_event(
            "COWORK_COMMAND",
            f"Co-work handled {source} command: {text[:80]}",
            {"session_id": session_id, "result": result, "source": source},
        )
        return {
            "ok": True,
            "session_id": session_id,
            "intent": intent,
            "speech_text": speech_text,
            "chat_text": chat_text,
            "result": result,
        }

    if intent == "browser":
        if not effective_permissions.get("allow_browser_control", True):
            return {
                "ok": True,
                "session_id": session_id,
                "intent": "browser",
                "requires_confirmation": True,
                "speech_text": "Pot controla browserul, dar sesiunea cere confirmare.",
                "chat_text": "Browser control este blocat de policy-ul curent. Confirmă dacă vrei să continui.",
            }
        tool_name, tool_args = _select_browser_tool_call(text)
        result = await _call_engine_tool(tool_name, tool_args)
        speech_text = sanitize_assistant_output(_live_result_text(result), user_message=text)
        chat_text = speech_text
        if session is not None:
            _store_live_session_turn(
                session,
                speaker="jarvis",
                text=chat_text,
                payload={"intent": intent, "result": result},
            )
        await push_event(
            "BROWSER_TASK",
            f"{source.title()} browser task: {text[:80]}",
            {"session_id": session_id, "result": result, "source": source},
        )
        return {
            "ok": True,
            "session_id": session_id,
            "intent": intent,
            "speech_text": speech_text,
            "chat_text": chat_text,
            "result": result,
        }

    if intent == "computer":
        if not effective_permissions.get("allow_computer_control", True):
            return {
                "ok": True,
                "session_id": session_id,
                "intent": "computer",
                "requires_confirmation": True,
                "speech_text": "Pot controla computerul, dar sesiunea cere confirmare.",
                "chat_text": "Computer control este blocat de policy-ul curent. Confirmă dacă vrei să continui.",
            }
        result = await _call_engine_tool("computer_task", {"task": text})
        speech_text = sanitize_assistant_output(_live_result_text(result), user_message=text)
        chat_text = speech_text
        if session is not None:
            _store_live_session_turn(
                session,
                speaker="jarvis",
                text=chat_text,
                payload={"intent": intent, "result": result},
            )
        await push_event(
            "COMPUTER_TASK",
            f"{source.title()} computer task: {text[:80]}",
            {"session_id": session_id, "result": result, "source": source},
        )
        return {
            "ok": True,
            "session_id": session_id,
            "intent": intent,
            "speech_text": speech_text,
            "chat_text": chat_text,
            "result": result,
        }

    visual_question = source == "gemini-live" and _looks_like_visual_live_question(text)
    observed_screen_summary = None
    if visual_question and (screen_active or bool((session or {}).get("screen_active"))):
        observed_screen_summary = await _observe_local_screen_summary()

    visual_context = _compose_live_visual_context(
        screen_summary=screen_summary,
        camera_summary=camera_summary,
        screen_active=screen_active,
        camera_active=camera_active,
        session=session,
        observed_screen_summary=observed_screen_summary,
    )

    chat_input = text
    if visual_context:
        chat_input = (
            "Context vizual live pentru acest mesaj:\n"
            f"{visual_context}\n\n"
            "Instrucțiune critică: dacă acest context vizual este prezent, nu spune că nu poți vedea ecranul "
            "sau camera. Folosește contextul disponibil și spune sincer ce știi și ce nu știi.\n\n"
            f"Mesajul utilizatorului: {text}"
        )

    _resolved_session_id, chat = _get_or_create_chat_session(session_id, mode_hint=mode_hint)
    response = await chat.chat(chat_input)
    response = _normalize_brain_error_for_user(
        response,
        context="audit" if _looks_like_audit_mission(text) else "chat",
    )
    response = sanitize_assistant_output(response, user_message=text)
    if visual_context and visual_question and _looks_like_visual_denial(response):
        if screen_summary or observed_screen_summary or camera_summary:
            response = (
                "Da, am context vizual live disponibil acum. "
                f"{visual_context} "
                "Spune-mi ce vrei să verific concret și mă uit țintit."
            )
        else:
            response = (
                "Da, am sesiunea vizuală activă, dar nu am extras încă un rezumat util din cadru. "
                "Spune-mi ce zonă sau ce fereastră vrei să inspectez și continui de acolo."
            )
    if session is not None:
        _store_live_session_turn(
            session,
            speaker="jarvis",
            text=response,
            payload={"intent": "chat", "visual_context": visual_context or None},
        )
    return {
        "ok": True,
        "session_id": session_id,
        "intent": "chat",
        "speech_text": response,
        "chat_text": response,
    }


async def _route_principal_command(
    *,
    text: str,
    session_id: Optional[str] = None,
    explicit_mode: str = "auto",
    source: str = "chat",
    mode_hint: str = "chat",
    permissions: Optional[Dict[str, bool]] = None,
    session: Optional[Dict[str, Any]] = None,
    screen_summary: Optional[str] = None,
    camera_summary: Optional[str] = None,
    screen_active: bool = False,
    camera_active: bool = False,
    allow_background_mission: bool = False,
) -> Dict[str, Any]:
    intent = await _classify_principal_intent(
        text,
        explicit_mode=explicit_mode,
        session=session,
    )

    effective_permissions = dict(_default_principal_permissions())
    effective_permissions.update(permissions or {})

    if intent == "mission":
        if not effective_permissions.get("allow_agent_start", True):
            return {
                "ok": True,
                "session_id": session_id,
                "intent": "mission",
                "requires_confirmation": True,
                "speech_text": "Pot porni o misiune, dar am nevoie de confirmare pentru agenți.",
                "chat_text": "Comanda pare de tip mission. Confirmă că vrei să pornesc agenții.",
            }
        if state.is_running:
            return {
                "ok": False,
                "session_id": session_id,
                "intent": "mission",
                "status": "busy",
                "speech_text": "Am deja o misiune în execuție.",
                "chat_text": "Există deja o misiune activă. O pot întrerupe sau aștepta finalizarea ei.",
            }

        mission_preflight = await _prepare_principal_mission(
            text,
            allow_agent_start=effective_permissions.get("allow_agent_start", True),
        )

        if allow_background_mission:
            mission_task = asyncio.create_task(
                _run_live_mission_background(
                    session_id or "",
                    text,
                    mission_preflight=mission_preflight,
                )
            )
            _active_background_tasks.add(mission_task)
            mission_task.add_done_callback(_active_background_tasks.discard)
            if session is not None:
                session["last_mission_request"] = text
                session["last_mission_preflight"] = mission_preflight
                session["updated_at"] = time.time()
            speech_text, chat_text = _describe_live_mission_start(text, mission_preflight)
            if session is not None:
                _store_live_session_turn(
                    session,
                    speaker="jarvis",
                    text=chat_text,
                    payload={
                        "intent": intent,
                        "mission_started": True,
                        "mission_preflight": mission_preflight,
                    },
                )
            return {
                "ok": True,
                "session_id": session_id,
                "intent": intent,
                "mission_started": True,
                "speech_text": speech_text,
                "chat_text": chat_text,
                "ui_events": ["mission_started"],
                "mission_preflight": mission_preflight,
            }

        return {
            "ok": True,
            "session_id": session_id,
            "intent": "mission",
            "requires_mission_execution": True,
            "mission_preflight": mission_preflight,
            "mission_execution_goal": _compose_principal_mission_goal(text, mission_preflight),
        }

    return await _execute_principal_nonmission(
        intent=intent,
        text=text,
        session_id=session_id,
        source=source,
        mode_hint=mode_hint,
        permissions=effective_permissions,
        session=session,
        screen_summary=screen_summary,
        camera_summary=camera_summary,
        screen_active=screen_active,
        camera_active=camera_active,
    )


async def _run_live_mission_background(
    session_id: str,
    mission_text: str,
    *,
    mission_preflight: Optional[Dict[str, Any]] = None,
) -> None:
    result = ""
    try:
        from core.orchestrator import run_mission

        preflight = mission_preflight or await _prepare_principal_mission(mission_text)
        execution_goal = _compose_principal_mission_goal(mission_text, preflight)
        state.start_mission(mission_text)
        await _push_mission_preflight_event(
            mission_text,
            preflight,
            session_id=session_id,
            source="gemini-live",
        )
        await push_event(
            "MISSION_START",
            f"Voice mission started: {mission_text[:80]}...",
            {
                "session_id": session_id,
                "source": "gemini-live",
                "mission_preflight": preflight,
            },
        )
        result = await _run_principal_mission_sync(
            mission_text,
            mission_preflight=preflight,
            execution_goal=execution_goal,
        )
        mission_meta = _extract_code_audit_metadata(result) if _looks_like_audit_mission(mission_text) else None
        summary = _summarize_live_mission_result(mission_text, result, mission_meta=mission_meta)
        session = _live_sessions.get(session_id)
        if session is not None:
            session["last_mission_result"] = result
            session["last_mission_summary"] = summary
            session["last_mission_meta"] = mission_meta
            session["last_mission_preflight"] = preflight
            session["updated_at"] = time.time()
            _store_live_session_turn(
                session,
                speaker="jarvis",
                text=summary,
                payload={
                    "mission_result": result[:1500],
                    "mission_summary": summary,
                    "mission_meta": mission_meta,
                    "mission_preflight": preflight,
                },
            )
        await push_event(
            "MISSION_COMPLETE",
            summary,
            {
                "session_id": session_id,
                "source": "gemini-live",
                "mission_result_summary": summary,
                "mission_meta": mission_meta,
                "mission_preflight": preflight,
            },
        )
    except Exception as exc:
        session = _live_sessions.get(session_id)
        if session is not None:
            session["last_error"] = str(exc)
            session["updated_at"] = time.time()
        await push_event(
            "MISSION_ERROR",
            str(exc),
            {"session_id": session_id, "source": "gemini-live"},
        )
    finally:
        state.end_mission(result)


def _get_live_chat(session: Dict[str, Any]):
    _resolved_session_id, chat = _get_or_create_chat_session(
        session.get("session_id"),
        mode_hint="live_voice",
    )
    session["jarvis_chat"] = chat
    return chat


async def _call_engine_tool(tool_name: str, arguments: Optional[Dict[str, Any]] = None):
    """Route runtime actions through the engine MCP registry, not ad-hoc side paths."""
    try:
        from chat_jarvis import _get_engine

        engine = _get_engine()
    except Exception as exc:
        return {"error": "Engine unavailable.", "details": str(exc)}

    if not engine:
        return {"error": "Engine unavailable."}

    result = await engine.mcp.call_tool(tool_name, arguments or {})

    # Mirror the same output budgeting discipline used by JarvisChat tool execution.
    try:
        rendered = (
            json.dumps(result, ensure_ascii=False)
            if isinstance(result, (dict, list))
            else str(result)
        )
        budget = getattr(engine, "result_budget", None)
        if budget:
            budgeted = budget.check_limit(tool_name, rendered)
            if budgeted.get("allowed") and budgeted.get("persisted"):
                result = {
                    "summary": budgeted.get("content", rendered),
                    "persisted_file": budgeted.get("file"),
                    "truncated": True,
                }
    except Exception:
        pass

    return result


@app.get("/api/autonomy/thoughts")
async def get_autonomy_thoughts():
    """Retrieve JARVIS's proactive subconscious thoughts."""
    try:
        from core.autonomy_daemon import jarvis_daemon

        thoughts = jarvis_daemon.get_recent_thoughts()
        return {
            "thoughts": thoughts,
            "count": len(thoughts),
            "daemon_active": jarvis_daemon.is_running,
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "thoughts": []}


TRIAGE_TIMEOUT_SEC = float(os.getenv("JARVIS_CHAT_TRIAGE_TIMEOUT_SEC", "4"))
SIMPLE_CHAT_PREFIXES = (
    "salut",
    "hello",
    "hi",
    "hey",
    "bună",
    "buna",
    "ce faci",
    "cine esti",
    "cine ești",
)
MISSION_MARKERS = (
    "[misiune autonomă]",
    "construiește",
    "construieste",
    "implementează",
    "implementeaza",
    "scrie cod",
    "write code",
    "research",
    "caută pe web",
    "cauta pe web",
    "audit complet",
    "rulează un audit",
    "ruleaza un audit",
    "audit al propriului",
    "audit al propriului tău cod",
    "audit al propriului tau cod",
    "auditează-ți codul",
    "auditeaza-ti codul",
)

STRONG_MISSION_MARKERS = (
    "[misiune autonomă]",
    "construiește",
    "construieste",
    "implementează",
    "implementeaza",
    "scrie cod",
    "write code",
    "audit complet",
    "rulează un audit",
    "ruleaza un audit",
    "audit al propriului",
    "audit al propriului tău cod",
    "audit al propriului tau cod",
    "auditează-ți codul",
    "auditeaza-ti codul",
)


def _fast_path_chat_mode(message: str) -> str | None:
    text = (message or "").strip().lower()
    if not text:
        return "CHAT"
    if len(text) <= 24 and any(text.startswith(prefix) for prefix in SIMPLE_CHAT_PREFIXES):
        return "CHAT"
    if any(marker in text for marker in MISSION_MARKERS):
        return "MISSION"
    return None


def _default_principal_permissions() -> Dict[str, bool]:
    return {
        "allow_agent_start": True,
        "allow_browser_control": True,
        "allow_computer_control": True,
        "allow_cowork_control": True,
    }


def _looks_like_strong_mission_request(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return any(marker in lowered for marker in STRONG_MISSION_MARKERS)


async def _call_brain_for_triage(message: str) -> str:
    from core.brain import call_brain, CHEAP_MODEL

    system_eval = (
        "Ești routerul central J.A.R.V.I.S. Analizează mesajul utilizatorului.\n"
        "Dacă cere codare complexă, creare de aplicații, arhitectură, research pe web invaziv sau are tag-ul [Misiune Autonomă] -> Răspunde STRICT 'MISSION'.\n"
        "Dacă este o simplă întrebare teoretică, salut creativ, clarificare sumară de chat -> Răspunde STRICT 'CHAT'."
    )

    return await call_brain(
        [
            {"role": "system", "content": system_eval},
            {"role": "user", "content": message},
        ],
        model=CHEAP_MODEL,
        profile="precise",
    )


async def _classify_chat_mode(message: str, timeout_sec: float = TRIAGE_TIMEOUT_SEC) -> str:
    fast_path = _fast_path_chat_mode(message)
    if fast_path:
        return fast_path

    try:
        classification = await asyncio.wait_for(
            _call_brain_for_triage(message),
            timeout=timeout_sec,
        )
        normalized = (classification or "").upper()
        if "MISSION" in normalized:
            return "MISSION"
    except TimeoutError:
        logger.warning("[BRIDGE] Chat triage timed out; falling back to CHAT.")
    except Exception as exc:
        logger.warning("[BRIDGE] Chat triage failed; falling back to CHAT: %s", exc)

    return "CHAT"


@app.get("/api/graph")
async def get_knowledge_graph():
    """Returns the visual node map of JARVIS's entire memory banks."""
    vault_path = str(OBSIDIAN_VAULT_PATH)
    nodes = []
    links = []
    node_set = set()

    if not os.path.exists(vault_path):
        print(f"⚠️ [GRAPH ERROR] Vault path not found: {vault_path}")
        return {"nodes": [{"id": "Core", "label": "No Data", "group": 1}], "links": []}

    print(f"📂 [GRAPH] Scanning vault at: {vault_path}...")
    try:
        found_md = 0
        for root, dirs, files in os.walk(vault_path):
            for file in files:
                if file.endswith(".md"):
                    found_md += 1
                    file_name = file.replace(".md", "")
                    node_set.add(file_name)
                    nodes.append({"id": file_name, "label": file_name, "group": 1})
        print(f"✅ [GRAPH] Found {found_md} markdown files.")

        # Reset and do second pass for links to avoid missing nodes
        for root, dirs, files in os.walk(vault_path):
            for file in files:
                if file.endswith(".md"):
                    file_name = file.replace(".md", "")
                    with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                        content = f.read()
                        linked_matches = re.findall(r"\[\[(.*?)\]\]", content)
                        for match in linked_matches:
                            target = match.split("|")[0].strip()
                            links.append({"source": file_name, "target": target})
                            node_set.add(target)

        # Create virtual nodes for links that don't have concrete files yet
        existing_nodes = {n["id"] for n in nodes}
        for n in node_set:
            if n not in existing_nodes:
                nodes.append({"id": n, "label": n, "group": 2})  # Group 2 = Ghost Nodes

        # ── Calculate Node Degree (Importance) ──
        node_vals = {n["id"]: 1 for n in nodes}
        for l in links:
            if l["target"] in node_vals:
                node_vals[l["target"]] += 1
            if l["source"] in node_vals:
                node_vals[l["source"]] += 0.5

        for n in nodes:
            n["val"] = node_vals.get(n["id"], 1)

        return {"nodes": nodes, "links": links}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Primary chat surface for JARVIS.

    Uses mission routing for explicit execution requests and a persistent
    JarvisChat agentic session for normal conversation.
    """
    # Ping sensory awareness
    try:
        from core.autonomy_daemon import jarvis_daemon

        jarvis_daemon.ping_user_activity()
    except Exception as e:
        pass

    routed = await _route_principal_command(
        text=req.message,
        session_id=req.session_id,
        source="chat",
        mode_hint="chat",
    )

    if routed.get("requires_mission_execution"):
        if state.is_running:
            return {"error": "A mission is already running.", "status": "busy"}

        state.start_mission(req.message)
        mission_preflight = routed.get("mission_preflight")
        execution_goal = routed.get("mission_execution_goal")
        await _push_mission_preflight_event(
            req.message,
            mission_preflight,
            source="chat",
        )
        await push_event(
            "MISSION_START",
            f"🛸 Flota de Agenți activată pentru: {req.message[:50]}...",
        )

        if req.stream:
            return StreamingResponse(
                _stream_mission(
                    req.message,
                    180,
                    mission_preflight=mission_preflight,
                    execution_goal=execution_goal,
                ),
                media_type="text/event-stream",
            )

        result = await _run_principal_mission_sync(
            req.message,
            mission_preflight=mission_preflight,
            execution_goal=execution_goal,
        )
        state.end_mission(result)
        await push_event("MISSION_COMPLETE", "Misiunea agentică finalizată.")
        return {"result": result, "status": "done"}

    if req.stream:
        return StreamingResponse(
            _stream_principal_result(routed, req.voice),
            media_type="text/event-stream",
        )

    result_text = (routed.get("chat_text") or routed.get("speech_text") or "").strip()
    if req.voice and result_text:
        from core.os_sovereign import OSSovereign

        task = asyncio.create_task(OSSovereign().say(result_text))
        _active_voice_tasks.add(task)
        task.add_done_callback(_active_voice_tasks.discard)

    if not routed.get("ok", True):
        return {
            "error": routed.get("chat_text") or routed.get("speech_text") or "JARVIS routing failed.",
            "status": routed.get("status", "error"),
            "intent": routed.get("intent"),
        }

    return {
        "result": result_text,
        "status": routed.get("status", "done"),
        "intent": routed.get("intent"),
        "requires_confirmation": bool(routed.get("requires_confirmation")),
        "details": routed.get("result"),
    }


@app.post("/api/live/session/start")
async def start_live_session(req: LiveSessionStartRequest):
    session_id = _new_live_session_id()
    session = {
        "session_id": session_id,
        "source": req.source,
        "mode": req.mode,
        "created_at": time.time(),
        "updated_at": time.time(),
        "permissions": {
            "allow_agent_start": req.allow_agent_start,
            "allow_browser_control": req.allow_browser_control,
            "allow_computer_control": req.allow_computer_control,
            "allow_cowork_control": req.allow_cowork_control,
        },
        "transcript": [],
        "last_intent": "idle",
        "cowork_active": False,
        "last_error": None,
    }
    _live_sessions[session_id] = session
    await push_event(
        "LIVE_SESSION_START",
        "Gemini Live session attached to JARVIS.",
        {"session_id": session_id, "source": req.source},
    )
    return {
        "ok": True,
        "session_id": session_id,
        "mode": req.mode,
        "permissions": session["permissions"],
    }


@app.get("/api/live/session/status")
async def get_live_session_status(session_id: str):
    session = _live_sessions.get(session_id)
    if not session:
        return {"ok": False, "error": "Live session not found."}
    return {
        "ok": True,
        "session_id": session_id,
        "source": session.get("source"),
        "mode": session.get("mode"),
        "updated_at": session.get("updated_at"),
        "last_intent": session.get("last_intent"),
        "permissions": session.get("permissions"),
        "cowork_active": bool(session.get("cowork_active")),
        "last_error": session.get("last_error"),
        "last_mission_request": session.get("last_mission_request"),
        "last_mission_summary": session.get("last_mission_summary"),
        "last_mission_result": session.get("last_mission_result"),
        "last_mission_meta": session.get("last_mission_meta"),
        "transcript_count": len(session.get("transcript") or []),
        "mission_running": state.is_running,
    }


@app.post("/api/live/session/interrupt")
async def interrupt_live_session(req: LiveSessionControlRequest):
    session = _live_sessions.get(req.session_id)
    if not session:
        return {"ok": False, "error": "Live session not found."}
    return await _interrupt_runtime(
        session=session,
        session_id=req.session_id,
        reason=req.reason,
        source="gemini-live",
    )


@app.post("/api/live/session/stop")
async def stop_live_session(req: LiveSessionControlRequest):
    session = _live_sessions.get(req.session_id)
    if not session:
        return {"ok": False, "error": "Live session not found."}

    await interrupt_live_session(req)
    _live_sessions.pop(req.session_id, None)
    await push_event(
        "LIVE_SESSION_STOP",
        "Gemini Live session detached from JARVIS.",
        {"session_id": req.session_id},
    )
    return {"ok": True, "session_id": req.session_id, "status": "stopped"}


@app.post("/api/live/session/turn")
async def live_session_turn(req: LiveTurnRequest):
    session = _live_sessions.get(req.session_id)
    if not session:
        return {"ok": False, "error": "Live session not found.", "status": "missing_session"}

    text = (req.user_text or "").strip()
    if not text:
        return {"ok": False, "error": "No user_text provided.", "status": "empty"}

    permissions = _live_session_permissions(session, req)
    session["permissions"] = permissions
    session["source"] = req.source
    session["screen_active"] = bool(req.screen_active)
    session["camera_active"] = bool(req.camera_active)
    session["updated_at"] = time.time()
    _store_live_session_turn(
        session,
        speaker="user",
        text=text,
        payload={
            "screen_summary": req.screen_summary,
            "camera_summary": req.camera_summary,
            "screen_active": req.screen_active,
            "camera_active": req.camera_active,
        },
    )

    routed = await _route_principal_command(
        text=text,
        session_id=req.session_id,
        explicit_mode=req.mode,
        source=req.source,
        mode_hint="live_voice",
        permissions=permissions,
        session=session,
        screen_summary=req.screen_summary,
        camera_summary=req.camera_summary,
        screen_active=req.screen_active,
        camera_active=req.camera_active,
        allow_background_mission=True,
    )
    session["last_intent"] = routed.get("intent", "chat")
    return routed


# Global set to hold strong references to background audio tasks
_active_voice_tasks = set()


async def _stream_principal_result(payload: Dict[str, Any], voice_enabled: bool = False):
    """Stream a routed principal-command result back to the main chat UI."""
    try:
        full_response = (
            payload.get("chat_text")
            or payload.get("speech_text")
            or payload.get("error")
            or "JARVIS did not return a response."
        )
        full_response = str(full_response).strip()
        for chunk in chunk_text(full_response):
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

        if voice_enabled and full_response:
            pure_text = re.sub(r"```.*?```", "", full_response, flags=re.DOTALL)

            from core.os_sovereign import OSSovereign

            task = asyncio.create_task(OSSovereign().say(pure_text.strip()))
            _active_voice_tasks.add(task)
            task.add_done_callback(_active_voice_tasks.discard)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    finally:
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


async def _stream_chat(
    message: str,
    voice_enabled: bool = False,
    *,
    session_id: Optional[str] = None,
):
    """Backward-compatible wrapper for chat streaming through the principal router."""
    routed = await _route_principal_command(
        text=message,
        session_id=session_id,
        source="chat",
        mode_hint="chat",
    )
    async for event in _stream_principal_result(routed, voice_enabled):
        yield event


async def _stream_mission(
    mission: str,
    timeout_seconds: int,
    *,
    mission_preflight: Optional[Dict[str, Any]] = None,
    execution_goal: Optional[str] = None,
):
    """Generator that streams mission output as SSE events."""
    buffer: list[str] = []
    try:
        from core.orchestrator import run_mission_stream

        async for chunk in run_mission_stream(
            **_mission_run_kwargs(
                mission,
                mission_preflight=mission_preflight,
                execution_goal=execution_goal,
            )
        ):
            if state.cancel_requested:
                yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
                break
            buffer.append(chunk)
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

    except asyncio.TimeoutError:
        yield f"data: {json.dumps({'type': 'timeout', 'message': f'Timeout after {timeout_seconds}s'})}\n\n"
    except ImportError:
        # Fallback: run_mission_stream not available, use sync
        try:
            result = await _run_principal_mission_sync(
                mission,
                mission_preflight=mission_preflight,
                execution_goal=execution_goal,
            )
            buffer.append(result)
            yield f"data: {json.dumps({'type': 'chunk', 'content': result})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    finally:
        full_result = "".join(buffer)
        state.end_mission(full_result)
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


@app.post("/api/mission/cancel")
async def cancel_mission():
    if not state.is_running:
        return {"status": "idle", "message": "No mission running."}
    state.cancel_requested = True
    await push_event("MISSION_CANCEL", "Cancel requested by user.")
    return {"status": "cancelling"}


@app.get("/api/status")
async def get_status():
    status = {
        "is_running": state.is_running,
        "current_mission": state.current_mission,
        "uptime_sec": round(time.time() - state.start_time, 1)
        if state.start_time
        else 0,
        "connected_clients": len(manager.active_connections),
        "total_missions": len(state.history),
    }
    try:
        from tools.browser_agent import get_browser_agent

        status["browser"] = get_browser_agent().get_status()
    except Exception:
        pass
    try:
        from tools.stagehand_browser import get_stagehand_browser

        status["stagehand"] = get_stagehand_browser().get_status()
    except Exception:
        pass
    try:
        from tools.voice_cascade import get_voice_cascade

        status["voice"] = get_voice_cascade().get_status()
    except Exception:
        pass
    return status


@app.get("/api/history")
async def get_history():
    return {"missions": list(reversed(state.history))}


# ═══════════════════════════════════════════════════════════════
#  NEW FEATURES API ENDPOINTS
# ═══════════════════════════════════════════════════════════════


@app.get("/api/skills")
async def get_skills():
    """Get all available skills."""
    try:
        from core.self_evolving_skills import SelfEvolvingSkills

        skills = SelfEvolvingSkills()
        return {"skills": skills.store.get_all_skills()[:20]}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/skills/search")
async def search_skills(q: str):
    """Search skills."""
    try:
        from core.self_evolving_skills import SelfEvolvingSkills

        skills = SelfEvolvingSkills()
        result = await skills.find_skill(q)
        if result:
            return {
                "name": result.name,
                "description": result.description,
                "quality": result.quality_score,
            }
        return {"message": "No matching skills"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/skills/status")
async def get_skills_status():
    """Get skills engine status."""
    try:
        from core.self_evolving_skills import SelfEvolvingSkills

        skills = SelfEvolvingSkills()
        return skills.get_skill_status()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/memory/observations")
async def get_observations(limit: int = 15):
    """Get recent observations from observational memory."""
    try:
        from core.observational_memory import ObservationalMemory

        mem = ObservationalMemory()
        obs = mem.observer.get_recent_observations(limit=limit)
        return {
            "count": len(obs),
            "observations": [
                {
                    "type": o.observation_type.value,
                    "importance": o.importance,
                    "content": o.content[:200],
                }
                for o in obs
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/memory/stats")
async def get_memory_stats():
    """Get observational memory statistics."""
    try:
        from core.observational_memory import ObservationalMemory

        mem = ObservationalMemory()
        return mem.get_stats()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/memory/context")
async def get_memory_context():
    """Get dense context from observational memory."""
    try:
        from core.observational_memory import ObservationalMemory

        mem = ObservationalMemory()
        return {"context": mem.get_context_for_llm()}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/memory/structured/summary")
async def get_structured_memory_summary():
    """Get summary counts and previews for the 4-type memory system."""
    try:
        from tools.memory_tool import StructuredMemory, load_lessons, load_memory

        memory = StructuredMemory()
        short_term = memory.recall_short_term(limit=10)
        entities = memory.recall_entity()
        episodic = memory.recall_episodic(limit=10)
        long_term = load_memory()
        lessons = load_lessons()

        return {
            "counts": {
                "short_term": len(short_term),
                "long_term": len(long_term),
                "entity": len(entities),
                "episodic": len(episodic),
                "lessons": len(lessons),
            },
            "recent_short_term": short_term[-3:],
            "top_entities": entities[:5],
            "recent_episodic": episodic[:5],
            "full_context": memory.get_full_context(session_id="chat")[:1500],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/identity-anchor")
async def get_identity_anchor():
    """Get the persisted identity anchor and context priorities."""
    try:
        from core.identity_context import IdentityContextManager

        manager = IdentityContextManager(
            os.path.join(PROJECT_ROOT, ".agent", "brain_vault"),
            PROJECT_ROOT,
        )
        return manager.summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/runtime/cockpit")
async def get_runtime_cockpit():
    """Aggregate runtime intel for the dashboard."""
    if _knowledge_graph_age_sec() > KNOWLEDGE_GRAPH_CACHE_TTL_SEC and not _knowledge_graph_cache["refreshing"]:
        asyncio.create_task(_refresh_knowledge_graph_stats_cache())

    cached = _runtime_cockpit_cache.get("data")
    age_sec = _runtime_cockpit_age_sec()

    if cached and age_sec <= COCKPIT_CACHE_TTL_SEC:
        return {
            **cached,
            "refreshing": _runtime_cockpit_cache["refreshing"],
            "cached": True,
            "age_sec": round(age_sec, 1),
        }

    if not _runtime_cockpit_cache["refreshing"]:
        asyncio.create_task(_refresh_runtime_cockpit_cache())

    if cached:
        payload = dict(cached)
        payload.update(
            {
                "refreshing": True,
                "cached": True,
                "stale": True,
                "age_sec": round(age_sec, 1),
            }
        )
        if _runtime_cockpit_cache.get("error"):
            payload["error"] = _runtime_cockpit_cache["error"]
        return payload

    return {
        "refreshing": True,
        "cached": False,
        "identity": {"agent_name": "J.A.R.V.I.S.", "codename": "Booting"},
        "structured_memory": {"counts": {}, "memory_signal": "Runtime snapshot warming up."},
        "planning": {"modes": ["default", "ultraplan", "coordinator"]},
        "sessions": [],
        "tracing": {"total_spans": 0, "by_kind": {}, "by_status": {}},
        "skill_library": {"count": 0, "categories": []},
        "skill_governance": {
            "active_skills": 0,
            "total_skills": 0,
            "lifecycle_counts": {},
            "proposal_summary": {},
            "promotion_history": [],
            "recent_proposals": [],
            "recent_governance": [],
        },
        "neuro": {
            "mode": "shadow",
            "temporal_events": 0,
            "belief_entropy": 0,
            "routes_tracked": 0,
            "recent_sequence": [],
            "routing_summary": [],
            "event_gate": {"total_events": 0, "total_fires": 0, "fire_rate": 0},
            "maintenance": {
                "governance_events": 0,
                "promotion_events": 0,
                "anomaly_events": 0,
                "alert_events": 0,
                "recent_governance": [],
                "recent_promotions": [],
                "recent_anomalies": [],
                "recent_alerts": [],
            },
        },
        "knowledge_graph": _load_knowledge_graph_stats_snapshot(),
        "latest_mission": {
            "definition_of_done": None,
            "governance_signal": None,
            "post_mission_governance": None,
            "mission_closure": None,
        },
        "harness": {
            "retry": True,
            "timeout": True,
            "fallback": True,
            "circuit_breaker": True,
        },
        **({"error": _runtime_cockpit_cache["error"]} if _runtime_cockpit_cache.get("error") else {}),
}


@app.get("/api/governance/recent")
async def get_recent_governance(
    limit: int = 10,
    proposal_status: str = "all",
    target_type: str = "all",
    action: str = "all",
    gate_decision: str = "all",
    sort_by: str = "priority",
    human_only: bool = False,
    query: str = "",
):
    """Expose recent proposal/gate decisions without rebuilding the whole cockpit."""
    capped_limit = max(1, min(int(limit), 50))
    normalized_query = query.strip()
    policy = {
        "manual_approval_scope": "skill proposals only",
        "supported_actions": ["approve", "queue_eval", "hold", "reject"],
        "presets": _governance_policy_presets(),
        "filter_options": {
            "proposal_status": [
                "all",
                "drafted",
                "queued_for_eval",
                "eval_running",
                "eval_passed",
                "eval_failed",
                "on_hold",
                "promoted",
                "rejected",
            ],
            "target_type": ["all", "skill", "prompt", "routing", "eval_policy"],
            "gate_decision": ["all", "promote", "hold", "reject"],
            "action": ["all", "approve", "queue_eval", "hold", "reject", "capture", "fix"],
            "sort_by": ["priority", "newest", "expected_gain", "eval_score"],
        },
    }
    try:
        from core.self_evolving_skills import SelfEvolvingSkills

        skills = SelfEvolvingSkills(os.path.join(PROJECT_ROOT, ".jarvis", "skills"))
        status = skills.get_skill_status()
        filtered_proposals = _filter_recent_proposals(
            status.get("recent_proposals", []),
            proposal_status=proposal_status,
            target_type=target_type,
            query=normalized_query,
        )
        recent_proposals = _sort_recent_proposals(filtered_proposals, sort_by)[:capped_limit]
        approval_queue = _build_approval_queue(filtered_proposals)[:capped_limit]
        recent_governance = _filter_governance_history(
            _load_governance_history(limit=max(capped_limit * 3, 20)),
            action=action,
            gate_decision=gate_decision,
            human_only=human_only,
            query=normalized_query,
        )[:capped_limit]
        return {
            "recent_proposals": recent_proposals,
            "approval_queue": approval_queue,
            "recent_governance": recent_governance,
            "promotion_history": status.get("promotion_history", [])[:capped_limit],
            "proposal_summary": status.get("proposal_summary", {}),
            "policy": policy,
            "filters": {
                "proposal_status": proposal_status,
                "target_type": target_type,
                "action": action,
                "gate_decision": gate_decision,
                "sort_by": sort_by,
                "human_only": human_only,
                "query": normalized_query,
            },
        }
    except Exception as exc:
        logger.warning("[BRIDGE] Governance recent fetch failed: %s", exc)
        return {
            "recent_proposals": [],
            "approval_queue": [],
            "recent_governance": _filter_governance_history(
                _load_governance_history(limit=max(capped_limit * 3, 20)),
                action=action,
                gate_decision=gate_decision,
                human_only=human_only,
                query=normalized_query,
            )[:capped_limit],
            "promotion_history": [],
            "proposal_summary": {},
            "policy": policy,
            "filters": {
                "proposal_status": proposal_status,
                "target_type": target_type,
                "action": action,
                "gate_decision": gate_decision,
                "sort_by": sort_by,
                "human_only": human_only,
                "query": normalized_query,
            },
            "error": str(exc),
        }


@app.get("/api/neuro/maintenance")
async def get_neuro_maintenance(limit: int = 10):
    """Expose the safe maintenance journal around the neuro runtime."""
    capped_limit = max(1, min(int(limit), 50))
    try:
        from core.neuro_maintenance import NeuroMaintenanceJournal

        return NeuroMaintenanceJournal(Path(PROJECT_ROOT) / ".agent" / "neuro").status(limit=capped_limit)
    except Exception as exc:
        logger.warning("[BRIDGE] Neuro maintenance fetch failed: %s", exc)
        return {"error": str(exc)}


@app.post("/api/governance/proposal/action")
async def governance_proposal_action(req: GovernanceProposalActionRequest):
    """Apply a safe human action to a proposal without bypassing the promotion gate."""
    normalized_action = req.action.strip().lower()
    try:
        from core.improvement_proposals import get_proposals

        proposals = get_proposals(str(Path(PROJECT_ROOT) / ".agent" / "proposals"))
        proposal = proposals.get(req.proposal_id)
        if not proposal:
            return {"error": f"Unknown proposal: {req.proposal_id}"}

        reason = req.reason.strip()
        approved_by = req.approved_by.strip() or "operator"
        gate_decision = None
        candidate_skill_name = proposal.proposal_summary
        extra: Dict[str, Any] = {}
        if normalized_action == "queue_eval":
            updated = proposals.queue_for_eval(req.proposal_id, eval_run_id=reason)
        elif normalized_action == "hold":
            updated = proposals.mark_on_hold(req.proposal_id, reason or "Held by operator")
            gate_decision = "hold"
        elif normalized_action == "reject":
            updated = proposals.reject(req.proposal_id, reason or "Rejected by operator")
            gate_decision = "reject"
        elif normalized_action == "approve":
            from core.self_evolving_skills import SelfEvolvingSkills

            skills = SelfEvolvingSkills(os.path.join(PROJECT_ROOT, ".jarvis", "skills"))
            approval = skills.human_approve_proposal(
                req.proposal_id,
                approved_by=approved_by,
                reason=reason or "Approved by operator",
            )
            updated = proposals.get(req.proposal_id)
            gate_decision = approval.get("decision")
            candidate_skill_name = approval.get("skill_name") or candidate_skill_name
            extra = {
                "gate": approval.get("gate"),
                "skill_id": approval.get("skill_id"),
                "skill_name": approval.get("skill_name"),
                "family_id": approval.get("family_id"),
            }
        else:
            return {"error": f"Unsupported proposal action: {req.action}"}

        _record_manual_governance_audit(
            {
                "mission_id": f"manual:{updated.proposal_id}",
                "recorded_at": datetime.now().isoformat(),
                "action": normalized_action,
                "status": str(updated.status.value),
                "gate_decision": gate_decision,
                "gate_reason": reason or None,
                "candidate_skill_name": candidate_skill_name,
                "proposal_summary": proposal.proposal_summary,
                "proposal_id": updated.proposal_id,
                "approved_by": approved_by,
                "quality_score": updated.eval_score,
                "governance_signal": {
                    "human_action": True,
                    "approved_by": approved_by,
                    "proposal_status": str(updated.status.value),
                },
            }
        )

        await push_event(
            "GOVERNANCE_ACTION",
            f"{normalized_action.upper()} → {updated.proposal_summary[:80]}",
            {
                "proposal_id": updated.proposal_id,
                "status": str(updated.status.value),
                "action": normalized_action,
                "approved_by": approved_by,
            },
        )
        return {
            "ok": True,
            "proposal": updated.as_dict(),
            "action": normalized_action,
            **extra,
        }
    except Exception as exc:
        logger.warning("[BRIDGE] Governance proposal action failed: %s", exc)
        return {"error": str(exc)}


@app.post("/api/governance/proposal/bulk-action")
async def governance_bulk_proposal_action(req: GovernanceBulkActionRequest):
    """Apply a single safe human action to multiple proposals."""
    proposal_ids = [proposal_id.strip() for proposal_id in req.proposal_ids if proposal_id.strip()]
    if not proposal_ids:
        return {"error": "No proposal IDs provided."}

    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for proposal_id in proposal_ids[:25]:
        result = await governance_proposal_action(
            GovernanceProposalActionRequest(
                proposal_id=proposal_id,
                action=req.action,
                reason=req.reason,
                approved_by=req.approved_by,
            )
        )
        if result.get("error"):
            errors.append({"proposal_id": proposal_id, "error": result["error"]})
        else:
            results.append(result)

    return {
        "ok": bool(results) and not errors,
        "action": req.action.strip().lower(),
        "processed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


@app.get("/api/governance/export")
async def governance_export(
    format: str = "markdown",
    limit: int = 20,
    proposal_status: str = "all",
    target_type: str = "all",
    action: str = "all",
    gate_decision: str = "all",
    sort_by: str = "priority",
    human_only: bool = False,
    query: str = "",
):
    """Export governance state plus latest mission closure for operator review."""
    recent = await get_recent_governance(
        limit=limit,
        proposal_status=proposal_status,
        target_type=target_type,
        action=action,
        gate_decision=gate_decision,
        sort_by=sort_by,
        human_only=human_only,
        query=query,
    )
    cockpit = _build_runtime_cockpit_sync()
    payload = {
        **recent,
        "latest_mission": cockpit.get("latest_mission", {}),
        "generated_at": datetime.now().isoformat(),
    }
    export_format = format.strip().lower()
    if export_format == "json":
        return {
            "format": "json",
            "content": json.dumps(payload, indent=2, ensure_ascii=False),
            "summary": "Governance export ready",
        }
    return {
        "format": "markdown",
        "content": _build_governance_export_markdown(payload),
        "summary": "Governance export ready",
    }


@app.post("/api/planning/preview")
async def get_planning_preview(req: PlanningPreviewRequest):
    """Preview ULTRAPLAN + coordinator routing for a task without executing it."""
    try:
        from core.ultraplan import UltraPlanner
        from core.coordinator_mode import CoordinatorMode
        from core.auto_agents import AutoAgentsManager

        async def preview_executor(system_prompt: str, user_prompt: str) -> str:
            return f"preview::{user_prompt[:60]}"

        planner = UltraPlanner()
        coordinator = CoordinatorMode(AutoAgentsManager(preview_executor), planner)
        prepared = await coordinator.prepare(req.task)
        plan = planner.build_plan(req.task)

        return {
            "task": req.task,
            "recommended_mode": prepared["mode"],
            "complexity_score": plan["complexity_score"],
            "plan": plan,
            "roles": prepared["roles"],
            "task_specs": prepared["task_specs"],
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/planning/ultraplan")
async def run_ultraplan_preview(req: PlanningPreviewRequest):
    """Build a direct ULTRAPLAN bundle for the requested task."""
    try:
        from core.ultraplan import UltraPlanner

        planner = UltraPlanner()
        plan = planner.build_plan(req.task)
        await push_event("ULTRAPLAN_READY", f"ULTRAPLAN built for: {req.task[:80]}")
        return {
            "task": req.task,
            "recommended_mode": "ultraplan",
            "complexity_score": plan.get("complexity_score"),
            "plan": plan,
            "roles": [],
            "task_specs": [],
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/planning/coordinator/prepare")
async def prepare_coordinator_preview(req: PlanningPreviewRequest):
    """Prepare coordinator mode explicitly for the requested task."""
    try:
        from core.ultraplan import UltraPlanner
        from core.coordinator_mode import CoordinatorMode
        from core.auto_agents import AutoAgentsManager

        async def preview_executor(system_prompt: str, user_prompt: str) -> str:
            del system_prompt
            return f"preview::{user_prompt[:60]}"

        planner = UltraPlanner()
        coordinator = CoordinatorMode(AutoAgentsManager(preview_executor), planner)
        prepared = await coordinator.prepare(req.task)
        plan = planner.build_plan(req.task)
        await push_event(
            "COORDINATOR_READY",
            f"Coordinator prepared for: {req.task[:80]}",
        )
        return {
            "task": req.task,
            "recommended_mode": prepared.get("mode", "coordinator"),
            "complexity_score": plan.get("complexity_score"),
            "plan": plan,
            "roles": prepared.get("roles", []),
            "task_specs": prepared.get("task_specs", []),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/sessions")
async def get_runtime_sessions(limit: int = 20):
    """List recent persisted runtime sessions."""
    try:
        from core.session_runtime import SessionRuntime

        runtime = SessionRuntime(Path(PROJECT_ROOT) / ".agent/brain_vault")
        return {"sessions": runtime.list_sessions(limit=limit)}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/sessions/current")
async def get_current_runtime_session():
    """Return the most recently updated runtime session."""
    try:
        from core.session_runtime import SessionRuntime

        runtime = SessionRuntime(Path(PROJECT_ROOT) / ".agent/brain_vault")
        sessions = runtime.list_sessions(limit=1)
        return {"session": sessions[0] if sessions else None}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/sessions/resume")
async def resume_runtime_session(req: SessionResumeRequest):
    """Resume a persisted runtime session, preferring the live engine when available."""
    try:
        try:
            from chat_jarvis import _get_engine

            engine = _get_engine()
            if engine:
                resumed = await engine._session_resume(req.session_id)
                await push_event(
                    "SESSION_RESUME", f"Resumed runtime session: {req.session_id}"
                )
                return resumed
        except Exception:
            pass

        from core.session_runtime import SessionRuntime

        runtime = SessionRuntime(Path(PROJECT_ROOT) / ".agent/brain_vault")
        resumed = runtime.resume(req.session_id)
        await push_event(
            "SESSION_RESUME", f"Resumed persisted session: {req.session_id}"
        )
        return resumed
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/plan/notebook")
async def get_plan_notebook_summary():
    """Expose the persisted plan notebook summary."""
    try:
        from core.plan_notebook import PlanNotebook

        notebook = PlanNotebook(Path(PROJECT_ROOT) / ".agent/brain_vault")
        return notebook.summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tracing/summary")
async def get_tracing_summary():
    """Get aggregate trace statistics from the local runtime."""
    try:
        from core.tracing_runtime import JarvisTracer

        tracer = JarvisTracer(Path(PROJECT_ROOT) / ".agent/brain_vault")
        return tracer.summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tracing/recent")
async def get_recent_traces(limit: int = 25, kind: str = "", status: str = ""):
    """Inspect recent trace spans."""
    try:
        from core.tracing_runtime import JarvisTracer

        tracer = JarvisTracer(Path(PROJECT_ROOT) / ".agent/brain_vault")
        return {
            "spans": tracer.recent(
                limit=limit,
                kind=kind or None,
                status=status or None,
            )
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/knowledge/graph")
async def get_graph_stats():
    """Get knowledge graph statistics."""
    try:
        from core.knowledge_graph import CodeKnowledgeGraph
        import os

        kg = CodeKnowledgeGraph(os.getcwd())
        kg.index_directory()
        return kg.get_graph_stats()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/knowledge/index")
async def index_codebase(extensions: List[str] = None):
    """Index codebase for knowledge graph."""
    try:
        from core.knowledge_graph import CodeKnowledgeGraph
        import os

        kg = CodeKnowledgeGraph(os.getcwd())
        kg.index_directory(extensions)
        return kg.get_graph_stats()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/knowledge/search")
async def search_code(q: str, limit: int = 10):
    """Search code using knowledge graph."""
    try:
        from core.knowledge_graph import CodeKnowledgeGraph
        import os

        kg = CodeKnowledgeGraph(os.getcwd())
        kg.index_directory()
        results = kg.search(q)
        return [
            {
                "name": r.name,
                "type": r.node_type,
                "file": r.file_path,
                "line": r.line_start,
            }
            for r in results[:limit]
        ]
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/knowledge/find")
async def find_definition(name: str):
    """Find definition of a symbol."""
    try:
        from core.knowledge_graph import CodeKnowledgeGraph
        import os

        kg = CodeKnowledgeGraph(os.getcwd())
        kg.index_directory()
        node = kg.find_definition(name)
        if node:
            return {
                "name": node.name,
                "type": node.node_type,
                "file": node.file_path,
                "line": node.line_start,
            }
        return {"error": "Not found"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/knowledge/impact")
async def knowledge_impact(symbol_name: str):
    """Run GitNexus-style impact analysis for a symbol."""
    try:
        from core.knowledge_graph import CodeKnowledgeGraph
        import os

        kg = CodeKnowledgeGraph(os.getcwd())
        kg.index_directory()
        return kg.impact(symbol_name)
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/knowledge/detect-changes")
async def knowledge_detect_changes(changed_lines: Dict[str, List[int]]):
    """Map changed lines to affected symbols and downstream impact."""
    try:
        from core.knowledge_graph import CodeKnowledgeGraph
        import os

        kg = CodeKnowledgeGraph(os.getcwd())
        kg.index_directory()
        return kg.detect_changes(changed_lines)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/knowledge/context")
async def knowledge_symbol_context(symbol_name: str):
    """Return 360-degree context for a symbol."""
    try:
        from core.knowledge_graph import CodeKnowledgeGraph
        import os

        kg = CodeKnowledgeGraph(os.getcwd())
        kg.index_directory()
        return kg.get_symbol_context(symbol_name)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/skill-library")
async def get_skill_library():
    """Get all skills in the library."""
    try:
        from core.skill_library import SkillLibrary

        lib = SkillLibrary()
        return {"skills": lib.list_skills()}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/skill-library/categories")
async def get_skill_categories():
    """Get skill categories."""
    try:
        from core.skill_library import SkillLibrary

        lib = SkillLibrary()
        return {"categories": lib.get_all_categories()}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/computer-use/info")
async def get_computer_info():
    """Get computer use agent info."""
    try:
        return await _call_engine_tool("computer_screen_info")
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/computer-use/task")
async def computer_task(task: str):
    """Execute a computer use task."""
    try:
        return await _call_engine_tool("computer_task", {"task": task})
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/computer-use/screenshot")
async def take_screenshot():
    """Take a screenshot."""
    try:
        return await _call_engine_tool("computer_screenshot")
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/computer-use/observe")
async def observe_screen():
    """Observe the current desktop state."""
    try:
        return await _call_engine_tool("computer_observe_screen")
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/computer-use/open-app")
async def open_app_verified(app_name: str):
    """Open an app and verify focus."""
    try:
        return await _call_engine_tool("computer_open_app", {"app_name": app_name})
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/computer-use/click-target")
async def click_screen_target(target_desc: str):
    """Click a screen target using coordinates or simple hints."""
    try:
        return await _call_engine_tool(
            "computer_click_target",
            {"target_desc": target_desc},
        )
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/computer-use/type-verified")
async def type_text_verified(text: str, destination_desc: str):
    """Type text and verify state afterwards."""
    try:
        return await _call_engine_tool(
            "computer_type_verified",
            {"text": text, "destination_desc": destination_desc},
        )
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/computer-use/assert-change")
async def assert_screen_change(expected_signal: str):
    """Assert a screen-change signal."""
    try:
        return await _call_engine_tool(
            "computer_assert_change",
            {"expected_signal": expected_signal},
        )
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/harness/status")
async def get_harness_status():
    """Get agent harness status."""
    try:
        from core.agent_harness import AgentHarness

        harness = AgentHarness()
        return {
            "retry_available": True,
            "timeout_available": True,
            "fallback_available": True,
            "circuit_breaker_available": True,
            "message": "AgentHarness primitives ready",
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/llm-gateway/models")
async def get_llm_models():
    """Get available LLM models."""
    try:
        from core.llm_gateway import create_llm_gateway

        gw = create_llm_gateway()
        return {"models": gw.get_available_models()}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/autotune/status")
async def autotune_status():
    """Get AutoTune status and context classification."""
    try:
        from core.autotune import get_autotune

        at = get_autotune()
        return {
            "active": True,
            "context_types": list(at.context_types.keys()),
            "feedback_count": len(at.feedback_history),
        }
    except Exception as e:
        return {"active": False, "error": str(e)}


@app.post("/api/autotune/feedback")
async def autotune_feedback(query: str, rating: int):
    """Record user feedback to improve AutoTune parameters."""
    try:
        from core.autotune import get_autotune

        at = get_autotune()
        at.record_feedback(query, rating)
        return {"success": True, "message": "Feedback recorded"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/stm/transform")
async def stm_transform(text: str, mode: str = "direct"):
    """Transform text using STM modules."""
    try:
        from core.stm_modules import get_stm

        stm = get_stm()
        result = stm.apply_all(text, mode)
        return {"original": text, "transformed": result, "mode": mode}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/llm-gateway/status")
async def get_llm_status():
    """Get LLM gateway status."""
    try:
        from core.llm_gateway import create_llm_gateway

        gw = create_llm_gateway()
        return gw.get_cost_summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/llm-gateway/health")
async def get_llm_health():
    """Get provider health and routing metadata."""
    try:
        from core.llm_gateway import create_llm_gateway

        gw = create_llm_gateway()
        return {"health": gw.get_provider_health(), "costs": gw.get_cost_summary()}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/llm-gateway/set")
async def set_llm_provider(provider: str, model: str = None):
    """Set LLM provider and model."""
    try:
        from core.llm_gateway import create_llm_gateway

        gw = create_llm_gateway()
        gw.set_provider(provider, model)
        return {
            "success": True,
            "provider": provider,
            "model": gw.current_model.name if gw.current_model else None,
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/llm-gateway/chat")
async def llm_chat(
    message: str, system: str = None, provider: str = "inception", model: str = None
):
    """Chat with specific LLM provider. Default: Inception (Mercury-2)."""
    try:
        from core.llm_gateway import create_llm_gateway

        gw = create_llm_gateway()
        gw.set_provider(provider, model)
        response = await gw.chat(message, system)
        return {
            "content": response.content,
            "model": response.model,
            "provider": response.provider,
            "usage": response.usage,
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/llm-gateway/chat-role")
async def llm_chat_for_role(role: str, message: str, system: str = None):
    """Chat using deterministic role routing."""
    try:
        from core.llm_gateway import create_llm_gateway

        gw = create_llm_gateway()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": message})
        return await gw.chat_for_role(role, messages)
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  META-COGNITION API ENDPOINTS
# ═══════════════════════════════════════════════════════════════


@app.get("/api/meta/thinking")
async def get_thinking_stats():
    """Get meta-cognition statistics."""
    try:
        from core.meta_cognition import MetaCognition

        meta = MetaCognition()
        return meta.get_thinking_stats()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/meta/think")
async def think(task: str):
    """Think about a task before executing."""
    try:
        from core.meta_cognition import MetaCognition

        meta = MetaCognition()
        result = await meta.think_before_action(task)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/meta/thoughts")
async def get_thoughts(limit: int = 10):
    """Get recent thoughts."""
    try:
        from core.meta_cognition import MetaCognition

        meta = MetaCognition()
        thoughts = meta.get_recent_thoughts(limit=limit)
        return {
            "count": len(thoughts),
            "thoughts": [
                {
                    "type": t.thought_type.value,
                    "content": t.content,
                    "confidence": t.confidence,
                }
                for t in thoughts
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/meta/reflections")
async def get_reflections(limit: int = 10):
    """Get recent reflections."""
    try:
        from core.meta_cognition import MetaCognition

        meta = MetaCognition()
        reflections = meta.get_recent_reflections(limit=limit)
        return {
            "count": len(reflections),
            "reflections": [
                {
                    "action": r.action,
                    "result": r.result,
                    "worked": r.what_worked,
                    "didnt_work": r.what_didnt_work,
                    "lessons": r.lessons_learned,
                }
                for r in reflections
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/meta/reflect")
async def reflect(action: str, result: str):
    """Reflect on an action and its result."""
    try:
        from core.meta_cognition import MetaCognition

        meta = MetaCognition()
        reflection = await meta.reflect_on_action(action, result)
        return {
            "worked": reflection.what_worked,
            "didnt_work": reflection.what_didnt_work,
            "lessons": reflection.lessons_learned,
            "improvements": reflection.improvement_suggestions,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  ADVANCED COGNITION API ENDPOINTS (Opus-level)
# ═══════════════════════════════════════════════════════════════


@app.post("/api/cognition/analyze")
async def analyze_request(request: str):
    """Full analysis like Opus would do - with real AI reasoning via DeepSeek."""
    try:
        from core.advanced_cognition import AdvancedCognition
        from core.llm_gateway import create_llm_gateway

        async def llm_executor(
            prompt: str, system: str = "You are a helpful AI assistant."
        ) -> str:
            gw = create_llm_gateway()
            gw.set_provider("deepseek", "deepseek-chat")
            try:
                response = await gw.chat(prompt, system)
                return response.content
            except Exception as e:
                gw.set_provider("inception", "mercury-inception")
                response = await gw.chat(prompt, system)
                return response.content

        cognition = AdvancedCognition(llm_executor=llm_executor)
        result = await cognition.full_analysis(request)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cognition/clarify")
async def generate_clarification(request: str):
    """Generate clarifying questions."""
    try:
        from core.advanced_cognition import AdvancedCognition

        cognition = AdvancedCognition()
        should_ask = await cognition.should_ask_question(request)
        questions = await cognition.generate_clarifying_questions(request)
        return {
            "needs_clarification": should_ask,
            "questions": [
                {"id": q.id, "question": q.question, "options": q.options}
                for q in questions
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cognition/judge")
async def judge_request(request: str):
    """Judge if request is safe."""
    try:
        from core.advanced_cognition import AdvancedCognition

        cognition = AdvancedCognition()
        judgment = await cognition.judge_request(request)
        return {
            "is_safe": judgment.is_safe,
            "reason": judgment.reason,
            "requires_consent": judgment.requires_consent,
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  cLAWS SAFETY SYSTEM (Cryptographic Safety)
# ═══════════════════════════════════════════════════════════════


@app.get("/api/claws/status")
async def claws_status():
    """Get cLaws safety system status."""
    try:
        from core.claws import get_claws

        return get_claws().get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/claws/check")
async def claws_check(action: str, action_type: str = "general"):
    """Check if action is allowed by cLaws."""
    try:
        from core.claws import get_claws

        return get_claws().check(action, action_type)
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/claws/consent")
async def claws_consent(action: str, granted: bool):
    """Record consent decision for an action."""
    try:
        from core.claws import get_claws

        get_claws().log_consent(action, granted, {"action_type": action})
        return {"success": True, "action": action, "granted": granted}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  PERSONALITY EVOLUTION
# ═══════════════════════════════════════════════════════════════


@app.get("/api/personality/status")
async def personality_status():
    """Get personality evolution status."""
    try:
        from core.personality_evolution import get_personality

        return get_personality().get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/personality/interaction")
async def record_interaction(user_message: str, agent_response: str):
    """Record interaction for personality evolution."""
    try:
        from core.personality_evolution import get_personality

        get_personality().record_interaction(user_message, agent_response)
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/personality/feedback")
async def record_feedback(rating: int, feedback_type: str = "general"):
    """Record user feedback for personality evolution."""
    try:
        from core.personality_evolution import get_personality

        get_personality().record_feedback(rating, feedback_type)
        return {"success": True, "rating": rating}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  CONFIDENCE SELF-ASSESSMENT
# ═══════════════════════════════════════════════════════════════


@app.get("/api/confidence/status")
async def confidence_status():
    """Get confidence assessor status."""
    try:
        from core.confidence_assessor import get_confidence

        return get_confidence().get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/confidence/assess")
async def assess_confidence(query: str, response: str, context_type: str = "general"):
    """Assess confidence in response."""
    try:
        from core.confidence_assessor import get_confidence

        conf = get_confidence().assess(query, response, {"type": context_type})
        return {
            "score": conf["score"],
            "level": conf["level"],
            "should_add_caveat": get_confidence().should_add_caveat(conf),
            "caveat": get_confidence().get_caveat_text(conf)
            if get_confidence().should_add_caveat(conf)
            else "",
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cognition/suggest")
async def generate_suggestions(request: str):
    """Generate proactive suggestions using real AI (DeepSeek)."""
    try:
        from core.advanced_cognition import AdvancedCognition
        from core.llm_gateway import create_llm_gateway

        async def llm_executor(
            prompt: str, system: str = "You are a helpful AI assistant."
        ) -> str:
            gw = create_llm_gateway()
            gw.set_provider("deepseek", "deepseek-chat")
            try:
                response = await gw.chat(prompt, system)
                return response.content
            except:
                gw.set_provider("inception", "mercury-inception")
                response = await gw.chat(prompt, system)
                return response.content

        cognition = AdvancedCognition(llm_executor=llm_executor)
        suggestions = await cognition.generate_suggestions(request)
        return {
            "suggestions": [
                {
                    "suggestion": s.suggestion,
                    "reason": s.reason,
                    "alternatives": s.alternatives,
                    "confidence": s.confidence,
                }
                for s in suggestions
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cognition/preference")
async def learn_preference(key: str, value: str, context: str = ""):
    """Learn a user preference."""
    try:
        from core.advanced_cognition import AdvancedCognition

        cognition = AdvancedCognition()
        await cognition.learn_preference(key, value, context)
        return {"status": "learned", "key": key, "value": value}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/cognition/preference")
async def get_preference(key: str, default: str = None):
    """Get a user preference."""
    try:
        from core.advanced_cognition import AdvancedCognition

        cognition = AdvancedCognition()
        value = await cognition.get_preference(key, default)
        return {"key": key, "value": value}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  VOICE INPUT API ENDPOINTS
# ═══════════════════════════════════════════════════════════════


@app.get("/api/voice/status")
async def voice_status():
    """Get voice input status."""
    try:
        from tools.voice_input import get_voice_input

        voice = get_voice_input()
        return {**voice.get_status(), "type": "speech_recognition"}
    except Exception as e:
        return {"active": False, "error": str(e)}


@app.post("/api/voice/listen")
async def voice_listen(timeout: int = 5, phrase_limit: int = 10):
    """Listen to microphone and transcribe speech."""
    try:
        from tools.voice_input import get_voice_input

        voice = get_voice_input()
        if not voice.is_active:
            return {"error": "Voice input not available"}

        text = await voice.listen(timeout=timeout, phrase_time_limit=phrase_limit)
        return {"text": text, "success": bool(text)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/voice/session/start")
async def voice_session_start(session_id: str = ""):
    """Start or resume a persistent voice session."""
    try:
        from tools.voice_input import get_voice_input

        return get_voice_input().start_voice_session(session_id or None)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/voice/session/status")
async def voice_session_status(session_id: str):
    """Get a specific voice session."""
    try:
        from tools.voice_input import get_voice_input

        return get_voice_input().get_session(session_id)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/voice/sessions")
async def voice_session_list(limit: int = 10):
    """List recent voice sessions."""
    try:
        from tools.voice_input import get_voice_input

        return {"sessions": get_voice_input().list_sessions(limit=limit)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/voice/session/stop")
async def voice_session_stop(session_id: str):
    """Stop a voice session."""
    try:
        from tools.voice_input import get_voice_input

        return get_voice_input().stop_voice_session(session_id)
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/voice/session/cancel")
async def voice_session_cancel(session_id: str):
    """Cancel a voice session."""
    try:
        from tools.voice_input import get_voice_input

        return get_voice_input().cancel_voice_session(session_id)
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/voice/session/listen")
async def voice_session_listen(
    session_id: str,
    timeout: int = 5,
    phrase_limit: int = 10,
):
    """Listen within a persistent voice session and return chunked transcript events."""
    try:
        from tools.voice_input import get_voice_input

        voice = get_voice_input()
        if not voice.is_active:
            return {"error": "Voice input not available"}
        return await voice.stream_listen(
            session_id,
            timeout=timeout,
            phrase_time_limit=phrase_limit,
        )
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/voice/session/stream")
async def voice_session_stream(
    session_id: str,
    timeout: int = 5,
    phrase_limit: int = 10,
):
    """Stream transcript events for a voice session over SSE."""

    async def _stream():
        try:
            from tools.voice_input import get_voice_input

            voice = get_voice_input()
            async for event in voice.stream_listen_events(
                session_id,
                timeout=timeout,
                phrase_time_limit=phrase_limit,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        finally:
            yield f"data: {json.dumps({'type': 'stream_closed', 'session_id': session_id})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/api/voice/test")
async def voice_test(text: str = "Buna ziua de la JARVIS!"):
    """Test voice output directly."""
    try:
        from core.os_sovereign import OSSovereign

        await OSSovereign().say(text)
        return {"success": True, "text": text}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/voice/converse")
async def voice_converse(
    timeout: int = 5,
    phrase_limit: int = 10,
    session_id: Optional[str] = None,
):
    """Full voice conversation - listen, understand, respond with voice."""
    try:
        from tools.voice_input import get_voice_input
        from core.os_sovereign import OSSovereign

        # Step 1: Listen to user
        voice = get_voice_input()
        if not voice.is_active:
            return {"error": "Microphone not available"}

        # Step 2: Transcribe speech to text
        user_text = await voice.listen(timeout=timeout, phrase_time_limit=phrase_limit)
        if not user_text:
            return {"error": "No speech detected", "success": False}

        # Step 3: Get JARVIS response
        resolved_session_id, chat = _get_or_create_chat_session(
            session_id or "voice_converse",
            mode_hint="voice",
        )
        jarvis_response = await chat.chat(user_text)
        jarvis_response = _normalize_brain_error_for_user(jarvis_response, context="chat")
        jarvis_response = sanitize_assistant_output(
            jarvis_response,
            user_message=user_text,
        )

        # Step 4: Speak the response (try realtime first, fallback to TTS)
        try:
            from tools.realtime_voice import RealtimeVoice

            rt = RealtimeVoice()
            if rt.is_active:
                await rt.initialize()
                await rt.speak(jarvis_response)
            else:
                await OSSovereign().say(jarvis_response)
        except Exception:
            await OSSovereign().say(jarvis_response)

        return {
            "success": True,
            "heard": user_text,
            "jarvis_said": jarvis_response,
            "session_id": resolved_session_id,
        }
    except Exception as e:
        return {"error": str(e), "success": False}


# ═══════════════════════════════════════════════════════════════
#  VOICE CASCADE
# ═══════════════════════════════════════════════════════════════


@app.get("/api/voice-cascade/status")
async def voice_cascade_status():
    """Get voice cascade system status."""
    try:
        from tools.voice_cascade import get_voice_cascade

        return get_voice_cascade().get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/voice-cascade/speak")
async def voice_cascade_speak(text: str):
    """Speak using voice cascade."""
    try:
        from tools.voice_cascade import get_voice_cascade

        pathway = await get_voice_cascade().speak(text)
        return {"success": True, "pathway": pathway.value}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/voice-cascade/listen")
async def voice_cascade_listen(timeout: int = 5):
    """Listen using voice cascade."""
    try:
        from tools.voice_cascade import get_voice_cascade

        text, pathway = await get_voice_cascade().listen(timeout)
        return {"text": text, "pathway": pathway.value, "success": bool(text)}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  MEMORY CONSOLIDATION
# ═══════════════════════════════════════════════════════════════


@app.get("/api/memory-consolidation/status")
async def memory_consolidation_status():
    """Get memory consolidation status."""
    try:
        from core.memory_consolidation import get_memory_consolidation

        return get_memory_consolidation().get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/memory-consolidation/add")
async def add_memory(content: str, tier: str = "short", importance: float = 50.0):
    """Add a new memory."""
    try:
        from core.memory_consolidation import get_memory_consolidation

        mem_id = get_memory_consolidation().add_memory(content, tier, importance)
        return {"success": True, "memory_id": mem_id}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/memory-consolidation/search")
async def search_memories(query: str, tier: str = None):
    """Search memories."""
    try:
        from core.memory_consolidation import get_memory_consolidation

        results = get_memory_consolidation().search_memories(query, tier)
        return {
            "results": [
                {"id": r.id, "content": r.content, "tier": r.tier} for r in results
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/memory-consolidation/confirm")
async def confirm_memory(memory_id: str, importance: float = None):
    """Confirm memory importance."""
    try:
        from core.memory_consolidation import get_memory_consolidation

        get_memory_consolidation().confirm_memory(memory_id, importance)
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/memory-consolidation/biases")
async def memory_execution_biases(task: str, mission_type: str = "general"):
    """Get executable memories that bias a task."""
    try:
        from core.memory_consolidation import get_memory_consolidation

        memories = get_memory_consolidation().get_execution_biases(
            {"task": task, "user_goal": task, "mission_type": mission_type}
        )
        return {"count": len(memories), "biases": [memory.to_dict() for memory in memories]}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  CONTEXT GRAPH
# ═══════════════════════════════════════════════════════════════


@app.get("/api/context-graph/status")
async def context_graph_status():
    """Get context graph status."""
    try:
        from core.context_graph import get_context_graph

        return get_context_graph().get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/context-graph/update-app")
async def update_app(app_name: str):
    """Update current app context."""
    try:
        from core.context_graph import get_context_graph

        get_context_graph().update_app(app_name)
        return {"success": True, "app": app_name}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/context-graph/update-task")
async def update_task(task: str):
    """Update current task context."""
    try:
        from core.context_graph import get_context_graph

        get_context_graph().update_task(task)
        return {"success": True, "task": task}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/context-graph/update-topic")
async def update_topic(topic: str):
    """Update current topic context."""
    try:
        from core.context_graph import get_context_graph

        get_context_graph().update_topic(topic)
        return {"success": True, "topic": topic}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/context-graph/add-entity")
async def add_entity(entity: str):
    """Add entity to current context."""
    try:
        from core.context_graph import get_context_graph

        get_context_graph().add_entity(entity)
        return {"success": True, "entity": entity}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/context-graph/set-goal")
async def set_active_goal(goal: str):
    """Set the current active goal in the world-state graph."""
    try:
        from core.context_graph import get_context_graph

        get_context_graph().set_active_goal(goal)
        return {"success": True, "goal": goal}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/context-graph/record-tool-edge")
async def record_tool_edge(tool: str, result: str):
    """Record a tool usage edge in the world-state graph."""
    try:
        from core.context_graph import get_context_graph

        get_context_graph().record_tool_edge(tool, result)
        return {"success": True, "tool": tool, "result": result}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/context-graph/record-failure-edge")
async def record_failure_edge(step_id: str, code: str):
    """Record a failure edge in the world-state graph."""
    try:
        from core.context_graph import get_context_graph

        get_context_graph().record_failure_edge(step_id, code)
        return {"success": True, "step_id": step_id, "code": code}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  DURABLE RUNTIME (LangGraph-style execution)
# ═══════════════════════════════════════════════════════════════


@app.get("/api/durable/status")
async def durable_status():
    """Get durable runtime status."""
    try:
        from core.durable_runtime import get_durable_runtime

        return {"sessions": get_durable_runtime().list_sessions()}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/durable/create-session")
async def create_session(task: str, initial_state: str = "{}"):
    """Create new execution session."""
    try:
        from core.durable_runtime import get_durable_runtime
        import json

        state = json.loads(initial_state) if initial_state != "{}" else {}
        session_id = get_durable_runtime().create_session(task, state)
        return {"success": True, "session_id": session_id}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/durable/add-node")
async def add_node(session_id: str, node_id: str, name: str, input_state: str = "{}"):
    """Add node to execution graph."""
    try:
        from core.durable_runtime import get_durable_runtime
        import json

        state = json.loads(input_state) if input_state != "{}" else {}
        get_durable_runtime().add_node(session_id, node_id, name, state)
        return {"success": True, "node_id": node_id}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/durable/add-edge")
async def add_edge(session_id: str, from_node: str, to_node: str):
    """Add edge between nodes."""
    try:
        from core.durable_runtime import get_durable_runtime

        get_durable_runtime().add_edge(session_id, from_node, to_node)
        return {"success": True, "from": from_node, "to": to_node}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/durable/fork")
async def fork_session(session_id: str, reason: str = "exploration"):
    """Fork session for parallel exploration."""
    try:
        from core.durable_runtime import get_durable_runtime

        fork_id = get_durable_runtime().fork(session_id, reason)
        return {"success": True, "fork_id": fork_id}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  MEM0 MEMORY LAYER
# ═══════════════════════════════════════════════════════════════


@app.get("/api/mem0/status")
async def mem0_status():
    """Get Mem0 memory status."""
    try:
        from core.mem0_memory import get_mem0_memory

        return get_mem0_memory().get_stats()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/mem0/add")
async def mem0_add(
    content: str, memory_type: str = "session", importance: float = 50.0
):
    """Add a memory."""
    try:
        from core.mem0_memory import get_mem0_memory

        mem_id = get_mem0_memory().add(content, memory_type, importance=importance)
        return {"success": True, "memory_id": mem_id}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/mem0/search")
async def mem0_search(query: str, limit: int = 5):
    """Search memories."""
    try:
        from core.mem0_memory import get_mem0_memory

        results = get_mem0_memory().search(query, limit)
        return {"results": results}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/mem0/preferences")
async def mem0_preferences():
    """Get user preferences."""
    try:
        from core.mem0_memory import get_mem0_memory

        return get_mem0_memory().get_user_preferences()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/mem0/all")
async def mem0_all(memory_type: str = None, limit: int = 20):
    """Get all memories."""
    try:
        from core.mem0_memory import get_mem0_memory

        return {"memories": get_mem0_memory().get_all(memory_type, limit)}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  RESEARCH AGENT (GPT Researcher style)
# ═══════════════════════════════════════════════════════════════


@app.get("/api/research/status")
async def research_status():
    """Get research agent status."""
    try:
        from core.research_agent import get_research_agent

        return get_research_agent().get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/research/query")
async def research_query(query: str, depth: int = 2):
    """Perform research on a query."""
    try:
        from core.research_agent import get_research_agent

        result = await get_research_agent().research(query, depth)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/research/report")
async def research_report(topic: str, format: str = "brief"):
    """Generate research report."""
    try:
        from core.research_agent import get_research_agent

        result = await get_research_agent().generate_report(topic, format)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/durable/state")
async def get_state(session_id: str):
    """Get session state."""
    try:
        from core.durable_runtime import get_durable_runtime

        return get_durable_runtime().get_state(session_id) or {
            "error": "Session not found"
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  BROWSER AGENT
# ═══════════════════════════════════════════════════════════════


@app.get("/api/browser/status")
async def browser_status():
    """Get browser agent status."""
    try:
        return await _call_engine_tool("browser_status")
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/browser/search")
async def browser_search(query: str):
    """Search the web."""
    try:
        return await _call_engine_tool("browser_search", {"query": query})
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/browser/navigate")
async def browser_navigate(url: str):
    """Navigate to URL."""
    try:
        return await _call_engine_tool("browser_navigate", {"url": url})
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/browser/extract")
async def browser_extract(url: str, goal: str):
    """Extract information from page."""
    try:
        return await _call_engine_tool(
            "browser_extract",
            {"url": url, "goal": goal},
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/browser/execute")
async def browser_execute(task: str):
    """Execute a higher-level browser task."""
    try:
        return await _call_engine_tool("browser_task", {"task": task})
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/browser/execute-structured")
async def browser_execute_structured(
    task: str, success_criteria: Dict[str, Any] | None = None
):
    """Execute a browser task with explicit success criteria."""
    try:
        return await _call_engine_tool(
            "browser_task",
            {"task": task, "success_criteria": success_criteria or {}},
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/browser/extract-structured")
async def browser_extract_structured(schema: Dict[str, Any], url: str = ""):
    """Extract structured data from a page."""
    try:
        return await _call_engine_tool(
            "browser_structured_extract",
            {"schema": schema, "url": url or ""},
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/cowork/status")
async def get_cowork_status():
    """Get co-work runtime status."""
    try:
        return await _call_engine_tool("cowork_status")
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cowork/start")
async def start_cowork_runtime():
    """Start co-work runtime."""
    try:
        return await _call_engine_tool("cowork_start")
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cowork/command")
async def run_cowork_command(command: str):
    """Process a command through the persistent co-work runtime."""
    try:
        return await _call_engine_tool("cowork_command", {"command": command})
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cowork/stop")
async def stop_cowork_runtime():
    """Stop co-work runtime."""
    try:
        return await _call_engine_tool("cowork_stop")
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/stagehand/status")
async def stagehand_status():
    """Get deterministic Stagehand-style browser status."""
    try:
        from tools.stagehand_browser import get_stagehand_browser

        return get_stagehand_browser().get_status()
    except Exception as e:
        return {"available": False, "error": str(e)}


@app.post("/api/stagehand/act")
async def stagehand_act(action: str, target: str = ""):
    """Perform a deterministic browser action."""
    try:
        from tools.stagehand_browser import get_stagehand_browser

        return await get_stagehand_browser().act(action, target or None)
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/stagehand/extract")
async def stagehand_extract(selector: str = "body", url: str = ""):
    """Extract content using deterministic browser primitives."""
    try:
        from tools.stagehand_browser import get_stagehand_browser

        return await get_stagehand_browser().extract(selector=selector, url=url or None)
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/stagehand/observe")
async def stagehand_observe(query: str = "page", url: str = ""):
    """Observe a page using deterministic browser primitives."""
    try:
        from tools.stagehand_browser import get_stagehand_browser

        return await get_stagehand_browser().observe(query=query, url=url or None)
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/context-graph/current")
async def get_current_context():
    """Get current context."""
    try:
        from core.context_graph import get_context_graph

        return get_context_graph().get_current_context()
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  INTEGRATION BRIDGE (called from Python engine)
# ═══════════════════════════════════════════════════════════════


async def push_event(event_type: str, message: str, data: Optional[Dict] = None):
    """Bridge call to push an update from engine to Nucleus UI."""
    event = {
        "type": event_type,
        "message": message,
        "data": data or {},
        "timestamp": datetime.now().isoformat(),
    }
    await manager.broadcast(event)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8888)
