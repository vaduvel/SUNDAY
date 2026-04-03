"""Safe maintenance journal around the NeuroBrain runtime.

This module does not change neuro algorithms. It only records
governance/adaptation signals in a durable, inspectable form.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NeuroMaintenanceJournal:
    """Persist safe maintenance signals next to the neuro vault."""

    def __init__(self, neuro_path: str | Path = ".agent/neuro"):
        self.base_path = Path(neuro_path) / "maintenance"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.summary_path = self.base_path / "summary.json"
        self.governance_path = self.base_path / "governance_sync.jsonl"
        self.promotions_path = self.base_path / "promotions.jsonl"
        self.anomalies_path = self.base_path / "anomalies.jsonl"
        self.alerts_path = self.base_path / "alerts.jsonl"

    def record_governance(
        self,
        mission_id: str,
        governance: Dict[str, Any],
        governance_signal: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        signal = governance_signal or {}
        record = {
            "mission_id": mission_id,
            "recorded_at": _utc_now(),
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
            "governance_signal": signal,
        }
        self._append_jsonl(self.governance_path, record)

        gate_decision = str(governance.get("gate_decision") or "").lower()
        if gate_decision == "promote":
            self._append_jsonl(
                self.promotions_path,
                {
                    "mission_id": mission_id,
                    "recorded_at": record["recorded_at"],
                    "candidate_skill_id": governance.get("candidate_skill_id"),
                    "candidate_skill_name": governance.get("candidate_skill_name"),
                    "proposal_id": governance.get("proposal_id"),
                    "eval_suite_name": governance.get("eval_suite_name"),
                    "quality_score": governance.get("quality_score"),
                },
            )

        if not signal.get("dod_done", True) or int(signal.get("critical_failure_count", 0)) > 0:
            self._append_jsonl(
                self.alerts_path,
                {
                    "mission_id": mission_id,
                    "recorded_at": record["recorded_at"],
                    "kind": "governance_risk",
                    "gate_decision": governance.get("gate_decision"),
                    "critical_failure_count": int(signal.get("critical_failure_count", 0)),
                    "failure_codes": list(signal.get("failure_codes") or []),
                    "dod_done": bool(signal.get("dod_done")),
                },
            )

        return self._write_summary()

    def record_anomaly(
        self,
        mission_id: str,
        step_id: str,
        anomaly: float,
        reasons: List[str] | None = None,
        gate_fired: bool = False,
    ) -> Dict[str, Any]:
        record = {
            "mission_id": mission_id,
            "step_id": step_id,
            "recorded_at": _utc_now(),
            "anomaly_score": round(float(anomaly), 4),
            "gate_fired": bool(gate_fired),
            "reasons": list(reasons or []),
        }
        self._append_jsonl(self.anomalies_path, record)
        if gate_fired:
            self._append_jsonl(
                self.alerts_path,
                {
                    "mission_id": mission_id,
                    "recorded_at": record["recorded_at"],
                    "kind": "anomaly_gate",
                    "step_id": step_id,
                    "anomaly_score": record["anomaly_score"],
                    "reasons": record["reasons"],
                },
            )
        return self._write_summary()

    def status(self, limit: int = 3) -> Dict[str, Any]:
        summary = self._read_json(self.summary_path, default={})
        return {
            "governance_events": int(summary.get("governance_events", 0)),
            "promotion_events": int(summary.get("promotion_events", 0)),
            "anomaly_events": int(summary.get("anomaly_events", 0)),
            "alert_events": int(summary.get("alert_events", 0)),
            "last_governance_at": summary.get("last_governance_at"),
            "last_promotion_at": summary.get("last_promotion_at"),
            "last_anomaly_at": summary.get("last_anomaly_at"),
            "recent_governance": self._tail_jsonl(self.governance_path, limit),
            "recent_promotions": self._tail_jsonl(self.promotions_path, limit),
            "recent_anomalies": self._tail_jsonl(self.anomalies_path, limit),
            "recent_alerts": self._tail_jsonl(self.alerts_path, limit),
        }

    def _write_summary(self) -> Dict[str, Any]:
        summary = {
            "governance_events": self._count_lines(self.governance_path),
            "promotion_events": self._count_lines(self.promotions_path),
            "anomaly_events": self._count_lines(self.anomalies_path),
            "alert_events": self._count_lines(self.alerts_path),
            "last_governance_at": self._last_timestamp(self.governance_path),
            "last_promotion_at": self._last_timestamp(self.promotions_path),
            "last_anomaly_at": self._last_timestamp(self.anomalies_path),
            "updated_at": _utc_now(),
        }
        self.summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return summary

    @staticmethod
    def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def _tail_jsonl(path: Path, limit: int) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

        items: List[Dict[str, Any]] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(items) >= max(0, int(limit)):
                break
        return items

    @staticmethod
    def _count_lines(path: Path) -> int:
        if not path.exists():
            return 0
        try:
            return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            return 0

    @staticmethod
    def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(default)

    @staticmethod
    def _last_timestamp(path: Path) -> str | None:
        tail = NeuroMaintenanceJournal._tail_jsonl(path, 1)
        if not tail:
            return None
        return tail[0].get("recorded_at")
