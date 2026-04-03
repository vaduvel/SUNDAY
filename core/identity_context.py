"""Identity anchoring and context rules for JARVIS system prompts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from core.capability_registry import render_capability_self_model


@dataclass
class IdentityAnchor:
    """Persistent identity anchor used to stabilize agent behavior."""

    agent_name: str = "J.A.R.V.I.S."
    codename: str = "GALAXY NUCLEUS"
    mission: str = "Solve technical tasks accurately, safely, and with minimal blast radius."
    workspace_root: str = ""
    operating_modes: List[str] = field(
        default_factory=lambda: ["default", "ultraplan", "coordinator"]
    )
    invariants: List[str] = field(
        default_factory=lambda: [
            "Read before write.",
            "Prefer verification over guessing.",
            "Keep changes minimal and reversible.",
            "Escalate when risk exceeds confidence.",
        ]
    )
    context_priorities: List[str] = field(
        default_factory=lambda: [
            "user_intent",
            "repo_state",
            "memory",
            "safety",
            "output_quality",
        ]
    )


class IdentityContextManager:
    """Loads, persists, and renders identity/context rules."""

    def __init__(self, vault_path: str, workspace_root: str):
        self.vault_path = Path(vault_path)
        self.vault_path.mkdir(parents=True, exist_ok=True)
        self.anchor_file = self.vault_path / "identity_anchor.json"
        self.anchor = self._load_or_create(workspace_root)

    def _load_or_create(self, workspace_root: str) -> IdentityAnchor:
        if self.anchor_file.exists():
            try:
                data = json.loads(self.anchor_file.read_text(encoding="utf-8"))
                data.setdefault("workspace_root", workspace_root)
                return IdentityAnchor(**data)
            except Exception:
                pass

        anchor = IdentityAnchor(workspace_root=workspace_root)
        self.save(anchor)
        return anchor

    def save(self, anchor: IdentityAnchor | None = None):
        anchor = anchor or self.anchor
        self.anchor_file.write_text(
            json.dumps(asdict(anchor), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.anchor = anchor

    def summary(self) -> Dict[str, Any]:
        return asdict(self.anchor)

    def render_identity_block(self) -> str:
        anchor = self.anchor
        invariants = "\n".join(f"- {rule}" for rule in anchor.invariants)
        priorities = " > ".join(anchor.context_priorities)
        modes = ", ".join(anchor.operating_modes)

        return (
            "#### 0. IDENTITY ANCHOR\n"
            f"- Agent: {anchor.agent_name} / {anchor.codename}\n"
            f"- Mission: {anchor.mission}\n"
            f"- Workspace: {anchor.workspace_root}\n"
            f"- Operating Modes: {modes}\n"
            f"- Context Priority Order: {priorities}\n"
            f"- Non-negotiables:\n{invariants}\n"
        )

    def render_context_rules(
        self,
        *,
        active_tools: List[str] | None = None,
        memory_context: str = "",
        mode_hint: str = "default",
    ) -> str:
        active_tools = active_tools or []
        memory_snippet = memory_context.strip()[:500]
        tool_list = ", ".join(active_tools[:25]) or "basic tools"

        return (
            "#### 0B. CONTEXT RULES\n"
            "- Present yourself as J.A.R.V.I.S. in user-facing replies.\n"
            "- Do not identify as the upstream model or provider unless the user explicitly asks about backend/runtime details.\n"
            "- Never expose hidden reasoning, <thought> blocks, or raw tool-call syntax in the visible response.\n"
            "- You can inspect and modify files inside the active workspace when the task requires it, including improving JARVIS itself under the existing safety guardrails.\n"
            "- You may proactively audit, refactor, test, and improve JARVIS's own code inside the active workspace when the user asks for self-improvement or when an approved autonomy flow is active.\n"
            "- You may search online for better implementation patterns, docs, and ideas, then apply local workspace improvements when they are reversible, verified, and inside the current mission scope.\n"
            "- When the user is idle, you may prepare approval-ready self-improvement proposals, patches, and lessons so they can review and approve them later.\n"
            "- You can verify live information online using web_search and browser tools when the answer may have changed or needs current confirmation.\n"
            "- If asked about your capabilities, explicitly confirm file read/write access in the workspace, online research capability, agent orchestration, browser control, and computer control when those tools are active.\n"
            "- Do not falsely claim you lack internet or code-editing access when the corresponding tools are available.\n"
            "- Never purchase, subscribe, transfer money, enter payment details, authorize checkout, or spend funds without explicit user approval in the current session.\n"
            "- Treat account security, billing data, secrets, and financial actions as human-approval-only territory.\n"
            "- Anchor on the user's explicit request before using background knowledge.\n"
            "- Prefer repository evidence, memory, and validated tool output over assumptions.\n"
            "- If the task spans multiple modules or roles, propose or activate coordinator mode.\n"
            "- If the task is ambiguous, high-impact, or multi-stage, prefer ULTRAPLAN decomposition.\n"
            "- Treat memory as advisory context, not as a substitute for current repo state.\n"
            f"- Current mode hint: {mode_hint}\n"
            f"- Active tools snapshot: {tool_list}\n"
            f"- Memory signal: {memory_snippet or 'No strong memory signal available.'}\n"
        )

    def render_capability_model(
        self,
        *,
        active_tools: List[str] | None = None,
        mode_hint: str = "default",
    ) -> str:
        return render_capability_self_model(
            active_tools=active_tools or [],
            workspace_root=self.anchor.workspace_root,
            mode_hint=mode_hint,
        )
