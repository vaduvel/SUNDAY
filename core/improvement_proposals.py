"""Improvement Proposals — V3 structured self-improvement entity.

When Jarvis identifies a potential improvement, it creates a proposal.
The proposal enters candidate lane — NEVER directly into champion.
Promotion only after eval scores pass thresholds.

Aligned with V3 SPEC.md §8 Allowed self-improvement + DB_SCHEMA improvement_proposals.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ProposalStatus(str, Enum):
    DRAFTED        = "drafted"
    QUEUED_EVAL    = "queued_for_eval"
    EVAL_RUNNING   = "eval_running"
    EVAL_PASSED    = "eval_passed"
    EVAL_FAILED    = "eval_failed"
    ON_HOLD        = "on_hold"
    PROMOTED       = "promoted"
    REJECTED       = "rejected"


class TargetType(str, Enum):
    PROMPT          = "prompt"
    ROUTING         = "routing"
    SKILL           = "skill"
    EVAL_POLICY     = "eval_policy"
    RETRIEVAL       = "retrieval_policy"
    RETRY_STRATEGY  = "retry_strategy"
    TASK_TEMPLATE   = "task_decomposition_template"


class RiskLevel(str, Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


# ── What Jarvis is ALLOWED to propose (from V3 SPEC §8) ──────────
ALLOWED_TARGET_TYPES = {
    TargetType.PROMPT,
    TargetType.ROUTING,
    TargetType.SKILL,
    TargetType.EVAL_POLICY,
    TargetType.RETRIEVAL,
    TargetType.RETRY_STRATEGY,
    TargetType.TASK_TEMPLATE,
}

# ── What Jarvis is NEVER allowed to propose ───────────────────────
FORBIDDEN_TARGET_TYPES = {
    "model_weights",
    "root_permissions",
    "production_secrets",
    "approval_policies",
    "critical_deny_lists",
    "blast_radius_limits",
}


@dataclass
class ImprovementProposal:
    """A single structured self-improvement proposal."""
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_run_id: str = ""
    target_type: TargetType = TargetType.PROMPT
    proposal_summary: str = ""
    rationale: str = ""
    evidence: list[str] = field(default_factory=list)   # e.g. ["3/10 runs failed at step X"]
    patch: dict[str, Any] = field(default_factory=dict) # the actual proposed change
    expected_gain: float = 0.0                          # estimated improvement 0.0-1.0
    risk_level: RiskLevel = RiskLevel.LOW
    status: ProposalStatus = ProposalStatus.DRAFTED
    candidate_config_id: str = ""                       # set after candidate lane entry
    eval_score: float | None = None
    eval_run_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    rejected_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "source_run_id": self.source_run_id,
            "target_type": self.target_type,
            "proposal_summary": self.proposal_summary,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "patch": self.patch,
            "expected_gain": round(self.expected_gain, 4),
            "risk_level": self.risk_level,
            "status": self.status,
            "candidate_config_id": self.candidate_config_id,
            "eval_score": self.eval_score,
            "eval_run_id": self.eval_run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rejected_reason": self.rejected_reason,
        }

    def brief(self) -> str:
        return (
            f"[{self.status}] {self.target_type}: {self.proposal_summary[:60]} "
            f"(gain={self.expected_gain:.0%}, risk={self.risk_level})"
        )


class ImprovementProposals:
    """
    Registry of all improvement proposals.

    Usage:
        proposals = get_proposals()

        # Jarvis proposes an improvement after detecting a pattern
        p = proposals.propose(
            source_run_id="run-abc",
            target_type=TargetType.PROMPT,
            summary="Tighten planning prompt for engineering tasks",
            rationale="Observed plan drift on 3/10 engineering runs",
            evidence=["run-1: step overexpanded", "run-5: scope creep"],
            patch={"planning_prompt_suffix": "Keep plan under 5 steps."},
            expected_gain=0.15,
            risk_level=RiskLevel.LOW,
        )

        # queue for eval
        proposals.queue_for_eval(p.proposal_id, eval_run_id="eval-xyz")

        # record eval result
        proposals.record_eval_result(p.proposal_id, score=0.82, passed=True)

        # promote (after promotion gate approves)
        proposals.mark_promoted(p.proposal_id, candidate_config_id="cfg-123")
    """

    def __init__(self, vault_path: str = ".agent/proposals"):
        self.vault = Path(vault_path)
        self.vault.mkdir(parents=True, exist_ok=True)
        self.proposals_file = self.vault / "proposals.jsonl"
        self._proposals: dict[str, ImprovementProposal] = {}
        self._load()

    # ── propose ──────────────────────────────────────────────────

    def propose(
        self,
        source_run_id: str,
        target_type: TargetType,
        summary: str,
        rationale: str,
        evidence: list[str] | None = None,
        patch: dict[str, Any] | None = None,
        expected_gain: float = 0.0,
        risk_level: RiskLevel = RiskLevel.LOW,
    ) -> ImprovementProposal:
        """Create a new improvement proposal."""
        # Safety: reject forbidden target types
        if str(target_type) in FORBIDDEN_TARGET_TYPES:
            raise ValueError(
                f"Jarvis cannot propose changes to '{target_type}' — "
                "this surface requires human-only changes (V3 SPEC §8)."
            )

        p = ImprovementProposal(
            source_run_id=source_run_id,
            target_type=target_type,
            proposal_summary=summary,
            rationale=rationale,
            evidence=evidence or [],
            patch=patch or {},
            expected_gain=expected_gain,
            risk_level=risk_level,
            status=ProposalStatus.DRAFTED,
        )
        self._proposals[p.proposal_id] = p
        self._persist(p)
        return p

    # ── lifecycle transitions ─────────────────────────────────────

    def queue_for_eval(self, proposal_id: str, eval_run_id: str = "") -> ImprovementProposal:
        p = self._get(proposal_id)
        p.status = ProposalStatus.QUEUED_EVAL
        p.eval_run_id = eval_run_id
        p.updated_at = time.time()
        self._persist(p)
        return p

    def mark_eval_running(self, proposal_id: str) -> ImprovementProposal:
        p = self._get(proposal_id)
        p.status = ProposalStatus.EVAL_RUNNING
        p.updated_at = time.time()
        self._persist(p)
        return p

    def attach_candidate_config(
        self, proposal_id: str, candidate_config_id: str
    ) -> ImprovementProposal:
        """Attach a candidate/config reference before or during eval."""
        p = self._get(proposal_id)
        p.candidate_config_id = candidate_config_id
        p.updated_at = time.time()
        self._persist(p)
        return p

    def record_eval_result(
        self, proposal_id: str, score: float, passed: bool
    ) -> ImprovementProposal:
        p = self._get(proposal_id)
        p.eval_score = round(score, 4)
        p.status = ProposalStatus.EVAL_PASSED if passed else ProposalStatus.EVAL_FAILED
        p.updated_at = time.time()
        self._persist(p)
        return p

    def mark_on_hold(self, proposal_id: str, reason: str = "") -> ImprovementProposal:
        """Keep a proposal alive but blocked behind more evaluation work."""
        p = self._get(proposal_id)
        p.status = ProposalStatus.ON_HOLD
        p.rejected_reason = reason
        p.updated_at = time.time()
        self._persist(p)
        return p

    def mark_promoted(self, proposal_id: str, candidate_config_id: str = "") -> ImprovementProposal:
        p = self._get(proposal_id)
        if p.status not in (ProposalStatus.EVAL_PASSED,):
            raise ValueError(
                f"Cannot promote proposal {proposal_id} — status is '{p.status}', "
                "must be 'eval_passed' first."
            )
        p.status = ProposalStatus.PROMOTED
        p.candidate_config_id = candidate_config_id
        p.updated_at = time.time()
        self._persist(p)
        return p

    def reject(self, proposal_id: str, reason: str = "") -> ImprovementProposal:
        p = self._get(proposal_id)
        p.status = ProposalStatus.REJECTED
        p.rejected_reason = reason
        p.updated_at = time.time()
        self._persist(p)
        return p

    # ── queries ──────────────────────────────────────────────────

    def list_by_status(self, status: ProposalStatus) -> list[ImprovementProposal]:
        return sorted(
            [p for p in self._proposals.values() if p.status == status],
            key=lambda p: -p.created_at,
        )

    def pending(self) -> list[ImprovementProposal]:
        return self.list_by_status(ProposalStatus.DRAFTED) + \
               self.list_by_status(ProposalStatus.QUEUED_EVAL)

    def get(self, proposal_id: str) -> ImprovementProposal | None:
        return self._proposals.get(proposal_id)

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        for p in self._proposals.values():
            status = str(p.status.value)
            by_status[status] = by_status.get(status, 0) + 1
        return {
            "total": len(self._proposals),
            "by_status": by_status,
            "pending_eval": len(self.pending()),
        }

    def recent(
        self,
        limit: int = 5,
        statuses: list[ProposalStatus | str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the most recently updated proposals as plain dicts."""
        normalized_statuses = {
            str(status.value if isinstance(status, ProposalStatus) else status)
            for status in (statuses or [])
        }
        proposals = list(self._proposals.values())
        if normalized_statuses:
            proposals = [
                proposal
                for proposal in proposals
                if str(proposal.status.value) in normalized_statuses
            ]

        proposals.sort(key=lambda proposal: (proposal.updated_at, proposal.created_at), reverse=True)
        return [proposal.as_dict() for proposal in proposals[: max(0, int(limit))]]

    def dashboard(self) -> str:
        lines = [f"📋 Improvement Proposals ({len(self._proposals)} total)"]
        for status in ProposalStatus:
            items = self.list_by_status(status)
            if items:
                lines.append(f"\n  [{status.upper()}] {len(items)} proposal(s):")
                for p in items[:3]:
                    lines.append(f"    • {p.brief()}")
        return "\n".join(lines)

    # ── persistence ──────────────────────────────────────────────

    def _get(self, proposal_id: str) -> ImprovementProposal:
        p = self._proposals.get(proposal_id)
        if not p:
            raise ValueError(f"Proposal {proposal_id} not found")
        return p

    def _persist(self, p: ImprovementProposal) -> None:
        self._proposals[p.proposal_id] = p
        # rewrite full file
        lines = [json.dumps(pr.as_dict(), ensure_ascii=False)
                 for pr in self._proposals.values()]
        try:
            self.proposals_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass

    def _load(self) -> None:
        if not self.proposals_file.exists():
            return
        for line in self.proposals_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                p = ImprovementProposal(
                    proposal_id=d["proposal_id"],
                    source_run_id=d.get("source_run_id", ""),
                    target_type=TargetType(d["target_type"]),
                    proposal_summary=d.get("proposal_summary", ""),
                    rationale=d.get("rationale", ""),
                    evidence=d.get("evidence", []),
                    patch=d.get("patch", {}),
                    expected_gain=d.get("expected_gain", 0.0),
                    risk_level=RiskLevel(d.get("risk_level", "low")),
                    status=ProposalStatus(d.get("status", "drafted")),
                    candidate_config_id=d.get("candidate_config_id", ""),
                    eval_score=d.get("eval_score"),
                    eval_run_id=d.get("eval_run_id", ""),
                    created_at=d.get("created_at", time.time()),
                    updated_at=d.get("updated_at", time.time()),
                    rejected_reason=d.get("rejected_reason", ""),
                )
                self._proposals[p.proposal_id] = p
            except (KeyError, ValueError):
                pass


# ── Singleton ─────────────────────────────────────────────────────

_proposals: ImprovementProposals | None = None


def get_proposals(vault_path: str = ".agent/proposals") -> ImprovementProposals:
    global _proposals
    if _proposals is None:
        _proposals = ImprovementProposals(vault_path)
    return _proposals
