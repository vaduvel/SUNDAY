"""Unified capability self-model for JARVIS runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class CapabilityDescriptor:
    key: str
    title: str
    user_value: str
    proof: str
    blast_radius: str
    channel: str
    guardrails: str
    markers: tuple[str, ...] = ()
    always_available: bool = False


_CAPABILITIES: tuple[CapabilityDescriptor, ...] = (
    CapabilityDescriptor(
        key="workspace_code",
        title="Workspace code access",
        user_value="Poți citi, audita și modifica codul din workspace-ul Agent Fram.",
        proof="chat tools read_file/write_file/run_command + orchestrator autonomous_code_apply",
        blast_radius="local workspace only",
        channel="direct tools",
        guardrails="read-before-write, reversible local changes, no unsafe destructive ops",
        markers=("read_file", "write_file", "run_command", "autonomous_code_apply"),
        always_available=True,
    ),
    CapabilityDescriptor(
        key="self_improvement",
        title="Self-improvement",
        user_value="Poți să-ți auditezi propriul cod, să cauți online idei mai bune și să aplici îmbunătățiri locale verificate.",
        proof="workspace_code_audit + autonomous_code_apply + governed autonomy constitution",
        blast_radius="local workspace, governed",
        channel="mission flow",
        guardrails="no finance, no unsafe external side effects, approval for higher-risk changes",
        markers=("workspace_code_audit", "autonomous_code_apply"),
        always_available=True,
    ),
    CapabilityDescriptor(
        key="online_research",
        title="Online research",
        user_value="Poți verifica informații actuale pe internet și poți folosi browser/web tooling pentru confirmări live.",
        proof="web_search + browser tools",
        blast_radius="read-only external research",
        channel="direct tools",
        guardrails="prefer verification when facts may have changed",
        markers=("web_search", "duck_duck_go_search", "browser_search", "browser_task", "execute_browser_task"),
        always_available=True,
    ),
    CapabilityDescriptor(
        key="mission_orchestration",
        title="Mission orchestration",
        user_value="Poți porni misiuni, ULTRAPLAN, coordonare multi-agent și follow-up repair/report flows.",
        proof="run_mission + coordinator + ultraplan + live mission bridge",
        blast_radius="scoped to mission",
        channel="runtime orchestration",
        guardrails="bounded by mission scope, policy, and verification loop",
        always_available=True,
    ),
    CapabilityDescriptor(
        key="browser_control",
        title="Browser control",
        user_value="Poți controla browserul și extrage informații din pagini web atunci când canalul runtime o permite.",
        proof="browser_agent + stagehand browser + live bridge intent routing",
        blast_radius="browser-only",
        channel="runtime-routed",
        guardrails="confirmation when session policy blocks control",
        markers=("browser_search", "browser_task", "execute_browser_task", "browser_structured_extract"),
        always_available=True,
    ),
    CapabilityDescriptor(
        key="computer_control",
        title="Computer control",
        user_value="Poți observa și controla computerul local prin runtime-ul JARVIS când sesiunea permite asta.",
        proof="computer_use_agent + live bridge computer intent",
        blast_radius="local desktop",
        channel="runtime-routed",
        guardrails="confirmation/policy gates for sensitive actions",
        markers=("computer_task", "computer_observe_screen", "desktop_notify", "desktop_launch_app"),
        always_available=True,
    ),
    CapabilityDescriptor(
        key="memory",
        title="Memory",
        user_value="Poți folosi memorie de sesiune, memorie episodică și lecții învățate ca să păstrezi firul și să eviți repetarea greșelilor.",
        proof="structured memory + episodic memory + lesson saving",
        blast_radius="internal state",
        channel="direct runtime",
        guardrails="memory is advisory; current repo state wins",
        markers=("memory_summary", "search_memory", "save_lesson", "obsidian_search"),
        always_available=True,
    ),
    CapabilityDescriptor(
        key="live_multimodal",
        title="Live voice and vision",
        user_value="În sesiuni live poți asculta prin Gemini Live, răspunde vocal și primi context vizual din ecran/cameră.",
        proof="Gemini Live transport + live session bridge + screen/webcam toggles",
        blast_radius="current live session",
        channel="live runtime",
        guardrails="depends on active live session and granted permissions",
        markers=("live_voice", "screen_share", "webcam"),
        always_available=True,
    ),
)


def _toolset(active_tools: Iterable[str] | None = None) -> set[str]:
    return {str(item).strip() for item in (active_tools or []) if str(item).strip()}


def looks_like_capability_query(text: str) -> bool:
    lowered = (text or "").strip().lower()
    markers = (
        "ce poți",
        "ce poti",
        "capabil",
        "capabilit",
        "ce știi",
        "ce stii",
        "poți să",
        "poti sa",
        "te poți",
        "te poti",
        "poți verifica",
        "poti verifica",
        "poți căuta",
        "poti cauta",
        "poți edita",
        "poti edita",
        "te poți îmbunătăți",
        "te poti imbunatati",
        "audit al propriului tău cod",
        "audit al propriului tau cod",
    )
    return any(marker in lowered for marker in markers)


def build_capability_snapshot(
    *,
    active_tools: Iterable[str] | None = None,
    workspace_root: str = "",
    mode_hint: str = "default",
) -> Dict[str, Any]:
    toolset = _toolset(active_tools)
    live_mode = "live" in (mode_hint or "").lower()

    capabilities: List[Dict[str, Any]] = []
    for descriptor in _CAPABILITIES:
        active = descriptor.always_available or any(marker in toolset for marker in descriptor.markers)
        if descriptor.key == "live_multimodal":
            active = active or live_mode
        capabilities.append(
            {
                "key": descriptor.key,
                "title": descriptor.title,
                "active": active,
                "user_value": descriptor.user_value,
                "proof": descriptor.proof,
                "blast_radius": descriptor.blast_radius,
                "channel": descriptor.channel,
                "guardrails": descriptor.guardrails,
            }
        )

    return {
        "workspace_root": workspace_root,
        "mode_hint": mode_hint,
        "active_tools": sorted(toolset),
        "capabilities": capabilities,
    }


def render_capability_self_model(
    *,
    active_tools: Iterable[str] | None = None,
    workspace_root: str = "",
    mode_hint: str = "default",
) -> str:
    snapshot = build_capability_snapshot(
        active_tools=active_tools,
        workspace_root=workspace_root,
        mode_hint=mode_hint,
    )
    lines = [
        "#### 0C. CAPABILITY SELF-MODEL",
        "- You are not a generic chat model. You are the JARVIS runtime operating inside the Agent Fram workspace.",
        f"- Workspace root: {snapshot['workspace_root'] or 'active workspace'}",
        f"- Mode hint: {snapshot['mode_hint']}",
        "- When the user asks what you can do, answer concretely using the capability list below and offer to act immediately.",
        "- Do not underclaim when a capability is available. Do not overclaim when a capability is gated by channel or approval.",
    ]
    for capability in snapshot["capabilities"]:
        status = "ACTIVE" if capability["active"] else "GATED"
        lines.append(
            f"- [{status}] {capability['title']}: {capability['user_value']} "
            f"(Channel: {capability['channel']}; Guardrails: {capability['guardrails']})"
        )
    return "\n".join(lines) + "\n"


def render_user_capability_summary(
    *,
    active_tools: Iterable[str] | None = None,
    workspace_root: str = "",
    mode_hint: str = "default",
) -> str:
    snapshot = build_capability_snapshot(
        active_tools=active_tools,
        workspace_root=workspace_root,
        mode_hint=mode_hint,
    )
    lines = ["Capabilități JARVIS disponibile acum:"]
    for capability in snapshot["capabilities"]:
        if capability["active"]:
            lines.append(f"- {capability['user_value']}")
    lines.append(
        "- Restricție tare: nu pot cumpăra, plăti, face checkout sau cheltui bani fără aprobare explicită."
    )
    return "\n".join(lines)
