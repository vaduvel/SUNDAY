"""Persistent session runtime inspired by AgentScope session modules."""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionRuntime:
    """Persists mission sessions and restores registered module state."""

    def __init__(self, vault_path: str | Path):
        self.base_path = Path(vault_path) / "sessions"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_path / "index.json"
        self.active_session_id: str | None = None
        self._modules: Dict[str, Dict[str, Any]] = {}
        self._index = self._load_index()

    def register_module(
        self,
        name: str,
        exporter: Callable[..., Any],
        importer: Optional[Callable[[Any], None]] = None,
    ) -> None:
        self._modules[name] = {"exporter": exporter, "importer": importer}

    def start_session(
        self,
        task: str,
        *,
        mode: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not session_id:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            session_id = f"session_{timestamp}"

        record = {
            "id": session_id,
            "task": task,
            "mode": mode,
            "status": "active",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "ended_at": None,
            "metadata": metadata or {},
            "checkpoints": [],
            "module_states": {},
            "result_preview": "",
        }
        self.active_session_id = session_id
        self._write_session(record)
        self._upsert_index(record)
        return record

    def checkpoint(
        self,
        name: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        record = self._require_record(session_id)
        checkpoint = {
            "name": name,
            "timestamp": _utc_now(),
            "payload": payload or {},
        }
        record["checkpoints"].append(checkpoint)
        record["updated_at"] = _utc_now()
        self._write_session(record)
        self._upsert_index(record)
        return checkpoint

    def update(self, *, session_id: Optional[str] = None, **fields: Any) -> Dict[str, Any]:
        record = self._require_record(session_id)
        record.update(fields)
        record["updated_at"] = _utc_now()
        self._write_session(record)
        self._upsert_index(record)
        return record

    def snapshot(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        record = self._require_record(session_id)
        module_states: Dict[str, Any] = {}

        for module_name, config in self._modules.items():
            exporter = config["exporter"]
            try:
                module_states[module_name] = self._call_exporter(exporter, record["id"])
            except Exception as exc:
                module_states[module_name] = {"error": str(exc)}

        record["module_states"] = module_states
        record["updated_at"] = _utc_now()
        self._write_session(record)
        self._upsert_index(record)
        return record

    def resume(self, session_id: str) -> Dict[str, Any]:
        record = self.get_session(session_id)
        if not record:
            raise KeyError(f"Session '{session_id}' not found.")

        for module_name, config in self._modules.items():
            importer = config.get("importer")
            if importer and module_name in record.get("module_states", {}):
                importer(record["module_states"][module_name])

        self.active_session_id = session_id
        record["status"] = "resumed"
        record["updated_at"] = _utc_now()
        self._write_session(record)
        self._upsert_index(record)
        return record

    def close_session(
        self,
        *,
        status: str = "completed",
        result_preview: str = "",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        record = self._require_record(session_id)
        record["status"] = status
        record["ended_at"] = _utc_now()
        record["updated_at"] = _utc_now()
        record["result_preview"] = result_preview[:500]
        self._write_session(record)
        self._upsert_index(record)
        if self.active_session_id == record["id"]:
            self.active_session_id = None
        return record

    def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        ordered = sorted(self._index.values(), key=lambda item: item.get("updated_at", ""), reverse=True)
        return ordered[:limit]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        path = self.base_path / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def current_session(self) -> Optional[Dict[str, Any]]:
        if not self.active_session_id:
            return None
        return self.get_session(self.active_session_id)

    def _require_record(self, session_id: Optional[str]) -> Dict[str, Any]:
        record = self.get_session(session_id or self.active_session_id or "")
        if not record:
            raise RuntimeError("No active session.")
        return record

    def _write_session(self, record: Dict[str, Any]) -> None:
        path = self.base_path / f"{record['id']}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    def _upsert_index(self, record: Dict[str, Any]) -> None:
        self._index[record["id"]] = {
            "id": record["id"],
            "task": record.get("task", ""),
            "mode": record.get("mode", "default"),
            "status": record.get("status", "active"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "ended_at": record.get("ended_at"),
            "result_preview": record.get("result_preview", ""),
        }
        self.index_path.write_text(
            json.dumps(list(self._index.values()), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, list):
            return {}
        return {item["id"]: item for item in raw if isinstance(item, dict) and item.get("id")}

    def _call_exporter(self, exporter: Callable[..., Any], session_id: str) -> Any:
        params = inspect.signature(exporter).parameters
        if not params:
            return exporter()
        return exporter(session_id)
