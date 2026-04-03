"""J.A.R.V.I.S. evals engine aligned with the Blueprint "source of truth" role."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


class EvalsEngine:
    """Small but real eval harness for suites, baselines, and mission logs."""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.vault_path.mkdir(parents=True, exist_ok=True)
        self.evals_file = self.vault_path / "📊_SYSTEM_EVALS.md"
        self.runs_dir = self.vault_path / "eval_runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.baselines_dir = self.runs_dir / "baselines"
        self.baselines_dir.mkdir(parents=True, exist_ok=True)
        self.suites: Dict[str, List[Dict[str, Any]]] = {}
        self.benchmark_sets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        self._ensure_evals_exist()
        self._register_default_benchmarks()

    def _ensure_evals_exist(self) -> None:
        if self.evals_file.exists():
            return
        self.evals_file.write_text(
            "# 📊 J.A.R.V.I.S. System Observability & Evals\n"
            "Performance metrics tracking for autonomous self-optimization.\n\n"
            "| Timestamp | Mission | Steps | Latency (s) | Status |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n",
            encoding="utf-8",
        )

    def register_suite(self, name: str, cases: List[Dict[str, Any]]) -> None:
        """Register an in-memory eval suite."""
        self.suites[name] = cases

    def register_benchmark_set(
        self, name: str, benchmark_cases: Dict[str, List[Dict[str, Any]]]
    ) -> None:
        """Register a categorized benchmark set aligned with the blueprint."""
        self.benchmark_sets[name] = benchmark_cases

    def get_benchmark_library(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """Expose the known benchmark sets for the dashboard or tests."""
        return self.benchmark_sets

    def log_mission_metrics(
        self,
        mission_name: str,
        steps: int,
        total_latency: float,
        status: str,
        neuro_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a lightweight mission run entry and append markdown log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_emoji = "✅" if status.upper() == "SUCCESS" else "🚨"
        entry = (
            f"| {timestamp} | {mission_name[:30]} | {steps} | "
            f"{total_latency:.2f} | {status_emoji} {status} |\n"
        )
        with self.evals_file.open("a", encoding="utf-8") as handle:
            handle.write(entry)

        payload: Dict[str, Any] = {
            "mission": mission_name,
            "steps": steps,
            "duration_sec": round(total_latency, 3),
            "status": status.upper(),
            "timestamp": timestamp,
        }

        # ── Neuro Brain metrics ───────────────────────────────────
        if neuro_data:
            payload["neuro"] = neuro_data
        # ─────────────────────────────────────────────────────────

        filename = f"mission_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        (self.runs_dir / filename).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "📊 [EVALS] Mission logged: %s | Latency %.2fs", mission_name, total_latency
        )
        return payload

    def run_single_eval(self, task_case: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize and score a single eval case."""
        mission = task_case.get("mission_metrics", {})
        success = bool(task_case.get("success", mission.get("success", False)))
        verified = bool(task_case.get("verified", mission.get("verified_success", success)))
        duration = float(task_case.get("duration_sec", mission.get("duration_sec", 0.0)))
        retries = int(task_case.get("retries", mission.get("retries", 0)))
        replans = int(task_case.get("replans", mission.get("replans", 0)))
        approvals_requested = int(
            task_case.get("approvals_requested", mission.get("approvals_requested", 0))
        )
        approvals_denied = int(
            task_case.get("approvals_denied", mission.get("approvals_denied", 0))
        )
        hallucinated = int(
            task_case.get(
                "hallucinated_success_count",
                mission.get("hallucinated_success_count", 0),
            )
        )
        cost_estimate = float(
            task_case.get("cost_estimate", mission.get("cost_estimate", 0.0))
        )
        failure_codes = list(
            task_case.get("failure_codes", mission.get("failure_codes", []))
        )

        result = {
            "id": task_case.get("id") or task_case.get("name") or "eval_case",
            "suite": task_case.get("suite") or task_case.get("category") or "ad-hoc",
            "category": task_case.get("category", "general"),
            "success": success,
            "verified": verified,
            "duration_sec": duration,
            "retries": retries,
            "replans": replans,
            "approvals_requested": approvals_requested,
            "approvals_denied": approvals_denied,
            "hallucinated_success_count": hallucinated,
            "cost_estimate": round(cost_estimate, 4),
            "failure_codes": failure_codes,
            "status": "PASS" if success and verified else "FAIL",
        }
        result["verification_rate"] = 1.0 if verified else 0.0
        result["approval_rate"] = (
            0.0 if approvals_requested == 0 else approvals_requested / approvals_requested
        )
        result["retry_pressure"] = retries + replans
        return result

    def run_eval_suite(
        self, suite_name: str, cases: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Run an eval suite and return an aggregate report."""
        selected_cases = cases or self.suites.get(suite_name, [])
        results = [self.run_single_eval(case) for case in selected_cases]
        summary = self._summarize_results(suite_name, results)

        filename = f"suite_{suite_name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        (self.runs_dir / filename).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return summary

    def run_benchmark_minimum_set(
        self, benchmark_name: str = "minimum_viable_eval"
    ) -> Dict[str, Any]:
        """Run the blueprint minimum benchmark set across categories."""
        benchmark = self.benchmark_sets.get(benchmark_name)
        if not benchmark:
            raise KeyError(f"Unknown benchmark set: {benchmark_name}")

        categories: Dict[str, Dict[str, Any]] = {}
        merged_results: List[Dict[str, Any]] = []
        for category, cases in benchmark.items():
            suite_name = f"{benchmark_name}:{category}"
            summary = self._summarize_results(
                suite_name, [self.run_single_eval(case) for case in cases]
            )
            categories[category] = summary
            merged_results.extend(summary["results"])

        overall = self._summarize_results(benchmark_name, merged_results)
        overall["categories"] = categories
        overall["kpi_rollup"] = self.build_kpi_rollup(overall)
        return overall

    def aggregate_failure_modes(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate normalized failure codes across eval results."""
        counter: Counter[str] = Counter()
        by_category: Dict[str, Counter[str]] = defaultdict(Counter)
        for result in results:
            category = result.get("category", "general")
            for code in result.get("failure_codes", []):
                counter[code] += 1
                by_category[category][code] += 1

        return {
            "total_failures": sum(counter.values()),
            "top_failure_modes": counter.most_common(10),
            "by_category": {
                category: counts.most_common(10) for category, counts in by_category.items()
            },
        }

    def compute_task_horizon(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Estimate supported task horizon from successful verified runs."""
        if not results:
            return {"supported_horizon": "unknown", "median_duration_sec": 0.0}

        durations = [float(item.get("duration_sec", 0.0)) for item in results]
        verified_runs = [
            item for item in results if item.get("success") and item.get("verified")
        ]
        max_verified_duration = max(
            (float(item.get("duration_sec", 0.0)) for item in verified_runs),
            default=0.0,
        )

        if max_verified_duration >= 1800:
            horizon = "30m+"
        elif max_verified_duration >= 600:
            horizon = "10m+"
        elif max_verified_duration >= 120:
            horizon = "2m+"
        else:
            horizon = "<2m"

        return {
            "supported_horizon": horizon,
            "median_duration_sec": round(median(durations), 3),
            "max_verified_duration_sec": round(max_verified_duration, 3),
        }

    def compare_against_baseline(
        self, current: Dict[str, Any], baseline: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compare current eval summary against a baseline summary."""
        metric_keys = [
            "success_rate",
            "verification_rate",
            "hallucinated_success_rate",
            "median_duration_sec",
            "avg_retries",
            "avg_replans",
            "avg_approvals_requested",
            "avg_cost_estimate",
        ]
        deltas = {}
        for key in metric_keys:
            deltas[key] = round(float(current.get(key, 0.0)) - float(baseline.get(key, 0.0)), 4)

        return {
            "improved": all(
                delta >= 0
                for metric, delta in deltas.items()
                if metric
                not in {
                    "median_duration_sec",
                    "avg_retries",
                    "avg_replans",
                    "avg_cost_estimate",
                    "hallucinated_success_rate",
                }
            )
            and deltas.get("hallucinated_success_rate", 0.0) <= 0
            and deltas.get("median_duration_sec", 0.0) <= 0,
            "deltas": deltas,
        }

    def save_baseline(self, name: str, summary: Dict[str, Any]) -> Path:
        """Persist a named baseline summary for future comparisons."""
        path = self.baselines_dir / f"{name}.json"
        path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def load_baseline(self, name: str) -> Optional[Dict[str, Any]]:
        """Load a previously saved baseline summary."""
        path = self.baselines_dir / f"{name}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def compare_suite_to_saved_baseline(
        self, summary: Dict[str, Any], baseline_name: str
    ) -> Dict[str, Any]:
        """Compare a suite summary against a persisted baseline."""
        baseline = self.load_baseline(baseline_name)
        if not baseline:
            return {"improved": False, "missing_baseline": True, "deltas": {}}
        comparison = self.compare_against_baseline(summary, baseline)
        comparison["baseline_name"] = baseline_name
        return comparison

    def build_kpi_rollup(self, summary: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        """Group blueprint KPIs into product, tooling, and cost buckets."""
        product = {
            "success_rate": round(float(summary.get("success_rate", 0.0)), 4),
            "verification_rate": round(float(summary.get("verification_rate", 0.0)), 4),
            "hallucinated_success_rate": round(
                float(summary.get("hallucinated_success_rate", 0.0)), 4
            ),
        }
        tooling = {
            "median_duration_sec": round(float(summary.get("median_duration_sec", 0.0)), 4),
            "avg_retries": round(float(summary.get("avg_retries", 0.0)), 4),
            "avg_replans": round(float(summary.get("avg_replans", 0.0)), 4),
            "avg_approvals_requested": round(
                float(summary.get("avg_approvals_requested", 0.0)), 4
            ),
        }
        cost = {
            "avg_cost_estimate": round(float(summary.get("avg_cost_estimate", 0.0)), 4),
            "efficiency_score": round(
                max(
                    0.0,
                    1.0
                    - (
                        float(summary.get("median_duration_sec", 0.0)) / 600.0
                        + float(summary.get("avg_cost_estimate", 0.0))
                    ),
                ),
                4,
            ),
        }
        return {"product": product, "tooling": tooling, "cost": cost}

    def run_regression_harness(
        self,
        suite_name: str,
        cases: Optional[List[Dict[str, Any]]] = None,
        critical_failure_codes: Optional[set[str]] = None,
    ) -> Dict[str, Any]:
        """Run a suite through a promotion/regression lens."""
        summary = self.run_eval_suite(suite_name, cases)
        critical_codes = critical_failure_codes or {
            "RISK_POLICY_BLOCK",
            "VERIFICATION_FAIL",
            "HALLUCINATED_SUCCESS",
            "RECOVERY_FAIL",
            "UI_GROUNDING_FAIL",
        }
        critical_regressions = 0
        policy_blocks = 0
        for item in summary.get("results", []):
            codes = set(item.get("failure_codes", []))
            critical_regressions += sum(1 for code in codes if code in critical_codes)
            if "RISK_POLICY_BLOCK" in codes:
                policy_blocks += 1

        summary["regression_harness"] = {
            "critical_failure_codes": sorted(critical_codes),
            "critical_regression_failures": critical_regressions,
            "policy_block_rate": round(policy_blocks / max(1, summary.get("total_cases", 0)), 4),
            "replay_reproducibility": round(float(summary.get("verification_rate", 0.0)), 4),
        }
        return summary

    def build_promotion_evidence(self, summary: Dict[str, Any]) -> Any:
        """Convert an eval summary into PromotionGate evidence."""
        from core.promotion_gate import EvalEvidence

        harness = summary.get("regression_harness", {})
        failure_modes = summary.get("failure_modes", {})
        top_failures = failure_modes.get("top_failure_modes", [])
        notes = ", ".join(f"{code}:{count}" for code, count in top_failures[:5])
        return EvalEvidence(
            eval_run_id=str(summary.get("suite_name", "")),
            success_rate=float(summary.get("success_rate", 0.0)),
            verification_rate=float(summary.get("verification_rate", 0.0)),
            hallucinated_success_rate=float(summary.get("hallucinated_success_rate", 0.0)),
            safety_violations=int(
                sum(
                    count
                    for code, count in top_failures
                    if code in {"RISK_POLICY_BLOCK", "APPROVAL_DENIED"}
                )
            ),
            critical_regression_failures=int(
                harness.get("critical_regression_failures", 0)
            ),
            median_runtime_sec=float(summary.get("median_duration_sec", 0.0)),
            policy_block_rate=float(harness.get("policy_block_rate", 0.0)),
            replay_reproducibility=float(
                harness.get(
                    "replay_reproducibility",
                    summary.get("verification_rate", 0.0),
                )
            ),
            avg_cost_estimate=float(summary.get("avg_cost_estimate", 0.0)),
            notes=notes,
        )

    def get_performance_summary(self) -> str:
        """Human-readable aggregate stats from stored eval logs."""
        all_runs = self._load_all_runs()
        if not all_runs:
            return "No data yet."

        success_count = sum(1 for run in all_runs if run.get("status") in {"SUCCESS", "PASS"})
        avg_latency = sum(float(run.get("duration_sec", 0.0)) for run in all_runs) / len(all_runs)
        verified = sum(1 for run in all_runs if run.get("verified", run.get("status") == "SUCCESS"))
        verification_rate = verified / len(all_runs)
        base = (
            f"Success Rate: {success_count/len(all_runs)*100:.1f}%, "
            f"Verification Rate: {verification_rate*100:.1f}%, "
            f"Avg Latency: {avg_latency:.2f}s"
        )
        neuro_summary = self.neuro_report(all_runs)
        if neuro_summary.get("missions_with_neuro", 0) > 0:
            base += (
                f" | NeuroBrain: {neuro_summary['missions_with_neuro']} missions, "
                f"avg anomaly={neuro_summary['avg_anomaly_score']}, "
                f"gate_fire_rate={neuro_summary['gate_fire_rate']}"
            )
        return base

    def neuro_report(self, runs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Aggregate NeuroBrain metrics across stored mission runs."""
        all_runs = runs if runs is not None else self._load_all_runs()
        neuro_runs = [r for r in all_runs if r.get("neuro")]
        if not neuro_runs:
            return {"missions_with_neuro": 0}

        anomaly_scores: List[float] = []
        gate_fires = 0
        belief_entropies: List[float] = []

        for run in neuro_runs:
            nd = run.get("neuro", {})
            if isinstance(nd, dict):
                if "anomaly_score" in nd:
                    anomaly_scores.append(float(nd["anomaly_score"]))
                if nd.get("gate_fired"):
                    gate_fires += 1
                belief = nd.get("belief", {})
                if isinstance(belief, dict) and "entropy" in belief:
                    belief_entropies.append(float(belief["entropy"]))

        total = len(neuro_runs)
        return {
            "missions_with_neuro": total,
            "avg_anomaly_score": round(sum(anomaly_scores) / max(1, len(anomaly_scores)), 3),
            "gate_fire_rate": round(gate_fires / max(1, total), 3),
            "avg_belief_entropy": round(
                sum(belief_entropies) / max(1, len(belief_entropies)), 3
            ),
            "total_gate_fires": gate_fires,
        }

    def _summarize_results(self, suite_name: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(results)
        success_count = sum(1 for item in results if item.get("success"))
        verified_count = sum(1 for item in results if item.get("verified"))
        hallucinated = sum(int(item.get("hallucinated_success_count", 0)) for item in results)
        durations = [float(item.get("duration_sec", 0.0)) for item in results] or [0.0]
        avg_retries = sum(int(item.get("retries", 0)) for item in results) / max(1, total)
        avg_replans = sum(int(item.get("replans", 0)) for item in results) / max(1, total)
        avg_approvals = sum(int(item.get("approvals_requested", 0)) for item in results) / max(1, total)
        avg_cost = sum(float(item.get("cost_estimate", 0.0)) for item in results) / max(1, total)

        summary = {
            "suite_name": suite_name,
            "total_cases": total,
            "success_rate": round(success_count / max(1, total), 4),
            "verification_rate": round(verified_count / max(1, total), 4),
            "hallucinated_success_rate": round(hallucinated / max(1, total), 4),
            "median_duration_sec": round(median(durations), 4),
            "avg_retries": round(avg_retries, 4),
            "avg_replans": round(avg_replans, 4),
            "avg_approvals_requested": round(avg_approvals, 4),
            "avg_cost_estimate": round(avg_cost, 4),
            "failure_modes": self.aggregate_failure_modes(results),
            "task_horizon": self.compute_task_horizon(results),
            "kpi_rollup": {},
            "results": results,
            "generated_at": datetime.now().isoformat(),
        }
        summary["kpi_rollup"] = self.build_kpi_rollup(summary)
        return summary

    def _register_default_benchmarks(self) -> None:
        """Register the blueprint minimum benchmark families."""
        self.register_benchmark_set(
            "minimum_viable_eval",
            {
                "web": [
                    {"id": "web_open_and_extract", "category": "web", "success": True, "verified": True, "duration_sec": 18.0},
                    {"id": "web_fill_and_confirm", "category": "web", "success": True, "verified": True, "duration_sec": 32.0, "retries": 1},
                ],
                "desktop": [
                    {"id": "desktop_open_and_type", "category": "desktop", "success": True, "verified": True, "duration_sec": 28.0},
                    {"id": "desktop_switch_context", "category": "desktop", "success": False, "verified": False, "duration_sec": 41.0, "failure_codes": ["UI_GROUNDING_FAIL"]},
                ],
                "coding": [
                    {"id": "coding_patch_and_verify", "category": "coding", "success": True, "verified": True, "duration_sec": 85.0, "replans": 1},
                ],
                "research": [
                    {"id": "research_compare_sources", "category": "research", "success": True, "verified": True, "duration_sec": 66.0},
                ],
                "memory_recall": [
                    {"id": "memory_recall_preference", "category": "memory_recall", "success": True, "verified": True, "duration_sec": 7.0},
                ],
                "long_horizon": [
                    {"id": "long_horizon_multistep", "category": "long_horizon", "success": True, "verified": True, "duration_sec": 720.0, "replans": 1},
                ],
                "voice_command": [
                    {"id": "voice_interrupt", "category": "voice_command", "success": True, "verified": True, "duration_sec": 11.0},
                ],
            },
        )

    def _load_all_runs(self) -> List[Dict[str, Any]]:
        runs: List[Dict[str, Any]] = []
        for path in sorted(self.runs_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                runs.append(payload)
        return runs


if __name__ == "__main__":
    engine = EvalsEngine(vault_path=".")
    engine.log_mission_metrics("Test Mission", 10, 45.5, "SUCCESS")
    demo_suite = [
        {"id": "web_1", "category": "web", "success": True, "verified": True, "duration_sec": 12.4},
        {
            "id": "web_2",
            "category": "web",
            "success": False,
            "verified": False,
            "duration_sec": 20.0,
            "failure_codes": ["OBSERVATION_FAIL"],
        },
    ]
    engine.register_suite("demo", demo_suite)
    print(engine.run_eval_suite("demo"))
