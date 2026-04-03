"""J.A.R.V.I.S. (GALAXY BRAIN - REAL WIRING V2)

Fully asynchronous brain configuration using LiteLLM for multi-model access.
Supports Gemini, Anthropic, OpenAI, and Custom (Inception Labs).

V2 Features:
- Semantic state tracking
- Context-aware decision making
- Tool execution with verification
"""

import os
import logging
import asyncio

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOG", "CRITICAL")
import litellm
from typing import Dict, Any, List, AsyncGenerator, Optional
from dataclasses import dataclass, field

from core.runtime_config import configure_inception_openai_alias, load_project_env

logger = logging.getLogger(__name__)

# ─── Caching Configuration ──────────────────────────────────────
litellm.cache = litellm.Cache(type="local")
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
logging.getLogger("litellm").setLevel(logging.CRITICAL)

# ─── API Configuration ────────────────────────────────────────
load_project_env()

# OpenRouter Configuration (Qwen 3.6 Plus)
os.environ["OPENAI_API_BASE"] = "https://openrouter.ai/api/v1"
os.environ["OPENAI_API_KEY"] = os.getenv("OPENROUTER_API_KEY", "")

PRO_MODEL = "openrouter/qwen/qwen3.6-plus:free"
CHEAP_MODEL = "openrouter/qwen/qwen3.6-plus:free"
LOCAL_MODEL = "ollama/mixtral"
LLM_TIMEOUT_SEC = float(os.getenv("JARVIS_LLM_TIMEOUT_SEC", "18"))
LLM_STREAM_CONNECT_TIMEOUT_SEC = float(
    os.getenv("JARVIS_LLM_STREAM_CONNECT_TIMEOUT_SEC", "12")
)
LLM_STREAM_TOTAL_TIMEOUT_SEC = float(
    os.getenv("JARVIS_LLM_STREAM_TOTAL_TIMEOUT_SEC", "45")
)

# ─── LLM Profiles ─────────────────────────────────────────────
LLM_PROFILES = {
    "precise": {"temperature": 0.05, "max_tokens": 4096},
    "balanced": {"temperature": 0.1, "max_tokens": 4096},
    "creative": {"temperature": 0.5, "max_tokens": 4096},
    "coder": {"temperature": 0.05, "max_tokens": 8192},
}


@dataclass
class SemanticContext:
    """V2: Semantic state tracking for context-aware decisions."""

    session_id: str = ""
    task_history: List[Dict[str, Any]] = field(default_factory=list)
    learned_patterns: Dict[str, Any] = field(default_factory=dict)
    current_goal: Optional[str] = None
    environmental_state: Dict[str, Any] = field(default_factory=dict)
    last_tool_result: Optional[Dict[str, Any]] = None

    def add_to_history(self, action: str, result: Any):
        self.task_history.append({"action": action, "result": result})
        if len(self.task_history) > 50:
            self.task_history = self.task_history[-50:]

    def learn_pattern(self, pattern_key: str, pattern_data: Any):
        self.learned_patterns[pattern_key] = pattern_data


async def _close_litellm_clients_safely() -> None:
    """Best-effort cleanup for LiteLLM async clients to avoid noisy pending-task warnings."""
    try:
        await asyncio.wait_for(litellm.close_litellm_async_clients(), timeout=1.0)
    except Exception:
        pass


async def stream_brain(
    messages: List[Dict], model: str = PRO_MODEL, profile: str = "balanced"
) -> AsyncGenerator[str, None]:
    """[STREAM]: Stream tokens from LLM for real-time response."""
    config = LLM_PROFILES.get(profile, LLM_PROFILES["balanced"])

    try:
        logger.info(f"🧠 [BRAIN STREAM] Calling {model} with {profile} profile...")

        response = await asyncio.wait_for(
            litellm.acompletion(
                model=model,
                messages=messages,
                temperature=config["temperature"],
                max_tokens=config["max_tokens"],
                stream=True,
                timeout=LLM_STREAM_CONNECT_TIMEOUT_SEC,
                fallbacks=(
                    [CHEAP_MODEL, LOCAL_MODEL]
                    if model != CHEAP_MODEL
                    else [LOCAL_MODEL, "openai/gpt-4o-mini"]
                ),
                drop_invalid_params=True,
                caching=True,
            ),
            timeout=LLM_STREAM_CONNECT_TIMEOUT_SEC + 2,
        )

        async with asyncio.timeout(LLM_STREAM_TOTAL_TIMEOUT_SEC):
            async for chunk in response:
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        yield delta.content
                elif hasattr(chunk, "delta") and chunk.delta:
                    yield chunk.delta

    except TimeoutError:
        logger.error("❌ [BRAIN STREAM] Timed out waiting for model response.")
        yield "ERROR: Brain stream timed out."
    except Exception as e:
        logger.error(f"❌ [BRAIN STREAM] API Error: {str(e)}")
        yield f"ERROR: Brain stream failed. {str(e)}"
    finally:
        await _close_litellm_clients_safely()


async def call_brain(
    messages: List[Dict], model: str = PRO_MODEL, profile: str = "balanced"
):
    """
    [EXECUTE]: The high-fidelity asynchronous call to the LLM.
    Uses LiteLLM for transparent routing and retry logic.
    """
    config = LLM_PROFILES.get(profile, LLM_PROFILES["balanced"])

    try:
        logger.info(f"🧠 [BRAIN] Calling {model} with {profile} profile...")
        response = await asyncio.wait_for(
            litellm.acompletion(
                model=model,
                messages=messages,
                temperature=config["temperature"],
                max_tokens=config["max_tokens"],
                timeout=LLM_TIMEOUT_SEC,
                fallbacks=(
                    [CHEAP_MODEL, LOCAL_MODEL]
                    if model != CHEAP_MODEL
                    else [LOCAL_MODEL, "openai/gpt-4o-mini"]
                ),
                drop_invalid_params=True,
                caching=True,
            ),
            timeout=LLM_TIMEOUT_SEC + 2,
        )
        # type: ignore[attr-defined]
        return response.choices[0].message.content
    except TimeoutError:
        logger.error("❌ [BRAIN] Timed out waiting for model response.")
        return "ERROR: Brain call timed out."
    except Exception as e:
        logger.error(f"❌ [BRAIN] API Error: {str(e)}")
        return f"ERROR: Brain call failed. {str(e)}"
    finally:
        await _close_litellm_clients_safely()


async def call_brain_with_tools(
    messages: List[Dict],
    tools: List[Dict] = None,
    model: str = PRO_MODEL,
    profile: str = "balanced",
) -> Any:
    """Call LLM with function/tool calling support.

    Returns the raw message object so the caller can inspect
    .content (str | None) and .tool_calls (list | None).
    """
    config = LLM_PROFILES.get(profile, LLM_PROFILES["balanced"])

    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=messages,
        temperature=config["temperature"],
        max_tokens=config["max_tokens"],
        drop_invalid_params=True,
    )
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    # Tools require cloud models; LOCAL_MODEL doesn't support function calling
    kwargs["fallbacks"] = (
        [CHEAP_MODEL, LOCAL_MODEL] if model != CHEAP_MODEL else ["openai/gpt-4o-mini"]
    )

    try:
        logger.info(
            f"🧠 [BRAIN TOOLS] model={model} tools={len(tools or [])} profile={profile}"
        )
        kwargs["timeout"] = LLM_TIMEOUT_SEC
        response = await asyncio.wait_for(
            litellm.acompletion(**kwargs),
            timeout=LLM_TIMEOUT_SEC + 2,
        )
        return response.choices[0].message
    except TimeoutError as e:
        logger.error("❌ [BRAIN TOOLS] Timed out waiting for model response.")

        class _ErrMsg:
            content = f"ERROR: Brain call timed out — {str(e)}"
            tool_calls = None

        return _ErrMsg()
    except Exception as e:
        logger.error(f"❌ [BRAIN TOOLS] API Error: {str(e)}")

        class _ErrMsg:
            content = f"ERROR: Brain call failed — {str(e)}"
            tool_calls = None

        return _ErrMsg()
    finally:
        await _close_litellm_clients_safely()


def get_profile_for_role(role: str) -> str:
    """Maps agent roles to optimal LLM profiles automatically."""
    role_lower = role.lower()
    role_profile_map = {
        "architect": "balanced",
        "developer": "coder",
        "security": "precise",
        "growth": "creative",
    }
    return role_profile_map.get(role_lower, "balanced")


def get_llm_for_role(role: str):
    """Returns a LiteLLM-configured LLM for a specific role."""
    try:
        from crewai import LLM
    except ImportError as exc:
        raise RuntimeError(
            "CrewAI is required for role-based Crew orchestration."
        ) from exc

    profile = get_profile_for_role(role)
    config = LLM_PROFILES.get(profile, LLM_PROFILES["balanced"])

    return LLM(
        model=PRO_MODEL,
        temperature=config["temperature"],
        max_tokens=config["max_tokens"],
    )
