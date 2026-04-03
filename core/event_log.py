"""Jarvis V3 Event Log — typed append-only event pipeline.

Every meaningful action emits a structured event.
Without this, Jarvis is opaque and unreplayable.

Schema aligned with Jarvis V3 EVENT_SCHEMA.md.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Event types (V3 EVENT_SCHEMA families) ───────────────────────

class E:
    """Event type constants."""
    # Run lifecycle
    RUN_CREATED        = "run.created"
    RUN_STARTED        = "run.started"
    RUN_COMPLETED      = "run.completed"
    RUN_FAILED         = "run.failed"
    RUN_CANCELLED      = "run.cancelled"

    # Step lifecycle
    STEP_STARTED       = "run.step.started"
    STEP_COMPLETED     = "run.step.completed"
    STEP_FAILED        = "run.step.failed"
    STEP_SKIPPED       = "run.step.skipped"

    # Tooling
    TOOL_STARTED       = "tool.call.started"
    TOOL_COMPLETED     = "tool.call.completed"
    TOOL_FAILED        = "tool.call.failed"

    # Artifacts
    ARTIFACT_CREATED   = "artifact.created"
    ARTIFACT_PROMOTED  = "artifact.promoted"

    # Memory
    MEMORY_EXTRACTED   = "memory.extracted"
    MEMORY_WRITTEN     = "memory.written"
    MEMORY_SUPERSEDED  = "memory.superseded"

    # Improvements
    IMPROVEMENT_PROPOSED    = "improvement.proposed"
    IMPROVEMENT_QUEUED      = "improvement.queued_for_eval"
    IMPROVEMENT_REJECTED    = "improvement.rejected"
    IMPROVEMENT_PROMOTED    = "improvement.promoted"

    # Evals
    EVAL_STARTED       = "eval.run.started"
    EVAL_CASE_DONE     = "eval.case.completed"
    EVAL_COMPLETED     = "eval.run.completed"

    # Virtual worlds
    WORLD_STARTED      = "world.session.started"
    WORLD_STEP_DONE    = "world.step.completed"
    WORLD_COMPLETED    = "world.session.completed"

    # Governance
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED   = "approval.granted"
    APPROVAL_DENIED    = "approval.denied"
    PROMOTION_DECIDED  = "promotion.decision.recorded"
    POLICY_BLOCKED     = "policy.blocked"

    # Neuro (new)
    NEURO_ANOMALY      = "neuro.anomaly.detected"
    NEURO_GATE_FIRED   = "neuro.gate.fired"
    NEURO_BELIEF       = "neuro.belief.updated"


# ── Event envelope ────────────────────────────────────────────────

@dataclass
class Event:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    task_id: str = ""
    actor_kind: str = "agent"       # agent | human | system
    actor_role: str = "orchestrator"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_version: int = 1
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "actor": {
                "kind": self.actor_kind,
                "role": self.actor_role,
            },
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ── Event Log ─────────────────────────────────────────────────────

class EventLog:
    """
    Append-only structured event log.

    Writes JSONL to .agent/events/events.jsonl
    Materializes per-run logs for replay.

    Usage:
        log = get_event_log()
        log.emit(E.RUN_STARTED, run_id="abc", payload={"task": "fix bug"})
        log.emit(E.TOOL_COMPLETED, run_id="abc", actor_role="engineer",
                 payload={"tool_name": "browser_agent", "duration_ms": 1200})
    """

    def __init__(self, vault_path: str = ".agent/events"):
        self.vault = Path(vault_path)
        self.vault.mkdir(parents=True, exist_ok=True)
        self.main_log = self.vault / "events.jsonl"
        self.runs_dir = self.vault / "runs"
        self.runs_dir.mkdir(exist_ok=True)
        self._buffer: list[Event] = []
        self._buffer_limit = 50

    # ── public API ───────────────────────────────────────────────

    def emit(
        self,
        event_type: str,
        run_id: str = "",
        task_id: str = "",
        actor_kind: str = "agent",
        actor_role: str = "orchestrator",
        payload: dict[str, Any] | None = None,
    ) -> Event:
        """Emit a typed event and append to log."""
        ev = Event(
            event_type=event_type,
            run_id=run_id,
            task_id=task_id,
            actor_kind=actor_kind,
            actor_role=actor_role,
            payload=payload or {},
        )
        self._append(ev)
        return ev

    def emit_event(self, event: Event) -> None:
        """Emit a pre-built Event object."""
        self._append(event)

    def get_run_events(self, run_id: str) -> list[dict]:
        """Return all events for a given run_id."""
        run_file = self.runs_dir / f"{run_id}.jsonl"
        if not run_file.exists():
            return []
        events = []
        for line in run_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events

    def export_replay_bundle(self, run_id: str) -> dict:
        """Export a replay bundle for a run."""
        events = self.get_run_events(run_id)
        return {
            "run_id": run_id,
            "event_count": len(events),
            "events": events,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

    def tail(self, n: int = 20) -> list[dict]:
        """Return last N events from main log."""
        if not self.main_log.exists():
            return []
        lines = self.main_log.read_text(encoding="utf-8").splitlines()
        result = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return result

    def stats(self) -> dict:
        """Summary statistics."""
        if not self.main_log.exists():
            return {"total_events": 0}
        lines = [l for l in self.main_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        runs = list(self.runs_dir.glob("*.jsonl"))
        return {
            "total_events": len(lines),
            "total_runs": len(runs),
            "log_path": str(self.main_log),
        }

    # ── internal ─────────────────────────────────────────────────

    def _append(self, ev: Event) -> None:
        line = ev.to_json()
        # main log
        try:
            with self.main_log.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.warning(f"[EventLog] Write error: {e}")

        # per-run log
        if ev.run_id:
            run_file = self.runs_dir / f"{ev.run_id}.jsonl"
            try:
                with run_file.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

        logger.debug(f"[EventLog] {ev.event_type} run={ev.run_id} actor={ev.actor_role}")


# ── Singleton ─────────────────────────────────────────────────────

_event_log: EventLog | None = None


def get_event_log(vault_path: str = ".agent/events") -> EventLog:
    global _event_log
    if _event_log is None:
        _event_log = EventLog(vault_path)
    return _event_log
