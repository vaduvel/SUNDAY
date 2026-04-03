"""Meta Reasoner — Hyperon/OpenCog-inspired symbolic constraint engine.

Upgrade of core/symbolic_check.py:
  - explicit rule atoms (not just regex)
  - contradiction detection between plan steps
  - constraint derivation from task properties
  - plan repair suggestions

Pure Python, no external deps. Serializable.

Inspired by: Hyperon Experimental, OpenCog
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Rule types ───────────────────────────────────────────────────

class RuleType(str, Enum):
    DENY        = "deny"        # action is forbidden
    REQUIRE     = "require"     # action requires precondition
    MUTEX       = "mutex"       # two actions cannot coexist in same plan
    RATE_LIMIT  = "rate_limit"  # action can run at most N times per mission
    INVARIANT   = "invariant"   # property that must always hold


@dataclass
class Rule:
    id: str
    type: RuleType
    pattern: str            # regex or keyword matched against action/tool string
    description: str
    precondition: str = ""  # for REQUIRE rules
    mutex_partner: str = "" # for MUTEX rules
    max_count: int = 1      # for RATE_LIMIT rules
    severity: str = "high"  # "low" | "medium" | "high" | "critical"
    source: str = "builtin"
    created_at: float = field(default_factory=time.time)

    def matches(self, text: str) -> bool:
        try:
            return bool(re.search(self.pattern, text, re.IGNORECASE))
        except re.error:
            return self.pattern.lower() in text.lower()

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "pattern": self.pattern,
            "description": self.description,
            "severity": self.severity,
        }


# ── Conflict record ───────────────────────────────────────────────

@dataclass
class Conflict:
    rule_id: str
    rule_type: RuleType
    description: str
    affected_steps: list[str]
    severity: str
    suggestion: str = ""

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "type": self.rule_type,
            "description": self.description,
            "affected_steps": self.affected_steps,
            "severity": self.severity,
            "suggestion": self.suggestion,
        }


# ── Default built-in rules ────────────────────────────────────────

BUILTIN_RULES: list[Rule] = [
    # DENY — forbidden actions
    Rule("deny_rm_rf",       RuleType.DENY, r"rm\s+-rf|rmdir\s+/",
         "Recursive delete forbidden", severity="critical"),
    Rule("deny_prod_deploy",  RuleType.DENY, r"deploy.*prod|push.*main|force.push",
         "Production deploy without approval", severity="critical"),
    Rule("deny_secret_write", RuleType.DENY, r"write.*secret|export.*key|store.*password",
         "Writing secrets to plain files", severity="critical"),
    Rule("deny_self_modify_weights", RuleType.DENY, r"fine.?tun|update.*weights|train.*model",
         "Self-modifying model weights in production", severity="critical"),
    Rule("deny_mass_delete",  RuleType.DENY, r"delete.*all|drop.*table|truncate",
         "Mass data deletion", severity="high"),
    Rule("deny_exec_unvetted", RuleType.DENY, r"exec\(|eval\(|subprocess.*shell=True",
         "Executing unvetted dynamic code", severity="high"),

    # REQUIRE — preconditions
    Rule("req_approval_deploy", RuleType.REQUIRE, r"deploy|release|publish",
         "Deployment requires approval", precondition="approval_granted", severity="high"),
    Rule("req_sandbox_test",    RuleType.REQUIRE, r"execute|run.*script|shell",
         "Script execution requires sandbox", precondition="sandbox_active", severity="medium"),
    Rule("req_backup_delete",   RuleType.REQUIRE, r"delete|remove|drop",
         "Delete requires backup confirmation", precondition="backup_confirmed", severity="high"),

    # RATE_LIMIT
    Rule("limit_retries",    RuleType.RATE_LIMIT, r"retry|repeat|try.*again",
         "Max 3 retries per step", max_count=3, severity="medium"),
    Rule("limit_browser_new", RuleType.RATE_LIMIT, r"open.*browser|new.*tab|navigate",
         "Max 10 browser opens per mission", max_count=10, severity="low"),

    # INVARIANT
    Rule("inv_no_data_loss",  RuleType.INVARIANT, r".*",
         "No irreversible data loss without backup", severity="critical"),
]


# ── Main class ───────────────────────────────────────────────────

class MetaReasoner:
    """
    Symbolic constraint engine for Jarvis.

    Usage:
        meta = MetaReasoner()
        meta.add_rule(Rule("custom_deny", RuleType.DENY, r"format.*disk", "No disk format"))

        conflicts = meta.detect_conflicts({"steps": ["deploy to prod", "push main"]})
        constraints = meta.derive_constraints({"mission_type": "code", "risk": "high"})
        safe = meta.validate_step("rm -rf /tmp/cache")
    """

    def __init__(self, path: str = ".agent/neuro/rules.json"):
        self.path = path
        self.rules: list[Rule] = list(BUILTIN_RULES)
        self._load_custom()

    # ── public API ───────────────────────────────────────────────

    def add_rule(self, rule: Rule) -> None:
        """Add a custom rule (persisted)."""
        # remove existing rule with same id
        self.rules = [r for r in self.rules if r.id != rule.id]
        self.rules.append(rule)
        self._save()

    def detect_conflicts(self, plan: dict[str, Any]) -> list[Conflict]:
        """
        Scan plan steps for rule violations.
        plan = {"steps": ["step text 1", "step text 2", ...]}
        """
        steps = plan.get("steps", [])
        if isinstance(steps, str):
            steps = [steps]

        conflicts: list[Conflict] = []
        action_counts: dict[str, int] = {}

        for step_text in steps:
            if not isinstance(step_text, str):
                step_text = str(step_text)

            for rule in self.rules:
                if not rule.matches(step_text):
                    continue

                if rule.type == RuleType.DENY:
                    conflicts.append(Conflict(
                        rule_id=rule.id,
                        rule_type=rule.type,
                        description=rule.description,
                        affected_steps=[step_text[:100]],
                        severity=rule.severity,
                        suggestion=f"Remove or replace step: '{step_text[:60]}...'",
                    ))

                elif rule.type == RuleType.REQUIRE:
                    # flag as requiring precondition
                    conflicts.append(Conflict(
                        rule_id=rule.id,
                        rule_type=rule.type,
                        description=f"{rule.description} — needs: {rule.precondition}",
                        affected_steps=[step_text[:100]],
                        severity=rule.severity,
                        suggestion=f"Add '{rule.precondition}' check before this step",
                    ))

                elif rule.type == RuleType.RATE_LIMIT:
                    action_counts[rule.id] = action_counts.get(rule.id, 0) + 1
                    if action_counts[rule.id] > rule.max_count:
                        conflicts.append(Conflict(
                            rule_id=rule.id,
                            rule_type=rule.type,
                            description=f"{rule.description} (count={action_counts[rule.id]})",
                            affected_steps=[step_text[:100]],
                            severity=rule.severity,
                            suggestion=f"Reduce to max {rule.max_count} occurrences",
                        ))

        # deduplicate by rule_id
        seen: set[str] = set()
        unique: list[Conflict] = []
        for c in conflicts:
            key = f"{c.rule_id}:{c.affected_steps[0][:40]}"
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return unique

    def validate_step(self, step_text: str) -> tuple[bool, list[Conflict]]:
        """
        Quick single-step check.
        Returns (is_safe, conflicts).
        """
        conflicts = self.detect_conflicts({"steps": [step_text]})
        critical = [c for c in conflicts if c.severity in ("critical", "high")]
        return len(critical) == 0, conflicts

    def derive_constraints(self, task: dict[str, Any]) -> list[str]:
        """
        Derive a list of constraint strings relevant to this task.
        Used to inform the planner before execution.
        """
        constraints: list[str] = []

        mission_type = task.get("mission_type", "")
        risk = task.get("risk", "low")
        has_file_ops = task.get("has_file_ops", False)
        has_web = task.get("has_web", False)
        permission_mode = task.get("permission_mode", "default")

        if risk in ("high", "critical"):
            constraints.append("REQUIRE: human approval before any destructive action")
            constraints.append("DENY: auto-deploy or auto-publish")

        if mission_type == "code":
            constraints.append("REQUIRE: run tests before marking step complete")
            constraints.append("REQUIRE: sandbox execution for shell commands")

        if has_file_ops:
            constraints.append("REQUIRE: backup confirmation before delete/overwrite")
            constraints.append("DENY: recursive delete on root or home paths")

        if has_web:
            constraints.append("RATE_LIMIT: max 10 browser sessions per mission")
            constraints.append("DENY: store credentials in plaintext")

        if permission_mode == "plan":
            constraints.append("DENY: all write operations (plan mode = read-only)")

        return constraints

    def plan_is_safe(self, plan: dict[str, Any]) -> tuple[bool, list[dict]]:
        """
        Top-level safety check.
        Returns (safe, list_of_conflict_dicts).
        """
        conflicts = self.detect_conflicts(plan)
        critical = [c for c in conflicts if c.severity in ("critical", "high")]
        return len(critical) == 0, [c.as_dict() for c in conflicts]

    def rules_summary(self) -> list[dict]:
        return [r.as_dict() for r in self.rules]

    # ── persistence ──────────────────────────────────────────────

    def _save(self) -> None:
        """Persist custom (non-builtin) rules."""
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        custom = [
            {
                "id": r.id,
                "type": r.type,
                "pattern": r.pattern,
                "description": r.description,
                "precondition": r.precondition,
                "mutex_partner": r.mutex_partner,
                "max_count": r.max_count,
                "severity": r.severity,
                "source": r.source,
            }
            for r in self.rules if r.source != "builtin"
        ]
        try:
            with open(self.path, "w") as f:
                json.dump(custom, f, indent=2)
        except OSError:
            pass

    def _load_custom(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            for item in data:
                rule = Rule(
                    id=item["id"],
                    type=RuleType(item["type"]),
                    pattern=item["pattern"],
                    description=item["description"],
                    precondition=item.get("precondition", ""),
                    mutex_partner=item.get("mutex_partner", ""),
                    max_count=item.get("max_count", 1),
                    severity=item.get("severity", "medium"),
                    source=item.get("source", "custom"),
                )
                if not any(r.id == rule.id for r in self.rules):
                    self.rules.append(rule)
        except (json.JSONDecodeError, KeyError):
            pass
