"""Lightweight tracing runtime inspired by AgentScope tracing hooks."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

_TRACE_STACK: ContextVar[List[str]] = ContextVar("jarvis_trace_stack", default=[])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TraceSpan:
    """One trace span persisted for later debugging."""

    id: str
    parent_id: str | None
    kind: str
    name: str
    status: str
    started_at: str
    ended_at: str | None = None
    duration_ms: float | None = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class JarvisTracer:
    """Simple JSONL tracer with nested span support."""

    def __init__(self, vault_path: str | Path, *, max_recent: int = 200):
        self.base_path = Path(vault_path) / "traces"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.stream_path = self.base_path / "spans.jsonl"
        self.recent_path = self.base_path / "recent.json"
        self.max_recent = max_recent
        self._active: Dict[str, TraceSpan] = {}

    def start_span(
        self,
        kind: str,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        *,
        parent_id: Optional[str] = None,
    ) -> str:
        stack = list(_TRACE_STACK.get())
        if parent_id is None and stack:
            parent_id = stack[-1]

        span_id = uuid.uuid4().hex
        span = TraceSpan(
            id=span_id,
            parent_id=parent_id,
            kind=kind,
            name=name,
            status="in_progress",
            started_at=_now(),
            attributes=attributes or {},
        )
        self._active[span_id] = span
        stack.append(span_id)
        _TRACE_STACK.set(stack)
        return span_id

    def end_span(
        self,
        span_id: str,
        *,
        status: str = "ok",
        attributes: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        span = self._active.pop(span_id, None)
        if not span:
            return None

        started = datetime.fromisoformat(span.started_at)
        ended = datetime.now(timezone.utc)
        span.ended_at = ended.isoformat()
        span.duration_ms = round((ended - started).total_seconds() * 1000, 2)
        span.status = status
        if attributes:
            span.attributes.update(attributes)
        if error:
            span.error = error

        stack = [item for item in _TRACE_STACK.get() if item != span_id]
        _TRACE_STACK.set(stack)

        payload = asdict(span)
        self._append(payload)
        return payload

    @contextmanager
    def span(
        self,
        kind: str,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Iterator[str]:
        span_id = self.start_span(kind, name, attributes)
        try:
            yield span_id
        except Exception as exc:
            self.end_span(span_id, status="error", error=str(exc))
            raise
        else:
            self.end_span(span_id)

    @asynccontextmanager
    async def span_async(
        self,
        kind: str,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        span_id = self.start_span(kind, name, attributes)
        try:
            yield span_id
        except Exception as exc:
            self.end_span(span_id, status="error", error=str(exc))
            raise
        else:
            self.end_span(span_id)

    def record_event(
        self,
        kind: str,
        name: str,
        *,
        status: str = "ok",
        attributes: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        span_id = self.start_span(kind, name, attributes)
        return self.end_span(span_id, status=status, error=error)

    def recent(self, limit: int = 25, kind: str | None = None, status: str | None = None) -> List[Dict[str, Any]]:
        recent = self._load_recent()
        if kind:
            recent = [item for item in recent if item.get("kind") == kind]
        if status:
            recent = [item for item in recent if item.get("status") == status]
        return recent[-limit:]

    def summary(self, limit: int = 100) -> Dict[str, Any]:
        spans = self.recent(limit=limit)
        by_kind: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        for span in spans:
            by_kind[span.get("kind", "unknown")] = by_kind.get(span.get("kind", "unknown"), 0) + 1
            by_status[span.get("status", "unknown")] = by_status.get(span.get("status", "unknown"), 0) + 1

        recent_errors = [item for item in spans if item.get("status") == "error"][-5:]
        return {
            "total_spans": len(spans),
            "by_kind": by_kind,
            "by_status": by_status,
            "recent_errors": recent_errors,
        }

    def _append(self, payload: Dict[str, Any]) -> None:
        with self.stream_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

        recent = self._load_recent()
        recent.append(payload)
        recent = recent[-self.max_recent :]
        self.recent_path.write_text(
            json.dumps(recent, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_recent(self) -> List[Dict[str, Any]]:
        if not self.recent_path.exists():
            return []
        try:
            data = json.loads(self.recent_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []
