"""AgentScope-inspired plan notebook for persistent subtask management."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NotebookSubTask:
    """One persistent subtask tracked by the notebook."""

    name: str
    description: str
    expected_output: str = ""
    state: str = "todo"
    notes: List[str] = field(default_factory=list)


@dataclass
class NotebookPlan:
    """A persisted execution plan with stateful subtasks."""

    id: str
    name: str
    description: str
    expected_outcome: str
    state: str
    created_at: str
    updated_at: str
    mode: str = "default"
    complexity_score: int = 1
    source_task: str = ""
    subtasks: List[NotebookSubTask] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PlanNotebook:
    """Persistent notebook that manages current and historical plans."""

    def __init__(
        self,
        vault_path: str | Path,
        *,
        max_subtasks: int | None = 12,
        plan_to_hint: Optional[Callable[[Optional[NotebookPlan]], Optional[str]]] = None,
    ):
        self.max_subtasks = max_subtasks
        self.plan_to_hint = plan_to_hint or self._default_plan_to_hint
        self.storage_path = Path(vault_path) / "plan_notebook.json"
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.current_plan_id: str | None = None
        self.plans: Dict[str, NotebookPlan] = {}
        self._hooks: List[Callable[[str, Dict[str, Any]], None]] = []
        self._load()

    def register_plan_change_hook(self, hook: Callable[[str, Dict[str, Any]], None]) -> None:
        self._hooks.append(hook)

    def remove_plan_change_hook(self, hook: Callable[[str, Dict[str, Any]], None]) -> None:
        if hook in self._hooks:
            self._hooks.remove(hook)

    def create_plan(
        self,
        *,
        name: str,
        description: str,
        expected_outcome: str,
        subtasks: List[Dict[str, Any]],
        mode: str = "default",
        complexity_score: int = 1,
        source_task: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self.max_subtasks is not None:
            subtasks = subtasks[: self.max_subtasks]

        plan = NotebookPlan(
            id=f"plan_{uuid.uuid4().hex[:12]}",
            name=name,
            description=description,
            expected_outcome=expected_outcome,
            state="todo",
            created_at=_now(),
            updated_at=_now(),
            mode=mode,
            complexity_score=complexity_score,
            source_task=source_task,
            subtasks=[
                NotebookSubTask(
                    name=item.get("name", f"Step {idx + 1}"),
                    description=item.get("description", ""),
                    expected_output=item.get("expected_output", ""),
                    state=item.get("state", "todo"),
                    notes=list(item.get("notes", [])),
                )
                for idx, item in enumerate(subtasks)
            ],
            metadata=metadata or {},
        )
        self.plans[plan.id] = plan
        self.current_plan_id = plan.id
        self._save()
        payload = self._plan_to_dict(plan)
        self._emit("create_plan", payload)
        return payload

    def create_plan_from_bundle(self, task: str, plan_bundle: Dict[str, Any]) -> Dict[str, Any]:
        """Build a notebook plan from ULTRAPLAN output."""
        subtasks = []
        for step in plan_bundle.get("steps", []):
            subtasks.append(
                {
                    "name": f"{step.get('phase', 'Step')} - {step.get('title', 'Untitled')}",
                    "description": step.get("objective", ""),
                    "expected_output": "; ".join(step.get("outputs", [])),
                }
            )

        expected_outcome = "; ".join(plan_bundle.get("success_criteria", [])) or task
        return self.create_plan(
            name=task[:100],
            description=task,
            expected_outcome=expected_outcome,
            subtasks=subtasks,
            mode=plan_bundle.get("mode", "default"),
            complexity_score=int(plan_bundle.get("complexity_score", 1)),
            source_task=task,
            metadata={"context": plan_bundle.get("context", ""), "constraints": plan_bundle.get("constraints", [])},
        )

    def get_current_plan(self) -> Optional[Dict[str, Any]]:
        plan = self._current_plan()
        return self._plan_to_dict(plan) if plan else None

    def view_subtasks(self) -> List[Dict[str, Any]]:
        plan = self._current_plan()
        if not plan:
            return []
        return [asdict(subtask) for subtask in plan.subtasks]

    def revise_current_plan(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        expected_outcome: str | None = None,
        mode: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        plan = self._require_plan()
        if name:
            plan.name = name
        if description:
            plan.description = description
        if expected_outcome:
            plan.expected_outcome = expected_outcome
        if mode:
            plan.mode = mode
        if metadata:
            plan.metadata.update(metadata)
        plan.updated_at = _now()
        self._save()
        payload = self._plan_to_dict(plan)
        self._emit("revise_plan", payload)
        return payload

    def update_subtask_state(
        self,
        subtask_idx: int,
        state: str,
        note: str = "",
    ) -> Dict[str, Any]:
        plan = self._require_plan()
        if subtask_idx < 0 or subtask_idx >= len(plan.subtasks):
            raise IndexError("Subtask index out of range.")

        subtask = plan.subtasks[subtask_idx]
        subtask.state = state
        if note:
            subtask.notes.append(note)
        if state == "in_progress" and plan.state == "todo":
            plan.state = "in_progress"
        if all(item.state == "done" for item in plan.subtasks):
            plan.state = "completed"
        plan.updated_at = _now()
        self._save()
        payload = self._plan_to_dict(plan)
        self._emit(
            "update_subtask_state",
            {"plan_id": plan.id, "subtask_idx": subtask_idx, "state": state, "note": note, "plan": payload},
        )
        return payload

    def finish_subtask(self, subtask_idx: int, note: str = "") -> Dict[str, Any]:
        return self.update_subtask_state(subtask_idx, "done", note=note)

    def finish_plan(self, outcome: str = "completed") -> Dict[str, Any]:
        plan = self._require_plan()
        plan.state = outcome
        plan.updated_at = _now()
        self._save()
        payload = self._plan_to_dict(plan)
        self._emit("finish_plan", payload)
        return payload

    def view_historical_plans(self, limit: int = 10) -> List[Dict[str, Any]]:
        plans = sorted(self.plans.values(), key=lambda item: item.updated_at, reverse=True)
        return [self._plan_to_dict(plan) for plan in plans[:limit]]

    def recover_historical_plan(self, plan_id: str) -> Dict[str, Any]:
        if plan_id not in self.plans:
            raise KeyError(f"Plan '{plan_id}' not found.")
        self.current_plan_id = plan_id
        plan = self.plans[plan_id]
        plan.updated_at = _now()
        self._save()
        payload = self._plan_to_dict(plan)
        self._emit("recover_plan", payload)
        return payload

    def get_current_hint(self) -> str:
        return self.plan_to_hint(self._current_plan()) or "No active plan."

    def summary(self) -> Dict[str, Any]:
        current = self.get_current_plan()
        return {
            "current_plan": current,
            "historical_count": len(self.plans),
            "current_hint": self.get_current_hint(),
        }

    def _current_plan(self) -> Optional[NotebookPlan]:
        if not self.current_plan_id:
            return None
        return self.plans.get(self.current_plan_id)

    def _require_plan(self) -> NotebookPlan:
        plan = self._current_plan()
        if not plan:
            raise RuntimeError("No active plan.")
        return plan

    def _default_plan_to_hint(self, plan: Optional[NotebookPlan]) -> str:
        if not plan:
            return "No active plan. Create one before attempting coordinated execution."

        lines = [
            f"Current plan: {plan.name}",
            f"Mode: {plan.mode} | State: {plan.state} | Complexity: {plan.complexity_score}",
        ]
        next_subtask = next((item for item in plan.subtasks if item.state != "done"), None)
        if next_subtask:
            lines.append(f"Next subtask: {next_subtask.name}")
            lines.append(f"Objective: {next_subtask.description}")
            if next_subtask.expected_output:
                lines.append(f"Expected output: {next_subtask.expected_output}")
        else:
            lines.append("All subtasks are complete. Finish or archive the plan.")
        return "\n".join(lines)

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        for hook in list(self._hooks):
            try:
                hook(event, payload)
            except Exception:
                continue

    def _plan_to_dict(self, plan: Optional[NotebookPlan]) -> Optional[Dict[str, Any]]:
        if not plan:
            return None
        return asdict(plan)

    def _load(self) -> None:
        if not self.storage_path.exists():
            return

        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return

        self.current_plan_id = payload.get("current_plan_id")
        self.plans = {}
        for raw_plan in payload.get("plans", []):
            subtasks = [
                NotebookSubTask(**subtask)
                for subtask in raw_plan.get("subtasks", [])
            ]
            raw_plan = {**raw_plan, "subtasks": subtasks}
            plan = NotebookPlan(**raw_plan)
            self.plans[plan.id] = plan

    def _save(self) -> None:
        payload = {
            "current_plan_id": self.current_plan_id,
            "plans": [self._plan_to_dict(plan) for plan in self.plans.values()],
        }
        self.storage_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
