"""Executable Definition of Done for J.A.R.V.I.S. missions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


CRITICAL_FAILURE_CODES = {
    "RISK_POLICY_BLOCK",
    "VERIFICATION_FAIL",
    "HALLUCINATED_SUCCESS",
    "RECOVERY_FAIL",
    "UI_GROUNDING_FAIL",
}


@dataclass
class DoneCriterion:
    name: str
    passed: bool
    detail: str
    severity: str = "required"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class DefinitionOfDoneReport:
    mission_id: str
    done: bool
    score: float
    summary: str
    criteria: List[DoneCriterion] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "done": self.done,
            "score": round(self.score, 4),
            "summary": self.summary,
            "criteria": [criterion.to_dict() for criterion in self.criteria],
        }


class DefinitionOfDoneEvaluator:
    """Evaluate whether a mission meets the blueprint completion bar."""

    def evaluate(
        self,
        *,
        mission_id: str,
        contract: Any,
        results: List[Dict[str, Any]],
        metrics: Dict[str, Any],
        final_output: str,
        qa_text: str,
        memory_written: List[str] | None = None,
    ) -> Dict[str, Any]:
        criteria: List[DoneCriterion] = []
        memory_written = memory_written or []

        total_steps = len(getattr(contract, "steps", []))
        verified_steps = sum(1 for item in results if item.get("verified"))
        deliverable_path = getattr(contract, "context", {}).get("deliverable_path")
        contract_context = getattr(contract, "context", {}) or {}
        deliverable_exists = bool(final_output.strip()) and (
            not deliverable_path or Path(deliverable_path).exists()
        )
        requires_real_source_changes = bool(contract_context.get("requires_real_source_changes"))
        real_artifacts: List[str] = []
        if requires_real_source_changes:
            ignored = {str(Path(deliverable_path).resolve())} if deliverable_path else set()
            runtime_roots = {
                str((Path.cwd() / "workspace" / "orchestrator").resolve()),
                str((Path.cwd() / ".agent" / "runtime_reports").resolve()),
            }
            for item in results:
                result_payload = item.get("result") or {}
                for artifact in result_payload.get("artifacts", []) or []:
                    try:
                        normalized = str(Path(artifact).resolve())
                    except Exception:
                        continue
                    if normalized in ignored:
                        continue
                    if any(
                        normalized == root or normalized.startswith(root + "/")
                        for root in runtime_roots
                    ):
                        continue
                    if normalized not in real_artifacts:
                        real_artifacts.append(normalized)
        failure_codes = set(metrics.get("failure_codes", []))
        critical_failures = sorted(failure_codes.intersection(CRITICAL_FAILURE_CODES))
        verification_rate = float(metrics.get("rates", {}).get("verification_rate", 0.0))

        criteria.append(
            DoneCriterion(
                "plan_has_steps",
                total_steps > 0,
                f"{total_steps} planned step(s)",
            )
        )
        criteria.append(
            DoneCriterion(
                "all_steps_verified",
                total_steps > 0 and verified_steps == total_steps,
                f"{verified_steps}/{total_steps} verified step(s)",
            )
        )
        criteria.append(
            DoneCriterion(
                "deliverable_present",
                deliverable_exists,
                "Final output exists and linked artifacts resolve",
            )
        )
        if requires_real_source_changes:
            criteria.append(
                DoneCriterion(
                    "real_source_changes_present",
                    bool(real_artifacts),
                    "Real project artifacts detected"
                    if real_artifacts
                    else "No project artifacts were changed outside the orchestrator workspace",
                )
            )
        criteria.append(
            DoneCriterion(
                "quality_review_present",
                bool(qa_text.strip()),
                "QA review generated",
            )
        )
        criteria.append(
            DoneCriterion(
                "verification_rate_complete",
                verification_rate >= 1.0,
                f"verification_rate={verification_rate:.2f}",
            )
        )
        criteria.append(
            DoneCriterion(
                "no_critical_failures",
                not critical_failures,
                "No critical failure codes"
                if not critical_failures
                else f"Critical failures: {', '.join(critical_failures)}",
            )
        )
        criteria.append(
            DoneCriterion(
                "memory_writeback_complete",
                len(memory_written) >= 2,
                f"{len(memory_written)} memory artifact(s) written",
                severity="advisory",
            )
        )

        required = [criterion for criterion in criteria if criterion.severity == "required"]
        passed_required = sum(1 for criterion in required if criterion.passed)
        score = passed_required / max(1, len(required))
        done = all(criterion.passed for criterion in required)
        summary = (
            "Definition of Done passed"
            if done
            else "Definition of Done incomplete"
        )

        return DefinitionOfDoneReport(
            mission_id=mission_id,
            done=done,
            score=score,
            summary=summary,
            criteria=criteria,
        ).to_dict()
