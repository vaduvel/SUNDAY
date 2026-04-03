"""Candidate Lane — V3 champion/candidate config separation.

Separates active (champion) configs from experimental (candidate) ones.
Any self-improvement proposed by Jarvis goes into candidate lane.
Promotion to champion only after passing eval thresholds.

Aligned with V3 SPEC.md §6.9 Promotion Layer and DB_SCHEMA agent_configs table.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Lane(str, Enum):
    CHAMPION  = "champion"
    CANDIDATE = "candidate"
    ARCHIVED  = "archived"


class ConfigType(str, Enum):
    PROMPTS          = "prompts"
    ROUTING          = "routing"
    THRESHOLDS       = "thresholds"
    TOOL_POLICY      = "tool_policy"
    SKILL_POLICY     = "skill_policy"
    EVAL_POLICY      = "eval_policy"
    RETRIEVAL_POLICY = "retrieval_policy"


class ConfigStatus(str, Enum):
    ACTIVE         = "active"
    PENDING_REVIEW = "pending_review"
    ARCHIVED       = "archived"


@dataclass
class AgentConfig:
    """A versioned config object — either champion or candidate."""
    config_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    lane: Lane = Lane.CHAMPION
    config_type: ConfigType = ConfigType.PROMPTS
    version_label: str = "v1.0"
    config_json: dict[str, Any] = field(default_factory=dict)
    parent_config_id: str = ""
    created_from_run_id: str = ""
    status: ConfigStatus = ConfigStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "config_id": self.config_id,
            "lane": self.lane,
            "config_type": self.config_type,
            "version_label": self.version_label,
            "config_json": self.config_json,
            "parent_config_id": self.parent_config_id,
            "created_from_run_id": self.created_from_run_id,
            "status": self.status,
            "created_at": self.created_at,
            "notes": self.notes,
        }


class CandidateLane:
    """
    Manages champion and candidate configs.

    Rules (from V3):
      - Champion lane has max ONE active config per config_type.
      - Candidate config cannot overwrite champion row.
      - Promotion requires explicit gate approval.
      - Every config change has an audit trail.

    Usage:
        lane = get_candidate_lane()

        # get active champion config
        champion = lane.get_champion(ConfigType.PROMPTS)

        # propose a candidate improvement
        candidate = lane.propose_candidate(
            config_type=ConfigType.PROMPTS,
            config_json={"system_prompt": "improved version..."},
            created_from_run_id="run-123",
            notes="Tighter planning prompt for engineering tasks",
        )

        # after eval passes, promote
        lane.promote(candidate.config_id, approved_by="human")
    """

    def __init__(self, vault_path: str = ".agent/candidate_lane"):
        self.vault = Path(vault_path)
        self.vault.mkdir(parents=True, exist_ok=True)
        self.configs_file = self.vault / "configs.jsonl"
        self.audit_file = self.vault / "audit.jsonl"
        self._configs: dict[str, AgentConfig] = {}
        self._load()
        self._seed_defaults()

    # ── champion access ───────────────────────────────────────────

    def get_champion(self, config_type: ConfigType) -> AgentConfig | None:
        """Return the active champion config for a given type."""
        for cfg in self._configs.values():
            if (cfg.lane == Lane.CHAMPION
                    and cfg.config_type == config_type
                    and cfg.status == ConfigStatus.ACTIVE):
                return cfg
        return None

    def get_champion_value(self, config_type: ConfigType, key: str, default: Any = None) -> Any:
        """Convenience: get a specific key from champion config."""
        cfg = self.get_champion(config_type)
        if cfg:
            return cfg.config_json.get(key, default)
        return default

    # ── candidate management ──────────────────────────────────────

    def propose_candidate(
        self,
        config_type: ConfigType,
        config_json: dict[str, Any],
        created_from_run_id: str = "",
        notes: str = "",
    ) -> AgentConfig:
        """Create a new candidate config (does NOT affect champion)."""
        champion = self.get_champion(config_type)
        candidate = AgentConfig(
            lane=Lane.CANDIDATE,
            config_type=config_type,
            version_label=self._next_version(config_type),
            config_json=config_json,
            parent_config_id=champion.config_id if champion else "",
            created_from_run_id=created_from_run_id,
            status=ConfigStatus.PENDING_REVIEW,
            notes=notes,
        )
        self._configs[candidate.config_id] = candidate
        self._save_config(candidate)
        self._audit("proposed_candidate", candidate.config_id, notes)
        return candidate

    def list_candidates(self, config_type: ConfigType | None = None) -> list[AgentConfig]:
        """List all pending candidate configs."""
        results = [
            cfg for cfg in self._configs.values()
            if cfg.lane == Lane.CANDIDATE and cfg.status == ConfigStatus.PENDING_REVIEW
        ]
        if config_type:
            results = [c for c in results if c.config_type == config_type]
        return sorted(results, key=lambda c: -c.created_at)

    # ── promotion ─────────────────────────────────────────────────

    def promote(self, candidate_config_id: str, approved_by: str = "system") -> AgentConfig:
        """
        Promote a candidate to champion.
        Archives the old champion. Requires the candidate to exist and be pending.
        """
        candidate = self._configs.get(candidate_config_id)
        if not candidate:
            raise ValueError(f"Config {candidate_config_id} not found")
        if candidate.lane != Lane.CANDIDATE:
            raise ValueError(f"Config {candidate_config_id} is not a candidate")

        # archive current champion
        old_champion = self.get_champion(candidate.config_type)
        if old_champion:
            old_champion.lane = Lane.ARCHIVED
            old_champion.status = ConfigStatus.ARCHIVED
            self._save_config(old_champion)
            self._audit("archived_champion", old_champion.config_id, f"replaced by {candidate_config_id}")

        # promote candidate
        candidate.lane = Lane.CHAMPION
        candidate.status = ConfigStatus.ACTIVE
        self._save_config(candidate)
        self._audit("promoted_to_champion", candidate_config_id, f"approved_by={approved_by}")
        return candidate

    def reject(self, candidate_config_id: str, reason: str = "") -> None:
        """Reject a candidate config."""
        candidate = self._configs.get(candidate_config_id)
        if candidate:
            candidate.status = ConfigStatus.ARCHIVED
            candidate.lane = Lane.ARCHIVED
            self._save_config(candidate)
            self._audit("rejected_candidate", candidate_config_id, reason)

    # ── utilities ────────────────────────────────────────────────

    def diff(self, candidate_config_id: str) -> dict:
        """Show diff between candidate and current champion."""
        candidate = self._configs.get(candidate_config_id)
        if not candidate:
            return {}
        champion = self.get_champion(candidate.config_type)
        return {
            "config_type": candidate.config_type,
            "candidate_id": candidate_config_id,
            "champion_id": champion.config_id if champion else None,
            "candidate_values": candidate.config_json,
            "champion_values": champion.config_json if champion else {},
            "notes": candidate.notes,
        }

    def summary(self) -> dict:
        champions = [c for c in self._configs.values() if c.lane == Lane.CHAMPION and c.status == ConfigStatus.ACTIVE]
        candidates = [c for c in self._configs.values() if c.lane == Lane.CANDIDATE]
        return {
            "active_champions": len(champions),
            "pending_candidates": len(candidates),
            "champion_types": [c.config_type for c in champions],
        }

    # ── persistence ──────────────────────────────────────────────

    def _save_config(self, cfg: AgentConfig) -> None:
        # rewrite full file (simple approach for file-based store)
        lines = []
        self._configs[cfg.config_id] = cfg
        for c in self._configs.values():
            lines.append(json.dumps(c.as_dict(), ensure_ascii=False))
        try:
            self.configs_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass

    def _audit(self, action: str, config_id: str, notes: str) -> None:
        entry = json.dumps({
            "ts": time.time(),
            "action": action,
            "config_id": config_id,
            "notes": notes,
        }, ensure_ascii=False)
        try:
            with self.audit_file.open("a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except OSError:
            pass

    def _load(self) -> None:
        if not self.configs_file.exists():
            return
        for line in self.configs_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                cfg = AgentConfig(
                    config_id=d["config_id"],
                    lane=Lane(d["lane"]),
                    config_type=ConfigType(d["config_type"]),
                    version_label=d.get("version_label", "v1.0"),
                    config_json=d.get("config_json", {}),
                    parent_config_id=d.get("parent_config_id", ""),
                    created_from_run_id=d.get("created_from_run_id", ""),
                    status=ConfigStatus(d.get("status", "active")),
                    created_at=d.get("created_at", time.time()),
                    notes=d.get("notes", ""),
                )
                self._configs[cfg.config_id] = cfg
            except (KeyError, ValueError):
                pass

    def _seed_defaults(self) -> None:
        """Seed default champion configs if none exist."""
        for ct in ConfigType:
            if not self.get_champion(ct):
                default = AgentConfig(
                    lane=Lane.CHAMPION,
                    config_type=ct,
                    version_label="v1.0-seed",
                    config_json={"seeded": True},
                    notes="Default seeded champion",
                    status=ConfigStatus.ACTIVE,
                )
                self._configs[default.config_id] = default
                self._save_config(default)

    def _next_version(self, config_type: ConfigType) -> str:
        champions = [c for c in self._configs.values() if c.config_type == config_type]
        return f"v{len(champions) + 1}.0-candidate"


# ── Singleton ─────────────────────────────────────────────────────

_candidate_lane: CandidateLane | None = None


def get_candidate_lane(vault_path: str = ".agent/candidate_lane") -> CandidateLane:
    global _candidate_lane
    if _candidate_lane is None:
        _candidate_lane = CandidateLane(vault_path)
    return _candidate_lane
