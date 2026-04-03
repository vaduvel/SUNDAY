"""
J.A.R.V.I.S. Mission Metrics
============================

Metrici standardizate per misiune.

Based on JARVIS V2 Blueprint Section 4.6
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import json
from pathlib import Path


@dataclass
class MissionMetrics:
    """Metrici complete pentru o misiune"""

    # ID
    mission_id: str

    # Outcome
    success: bool
    verified_success: bool

    # Timing
    duration_sec: float
    start_time: datetime

    # Execution
    total_steps: int
    verified_steps: int = 0
    retries: int = 0
    replans: int = 0

    end_time: Optional[datetime] = None

    # Approvals
    approvals_requested: int = 0
    approvals_denied: int = 0

    # Tools
    tool_calls: int = 0

    # Quality
    hallucinated_success_count: int = 0
    failure_codes: List[str] = field(default_factory=list)

    # Cost
    cost_estimate: float = 0.0
    tokens_used: int = 0

    # Artifacts
    artifacts: List[str] = field(default_factory=list)
    memories_written: List[str] = field(default_factory=list)

    def calculate_rates(self) -> Dict[str, float]:
        """Calculează rate și KPIs"""
        return {
            "success_rate": 1.0 if self.success else 0.0,
            "verification_rate": self.verified_steps / max(1, self.total_steps),
            "retry_rate": self.retries / max(1, self.total_steps),
            "replan_rate": self.replans / max(1, self.total_steps),
            "approval_denied_rate": self.approvals_denied
            / max(1, self.approvals_requested),
            "hallucination_rate": self.hallucinated_success_count
            / max(1, self.total_steps),
            "avg_step_duration": self.duration_sec / max(1, self.total_steps),
        }

    def to_dict(self) -> Dict:
        """Serialize to dict"""
        return {
            "mission_id": self.mission_id,
            "success": self.success,
            "verified_success": self.verified_success,
            "duration_sec": round(self.duration_sec, 2),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_steps": self.total_steps,
            "verified_steps": self.verified_steps,
            "retries": self.retries,
            "replans": self.replans,
            "approvals_requested": self.approvals_requested,
            "approvals_denied": self.approvals_denied,
            "tool_calls": self.tool_calls,
            "hallucinated_success_count": self.hallucinated_success_count,
            "failure_codes": self.failure_codes,
            "cost_estimate": round(self.cost_estimate, 4),
            "tokens_used": self.tokens_used,
            "rates": self.calculate_rates(),
        }


class MetricsCollector:
    """Colector și stocator de metrici"""

    def __init__(self, storage_path: str = ".agent/metrics"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.current_metrics: Optional[MissionMetrics] = None

    def start_mission(self, mission_id: str) -> MissionMetrics:
        """Începe colectarea pentru o misiune"""
        self.current_metrics = MissionMetrics(
            mission_id=mission_id,
            success=False,
            verified_success=False,
            duration_sec=0.0,
            start_time=datetime.now(),
            total_steps=0,
        )
        return self.current_metrics

    def record_step(self, verified: bool, is_retry: bool = False):
        """Înregistrează un pas"""
        if self.current_metrics:
            self.current_metrics.total_steps += 1
            if verified:
                self.current_metrics.verified_steps += 1
            if is_retry:
                self.current_metrics.retries += 1

    def record_replan(self):
        """Înregistrează replan"""
        if self.current_metrics:
            self.current_metrics.replans += 1

    def record_approval(self, granted: bool):
        """Înregistrează aprobare"""
        if self.current_metrics:
            self.current_metrics.approvals_requested += 1
            if not granted:
                self.current_metrics.approvals_denied += 1

    def record_tool_call(self):
        """Înregistrează apel tool"""
        if self.current_metrics:
            self.current_metrics.tool_calls += 1

    def record_failure(self, code: str):
        """Înregistrează eșec"""
        if self.current_metrics:
            if code not in self.current_metrics.failure_codes:
                self.current_metrics.failure_codes.append(code)

    def record_hallucination(self):
        """Înregistrează succes fabricat"""
        if self.current_metrics:
            self.current_metrics.hallucinated_success_count += 1

    def record_cost(self, cost: float, tokens: int):
        """Înregistrează cost"""
        if self.current_metrics:
            self.current_metrics.cost_estimate += cost
            self.current_metrics.tokens_used += tokens

    def finish_mission(self, success: bool, verified: bool = None):
        """Finalizează misiunea"""
        if self.current_metrics:
            self.current_metrics.success = success
            self.current_metrics.verified_success = (
                verified if verified is not None else success
            )
            self.current_metrics.end_time = datetime.now()
            self.current_metrics.duration_sec = (
                self.current_metrics.end_time - self.current_metrics.start_time
            ).total_seconds()

            # Save to disk
            self._save_metrics(self.current_metrics)

    def _save_metrics(self, metrics: MissionMetrics):
        """Salvează metricile pe disk"""
        filename = f"{metrics.mission_id}.json"
        (self.storage_path / filename).write_text(
            json.dumps(metrics.to_dict(), indent=2)
        )

    def get_latest_metrics(self) -> Optional[MissionMetrics]:
        """Get most recent metrics"""
        return self.current_metrics

    def get_all_metrics(self) -> List[Dict]:
        """Get all stored metrics"""
        metrics_list = []
        for f in self.storage_path.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                metrics_list.append(data)
            except:
                pass
        return metrics_list

    def aggregate_stats(self) -> Dict:
        """Get aggregated statistics"""
        all_metrics = self.get_all_metrics()

        if not all_metrics:
            return {"total_missions": 0}

        total = len(all_metrics)
        successful = sum(1 for m in all_metrics if m.get("success", False))

        return {
            "total_missions": total,
            "successful_missions": successful,
            "success_rate": successful / total,
            "avg_duration": sum(m.get("duration_sec", 0) for m in all_metrics) / total,
            "avg_steps": sum(m.get("total_steps", 0) for m in all_metrics) / total,
            "avg_retries": sum(m.get("retries", 0) for m in all_metrics) / total,
            "avg_cost": sum(m.get("cost_estimate", 0) for m in all_metrics) / total,
        }


# ==================== GLOBAL INSTANCE ====================

_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


if __name__ == "__main__":
    print("=== MISSION METRICS TEST ===\n")

    collector = get_metrics_collector()

    # Start mission
    metrics = collector.start_mission("test_mission_001")
    print(f"Started mission: {metrics.mission_id}")

    # Record steps
    collector.record_step(verified=True)
    collector.record_step(verified=True, is_retry=True)
    collector.record_step(verified=False)

    # Record replan
    collector.record_replan()

    # Record approvals
    collector.record_approval(granted=True)
    collector.record_approval(granted=False)

    # Record cost
    collector.record_cost(0.05, 1500)

    # Finish
    collector.finish_mission(success=True, verified=True)

    print(f"\nFinal metrics:")
    print(f"  Success: {metrics.success}")
    print(f"  Duration: {metrics.duration_sec:.2f}s")
    print(f"  Steps: {metrics.total_steps} (verified: {metrics.verified_steps})")
    print(f"  Retries: {metrics.retries}")
    print(f"  Replans: {metrics.replans}")

    rates = metrics.calculate_rates()
    print(f"\nRates:")
    for k, v in rates.items():
        print(f"  {k}: {v:.2f}")

    print("\n✅ Metrics test complete!")
