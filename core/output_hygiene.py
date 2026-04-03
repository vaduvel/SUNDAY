"""Output hygiene helpers for J.A.R.V.I.S. user-visible responses."""

from __future__ import annotations

import re

THOUGHT_BLOCK_RE = re.compile(r"(?is)<thought>.*?</thought>|<thinking>.*?</thinking>")
THOUGHT_LINE_RE = re.compile(r"(?im)^\s*\[(?:OBSERVE|DECOMPOSE|SPECULATE|PLAN|REFLECT)\].*$")
TOOL_CALL_LINE_RE = re.compile(
    r"(?im)^\s*(?:desktop_voice_say|desktop_notify|desktop_launch_app|desktop_open_finder|"
    r"voice_speak|voice_listen|voice_session_[a-z_]+|computer_[a-z_]+|browser_[a-z_]+|"
    r"stagehand_[a-z_]+)\s*\(.*\)\s*$"
)
PROVIDER_LINE_RE = re.compile(
    r"(?im)^\s*(?:sunt|eu sunt|i am|i'm)\b[^\n]*(?:qwen|tongyi|alibaba|openai|anthropic|"
    r"gemini|claude|mixtral|llama)[^\n]*$"
)
PROVIDER_META_LINE_RE = re.compile(
    r"(?im)^.*(?:Tongyi Lab|Alibaba Group|model de limbaj mare dezvoltat de|large language model developed by).*$"
)
MULTISPACE_RE = re.compile(r"[ \t]{2,}")
MULTIBLANK_RE = re.compile(r"\n{3,}")

BACKEND_QUERY_HINTS = (
    "ce model",
    "care e modelul",
    "what model",
    "backend",
    "provider",
    "llm",
    "ce llm",
    "engine",
)


def wants_backend_identity(user_message: str) -> bool:
    lowered = (user_message or "").lower()
    return any(hint in lowered for hint in BACKEND_QUERY_HINTS)


def sanitize_assistant_output(text: str, user_message: str = "") -> str:
    """Strip hidden reasoning, raw tool syntax, and upstream identity leaks."""
    if not text:
        return ""

    cleaned = THOUGHT_BLOCK_RE.sub("", text)
    cleaned = THOUGHT_LINE_RE.sub("", cleaned)
    cleaned = TOOL_CALL_LINE_RE.sub("", cleaned)

    if not wants_backend_identity(user_message):
        cleaned = PROVIDER_LINE_RE.sub("", cleaned)
        cleaned = PROVIDER_META_LINE_RE.sub("", cleaned)

    cleaned = re.sub(r"desktop_voice_say\(.*?\)", "", cleaned, flags=re.DOTALL)
    cleaned = MULTISPACE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = MULTIBLANK_RE.sub("\n\n", cleaned)
    cleaned = cleaned.strip()

    if not cleaned and text.strip():
        return "Sunt J.A.R.V.I.S. Cu ce te pot ajuta?"
    return cleaned


def chunk_text(text: str, size: int = 80) -> list[str]:
    """Split sanitized output into UI-friendly chunks."""
    if not text:
        return []
    return [text[index : index + size] for index in range(0, len(text), size)]
