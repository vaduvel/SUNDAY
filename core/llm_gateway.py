"""🔄 JARVIS LLM Abstraction Layer
Inspired by Junie (JetBrains): LLM-agnostic architecture.

This layer provides:
- Easy swap between LLM providers (OpenAI, Anthropic, Google, etc.)
- Unified interface for all LLM operations
- Automatic fallback between models
- Cost tracking and optimization
- Model capabilities metadata

Usage:
    llm = LLMGateway()
    llm.set_provider("anthropic")
    response = await llm.chat("Hello")

    # Easy switch
    llm.set_provider("google")
    response = await llm.chat("Hello")
"""

import asyncio
import logging
import os
from collections import defaultdict
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers."""

    ANTHROPIC = "anthropic"  # Claude
    OPENAI = "openai"  # GPT-4
    GOOGLE = "google"  # Gemini
    OLLAMA = "ollama"  # Local models
    INCEPTION = "inception"  # Mercury (already in JARVIS)
    DEEPSEEK = "deepseek"  # DeepSeek V3/R1
    MISTRAL = "mistral"  # Mistral AI


@dataclass
class ModelConfig:
    """Configuration for a specific model."""

    name: str
    provider: LLMProvider
    max_tokens: int = 4096
    temperature: float = 0.7
    supports_streaming: bool = True
    supports_vision: bool = False
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    context_window: int = 128000


@dataclass
class LLMResponse:
    """Standardized LLM response."""

    content: str
    model: str
    provider: str
    usage: Dict[str, int]  # input_tokens, output_tokens
    finish_reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """Send a chat request."""
        pass

    @abstractmethod
    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs):
        """Send a streaming chat request."""
        pass

    @abstractmethod
    async def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        pass


class AnthropicClient(BaseLLMClient):
    """Anthropic (Claude) client."""

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self.base_url = "https://api.anthropic.com/v1"

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        try:
            import httpx

            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }

            # Convert messages format
            system = ""
            filtered_messages = []
            for msg in messages:
                if msg.get("role") == "system":
                    system = msg.get("content", "")
                else:
                    filtered_messages.append(msg)

            data = {
                "model": self.model,
                "max_tokens": kwargs.get("max_tokens", 4096),
                "temperature": kwargs.get("temperature", 0.7),
                "system": system,
                "messages": filtered_messages,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    headers=headers,
                    json=data,
                    timeout=60.0,
                )

                if response.status_code != 200:
                    raise Exception(f"Anthropic API error: {response.text}")

                result = response.json()

                return LLMResponse(
                    content=result["content"][0]["text"],
                    model=result["model"],
                    provider="anthropic",
                    usage={
                        "input_tokens": result.get("usage", {}).get("input_tokens", 0),
                        "output_tokens": result.get("usage", {}).get(
                            "output_tokens", 0
                        ),
                    },
                    finish_reason=result.get("stop_reason", "unknown"),
                )
        except ImportError:
            raise ImportError("httpx required for Anthropic client")

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs):
        # Streaming implementation would go here
        raise NotImplementedError("Streaming not yet implemented")

    async def count_tokens(self, text: str) -> int:
        # Approximate: ~4 chars per token
        return len(text) // 4


class OpenAIClient(BaseLLMClient):
    """OpenAI (GPT) client."""

    def __init__(self, api_key: str = None, model: str = "gpt-4o"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            data = {
                "model": self.model,
                "messages": messages,
                "max_tokens": kwargs.get("max_tokens", 4096),
                "temperature": kwargs.get("temperature", 0.7),
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=60.0,
                )

                result = response.json()

                return LLMResponse(
                    content=result["choices"][0]["message"]["content"],
                    model=result["model"],
                    provider="openai",
                    usage=result.get("usage", {}),
                    finish_reason=result["choices"][0].get("finish_reason", "unknown"),
                )
        except ImportError:
            raise ImportError("httpx required for OpenAI client")

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs):
        raise NotImplementedError("Streaming not yet implemented")

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4


class InceptionClient(BaseLLMClient):
    """Inception Labs (Mercury-2) client - already used in JARVIS."""

    def __init__(self, api_key: str = None, model: str = "mercury-2"):
        self.api_key = api_key or os.getenv("INCEPTION_API_KEY")
        self.base_url = os.getenv(
            "INCEPTION_BASE_URL", "https://api.inceptionlabs.ai/v1"
        )
        self.model = model

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            data = {
                "model": self.model,
                "messages": messages,
                "max_tokens": kwargs.get("max_tokens", 4096),
                "temperature": kwargs.get("temperature", 0.7),
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=60.0,
                )

                if response.status_code != 200:
                    raise Exception(
                        f"Inception API error {response.status_code}: {response.text}"
                    )

                result = response.json()

                return LLMResponse(
                    content=result["choices"][0]["message"]["content"],
                    model=result.get("model", self.model),
                    provider="inception",
                    usage=result.get("usage", {}),
                    finish_reason=result["choices"][0].get("finish_reason", "unknown"),
                )
        except ImportError:
            raise ImportError("httpx required for Inception client")

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs):
        raise NotImplementedError

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4


class OllamaClient(BaseLLMClient):
    """Ollama (local models) client."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url
        self.model = model

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        try:
            import httpx

            # Convert messages format
            ollama_messages = []
            for msg in messages:
                if msg["role"] != "system":
                    ollama_messages.append(
                        {"role": msg["role"], "content": msg["content"]}
                    )

            data = {"model": self.model, "messages": ollama_messages, "stream": False}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/chat", json=data, timeout=60.0
                )

                result = response.json()

                return LLMResponse(
                    content=result["message"]["content"],
                    model=self.model,
                    provider="ollama",
                    usage={"prompt_tokens": 0, "completion_tokens": 0},
                    finish_reason=result.get("done_reason", "stop"),
                )
        except ImportError:
            raise ImportError("httpx required for Ollama client")

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs):
        raise NotImplementedError

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4


class DeepSeekClient(BaseLLMClient):
    """DeepSeek (V3/R1) client - free and excellent for coding."""

    def __init__(self, api_key: str = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            # Convert messages format
            deepseek_messages = []
            for msg in messages:
                if msg.get("role") == "system":
                    continue  # DeepSeek handles system via special parameter
                deepseek_messages.append(
                    {"role": msg["role"], "content": msg["content"]}
                )

            # Find system message
            system_msg = None
            for msg in messages:
                if msg.get("role") == "system":
                    system_msg = msg.get("content")
                    break

            data = {
                "model": self.model,
                "messages": deepseek_messages,
                "max_tokens": kwargs.get("max_tokens", 4096),
                "temperature": kwargs.get("temperature", 0.7),
            }

            if system_msg:
                data["system"] = system_msg

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=120.0,  # Longer timeout for DeepSeek
                )

                if response.status_code != 200:
                    raise Exception(
                        f"DeepSeek API error {response.status_code}: {response.text}"
                    )

                result = response.json()

                return LLMResponse(
                    content=result["choices"][0]["message"]["content"],
                    model=result.get("model", self.model),
                    provider="deepseek",
                    usage=result.get("usage", {}),
                    finish_reason=result["choices"][0].get("finish_reason", "stop"),
                )
        except ImportError:
            raise ImportError("httpx required for DeepSeek client")

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs):
        raise NotImplementedError

    async def count_tokens(self, text: str) -> int:
        return len(text) // 4


class LLMGateway:
    """
    Main LLM Gateway - abstraction layer for all LLM providers.

    Usage:
        gateway = LLMGateway()

        # Set provider
        gateway.set_provider("anthropic")

        # Use
        response = await gateway.chat("Hello")

        # Easy switch
        gateway.set_provider("ollama", model="llama3")
    """

    # Predefined model configurations
    MODELS = {
        "claude-sonnet": ModelConfig(
            name="claude-sonnet-4-20250514",
            provider=LLMProvider.ANTHROPIC,
            max_tokens=4096,
            supports_streaming=True,
            supports_vision=True,
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
            context_window=200000,
        ),
        "claude-haiku": ModelConfig(
            name="claude-3-haiku-20240307",
            provider=LLMProvider.ANTHROPIC,
            max_tokens=4096,
            supports_streaming=True,
            cost_per_1k_input=0.00025,
            cost_per_1k_output=0.00125,
            context_window=200000,
        ),
        "gpt-4o": ModelConfig(
            name="gpt-4o",
            provider=LLMProvider.OPENAI,
            max_tokens=4096,
            supports_streaming=True,
            supports_vision=True,
            cost_per_1k_input=0.005,
            cost_per_1k_output=0.015,
            context_window=128000,
        ),
        "gpt-4o-mini": ModelConfig(
            name="gpt-4o-mini",
            provider=LLMProvider.OPENAI,
            max_tokens=4096,
            supports_streaming=True,
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
            context_window=128000,
        ),
        "qwen-openrouter": ModelConfig(
            name="openrouter/qwen/qwen3.6-plus:free",
            provider=LLMProvider.OPENAI,
            max_tokens=4096,
            supports_streaming=True,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            context_window=256000,
        ),
        "gemini-pro": ModelConfig(
            name="gemini-1.5-pro",
            provider=LLMProvider.GOOGLE,
            max_tokens=4096,
            supports_streaming=True,
            supports_vision=True,
            cost_per_1k_input=0.00125,
            cost_per_1k_output=0.005,
            context_window=200000,
        ),
        "mercury-inception": ModelConfig(
            name="mercury-2",
            provider=LLMProvider.INCEPTION,
            max_tokens=4096,
            supports_streaming=True,
            cost_per_1k_input=0.0001,  # Very cheap
            cost_per_1k_output=0.0001,
            context_window=128000,
        ),
        "llama3": ModelConfig(
            name="llama3",
            provider=LLMProvider.OLLAMA,
            max_tokens=4096,
            supports_streaming=True,
            cost_per_1k_input=0.0,  # Free (local)
            cost_per_1k_output=0.0,
            context_window=8192,
        ),
        "deepseek-chat": ModelConfig(
            name="deepseek-chat",
            provider=LLMProvider.DEEPSEEK,
            max_tokens=4096,
            supports_streaming=True,
            cost_per_1k_input=0.0000,  # Free (during beta)
            cost_per_1k_output=0.0000,
            context_window=64000,
        ),
        "deepseek-reasoner": ModelConfig(
            name="deepseek-reasoner",
            provider=LLMProvider.DEEPSEEK,
            max_tokens=4096,
            supports_streaming=True,
            cost_per_1k_input=0.0000,  # Free (during beta)
            cost_per_1k_output=0.0000,
            context_window=64000,
        ),
    }

    ROLE_MODEL_CHAINS = {
        "default": [
            "inception-mercury-inception",
            "anthropic-claude-haiku",
            "openai-gpt-4o-mini",
        ],
        "planner": [
            "anthropic-claude-sonnet",
            "deepseek-deepseek-reasoner",
            "inception-mercury-inception",
            "openai-gpt-4o-mini",
        ],
        "verifier": [
            "anthropic-claude-haiku",
            "openai-gpt-4o-mini",
            "inception-mercury-inception",
        ],
        "browser": [
            "openai-gpt-4o",
            "anthropic-claude-sonnet",
            "inception-mercury-inception",
        ],
        "voice": [
            "inception-mercury-inception",
            "openai-gpt-4o-mini",
            "ollama-llama3",
        ],
        "coder": [
            "deepseek-deepseek-chat",
            "anthropic-claude-sonnet",
            "openai-gpt-4o",
        ],
    }

    PROVIDER_POLICIES = {
        LLMProvider.ANTHROPIC: {"timeout_sec": 60, "retries": 1},
        LLMProvider.OPENAI: {"timeout_sec": 45, "retries": 1},
        LLMProvider.INCEPTION: {"timeout_sec": 45, "retries": 1},
        LLMProvider.OLLAMA: {"timeout_sec": 90, "retries": 0},
        LLMProvider.DEEPSEEK: {"timeout_sec": 90, "retries": 1},
        LLMProvider.GOOGLE: {"timeout_sec": 60, "retries": 1},
        LLMProvider.MISTRAL: {"timeout_sec": 60, "retries": 1},
    }

    def __init__(self):
        self.current_provider: Optional[LLMProvider] = None
        self.current_model: Optional[ModelConfig] = None
        self.client: Optional[BaseLLMClient] = None

        # Fallback chain
        self.fallback_chain: List[str] = []  # model names
        self._fallback_index = 0

        # Cost tracking
        self.total_cost = 0.0
        self.total_tokens = {"input": 0, "output": 0}
        self.role_costs: Dict[str, float] = defaultdict(float)
        self.provider_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failure": 0}
        )

    def set_provider(self, provider: str, model: str = None, **kwargs):
        """Set the current LLM provider and model."""
        provider_lower = provider.lower()

        if provider_lower == "anthropic":
            self.current_provider = LLMProvider.ANTHROPIC
            model_key = model or "claude-sonnet"
            config = self.MODELS.get(model_key, self.MODELS["claude-sonnet"])
            self.client = AnthropicClient(model=config.name, **kwargs)

        elif provider_lower == "openai":
            self.current_provider = LLMProvider.OPENAI
            model_key = model or "gpt-4o"
            config = self.MODELS.get(model_key, self.MODELS["gpt-4o"])
            self.client = OpenAIClient(model=config.name, **kwargs)

        elif provider_lower == "inception":
            self.current_provider = LLMProvider.INCEPTION
            model_key = model or "mercury-inception"
            config = self.MODELS.get(model_key, self.MODELS["mercury-inception"])
            self.client = InceptionClient(model=config.name, **kwargs)

        elif provider_lower == "ollama":
            self.current_provider = LLMProvider.OLLAMA
            model_key = model or "llama3"
            config = self.MODELS.get(model_key, self.MODELS["llama3"])
            self.client = OllamaClient(model=config.name, **kwargs)

        elif provider_lower == "google":
            # Would need Google client implementation
            raise NotImplementedError("Google client not yet implemented")

        elif provider_lower == "deepseek":
            self.current_provider = LLMProvider.DEEPSEEK
            model_key = model or "deepseek-chat"
            config = self.MODELS.get(model_key, self.MODELS["deepseek-chat"])
            self.client = DeepSeekClient(model=config.name, **kwargs)

        else:
            raise ValueError(f"Unknown provider: {provider}")

        self.current_model = config
        logger.info(f"LLM Gateway: Set provider to {provider}, model {config.name}")

    def set_fallback_chain(self, models: List[str]):
        """Set fallback chain of models to try in order."""
        self.fallback_chain = models
        self._fallback_index = 0

        # Set first model as primary
        if models:
            first = models[0].split("-")[
                0
            ]  # e.g., "anthropic" from "anthropic-claude-sonnet"
            model_name = (
                "-".join(models[0].split("-")[1:]) if "-" in models[0] else None
            )
            self.set_provider(first, model_name)

    async def chat(self, message: str, system: str = None, **kwargs) -> LLMResponse:
        """Send a chat message, with automatic fallback and AutoTune parameters."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": message})

        # Get AutoTune parameters for this query
        try:
            from core.autotune import get_autotune

            autotune = get_autotune()
            auto_params = autotune.get_params(message)
            # Merge with kwargs (kwargs takes precedence)
            kwargs = {**auto_params, **kwargs}
        except Exception:
            pass  # Use default if AutoTune fails

        return await self._chat_with_retries(messages, role=kwargs.pop("role", None), **kwargs)

    async def chat_with_history(
        self, messages: List[Dict[str, str]], **kwargs
    ) -> LLMResponse:
        """Send chat with full message history."""
        return await self._chat_with_retries(
            messages,
            role=kwargs.pop("role", None),
            **kwargs,
        )

    async def chat_for_role(
        self, role: str, messages: List[Dict[str, str]], **kwargs
    ) -> Dict[str, Any]:
        """Deterministically route a request based on the role."""
        normalized_role = (role or "default").lower()
        self.set_fallback_chain(
            self.ROLE_MODEL_CHAINS.get(normalized_role, self.ROLE_MODEL_CHAINS["default"])
        )
        response = await self._chat_with_retries(messages, role=normalized_role, **kwargs)
        payload = self.normalize_response(response)
        payload["role"] = normalized_role
        payload["estimated_cost"] = self.estimate_cost(
            payload.get("provider", ""),
            payload.get("usage", {}),
            model_key=self._infer_model_key(payload.get("provider"), payload.get("model")),
        )
        return payload

    def get_provider_health(self) -> Dict[str, Any]:
        """Expose simple health and availability for each provider."""
        health: Dict[str, Any] = {}
        for provider in LLMProvider:
            stats = self.provider_stats[provider.value]
            configured = self._provider_is_configured(provider)
            total = stats["success"] + stats["failure"]
            success_rate = stats["success"] / total if total else None
            health[provider.value] = {
                "configured": configured,
                "success": stats["success"],
                "failure": stats["failure"],
                "success_rate": success_rate,
                "timeout_sec": self.PROVIDER_POLICIES.get(provider, {}).get("timeout_sec"),
                "retries": self.PROVIDER_POLICIES.get(provider, {}).get("retries"),
                "current": self.current_provider == provider,
            }
        return health

    def estimate_cost(
        self, provider: str, usage: Dict[str, Any], model_key: str | None = None
    ) -> float:
        """Estimate request cost from normalized usage and provider."""
        model = None
        if model_key and model_key in self.MODELS:
            model = self.MODELS[model_key]
        elif (
            self.current_model is not None
            and self.current_provider is not None
            and self.current_provider.value == provider
        ):
            model = self.current_model
        else:
            for candidate in self.MODELS.values():
                if candidate.provider.value == provider:
                    model = candidate
                    break

        if model is None:
            return 0.0

        normalized_usage = self._normalize_usage(usage)
        input_tokens = normalized_usage["input_tokens"]
        output_tokens = normalized_usage["output_tokens"]
        return (
            input_tokens / 1000 * model.cost_per_1k_input
            + output_tokens / 1000 * model.cost_per_1k_output
        )

    def normalize_response(self, raw: Any) -> Dict[str, Any]:
        """Normalize various response shapes to a common payload."""
        if isinstance(raw, LLMResponse):
            usage = self._normalize_usage(raw.usage)
            return {
                "content": raw.content,
                "model": raw.model,
                "provider": raw.provider,
                "usage": usage,
                "finish_reason": raw.finish_reason,
                "metadata": dict(raw.metadata or {}),
            }

        if isinstance(raw, dict):
            usage = self._normalize_usage(raw.get("usage", {}))
            return {
                "content": raw.get("content") or raw.get("text") or "",
                "model": raw.get("model"),
                "provider": raw.get("provider"),
                "usage": usage,
                "finish_reason": raw.get("finish_reason", "unknown"),
                "metadata": dict(raw.get("metadata", {})),
            }

        return {
            "content": str(raw),
            "model": None,
            "provider": self.current_provider.value if self.current_provider else None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "finish_reason": "unknown",
            "metadata": {},
        }

    async def _chat_with_retries(
        self, messages: List[Dict[str, str]], role: str | None = None, **kwargs
    ) -> LLMResponse:
        if self.client is None or self.current_provider is None:
            raise RuntimeError("LLM provider not configured before chat call.")

        last_error = None
        while True:
            policy = self.PROVIDER_POLICIES.get(
                self.current_provider,
                {"timeout_sec": 60, "retries": 0},
            )
            timeout_sec = kwargs.pop("timeout", policy["timeout_sec"])
            retries = kwargs.pop("retries", policy["retries"])

            for _ in range(retries + 1):
                try:
                    response = await asyncio.wait_for(
                        self.client.chat(messages, **kwargs),
                        timeout=timeout_sec,
                    )
                    self._track_cost(response, role=role)
                    self.provider_stats[self.current_provider.value]["success"] += 1
                    return response
                except Exception as exc:
                    last_error = exc
                    self.provider_stats[self.current_provider.value]["failure"] += 1
                    logger.warning(
                        "LLM call failed on %s/%s: %s",
                        self.current_provider.value,
                        self.current_model.name if self.current_model else "unknown",
                        exc,
                    )

            if not self._advance_fallback():
                break

        raise last_error if last_error else RuntimeError("Unknown LLM gateway failure")

    def _advance_fallback(self) -> bool:
        if not self.fallback_chain or self._fallback_index >= len(self.fallback_chain) - 1:
            return False
        self._fallback_index += 1
        next_model = self.fallback_chain[self._fallback_index]
        logger.info("Trying LLM fallback: %s", next_model)
        provider, model = self._parse_model_identifier(next_model)
        self.set_provider(provider, model)
        return True

    def _track_cost(self, response: LLMResponse, role: str | None = None):
        """Track usage and cost."""
        usage = self._normalize_usage(response.usage)
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]

        self.total_tokens["input"] += input_tokens
        self.total_tokens["output"] += output_tokens

        cost = self.estimate_cost(
            response.provider,
            usage,
            model_key=self._infer_model_key(response.provider, response.model),
        )
        self.total_cost += cost
        if role:
            self.role_costs[role] += cost

    def get_cost_summary(self) -> Dict[str, Any]:
        """Get cost summary."""
        return {
            "total_cost": self.total_cost,
            "total_tokens": self.total_tokens,
            "current_model": self.current_model.name if self.current_model else None,
            "provider": self.current_provider.value if self.current_provider else None,
            "per_role": dict(self.role_costs),
            "provider_health": self.get_provider_health(),
        }

    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available models with their configs."""
        return [
            {
                "key": key,
                "name": config.name,
                "provider": config.provider.value,
                "context_window": config.context_window,
                "cost_per_1k_input": config.cost_per_1k_input,
                "supports_vision": config.supports_vision,
            }
            for key, config in self.MODELS.items()
        ]

    def _normalize_usage(self, usage: Dict[str, Any]) -> Dict[str, int]:
        return {
            "input_tokens": int(
                usage.get("input_tokens")
                or usage.get("prompt_tokens")
                or usage.get("input")
                or 0
            ),
            "output_tokens": int(
                usage.get("output_tokens")
                or usage.get("completion_tokens")
                or usage.get("output")
                or 0
            ),
        }

    def _parse_model_identifier(self, identifier: str) -> tuple[str, str | None]:
        parts = identifier.split("-")
        provider = parts[0]
        model = "-".join(parts[1:]) if len(parts) > 1 else None
        return provider, model

    def _infer_model_key(self, provider: str | None, model_name: str | None) -> str | None:
        for key, config in self.MODELS.items():
            if config.provider.value == provider and config.name == model_name:
                return key
        return None

    def _provider_is_configured(self, provider: LLMProvider) -> bool:
        env_map = {
            LLMProvider.ANTHROPIC: bool(os.getenv("ANTHROPIC_API_KEY")),
            LLMProvider.OPENAI: bool(os.getenv("OPENAI_API_KEY")),
            LLMProvider.GOOGLE: bool(os.getenv("GOOGLE_API_KEY")),
            LLMProvider.OLLAMA: True,
            LLMProvider.INCEPTION: bool(os.getenv("INCEPTION_API_KEY") or os.getenv("OPENAI_API_KEY")),
            LLMProvider.DEEPSEEK: bool(os.getenv("DEEPSEEK_API_KEY")),
            LLMProvider.MISTRAL: bool(os.getenv("MISTRAL_API_KEY")),
        }
        return env_map.get(provider, False)


# Easy instance for JARVIS
def create_llm_gateway() -> LLMGateway:
    """Create a configured LLM gateway instance."""
    gateway = LLMGateway()

    # Set default based on JARVIS existing config
    if os.getenv("OPENROUTER_API_KEY") or "openrouter.ai" in os.getenv("OPENAI_API_BASE", ""):
        gateway.set_provider("openai", "qwen-openrouter")
    elif os.getenv("INCEPTION_API_KEY"):
        gateway.set_provider("inception", "mercury-inception")
    elif os.getenv("ANTHROPIC_API_KEY"):
        gateway.set_provider("anthropic", "claude-sonnet")
    else:
        # Default to OpenAI
        gateway.set_provider("openai", "gpt-4o-mini")

    # Set fallback chain for reliability
    gateway.set_fallback_chain(
        [
            "openai-qwen-openrouter",
            "inception-mercury-inception",
            "anthropic-claude-haiku",
            "openai-gpt-4o-mini",
        ]
    )

    return gateway


# Standalone test
if __name__ == "__main__":
    import asyncio

    async def test():
        # Test model listing
        gateway = LLMGateway()

        print("Available models:")
        for model in gateway.get_available_models():
            print(f"  - {model['key']}: {model['name']} ({model['provider']})")

        # Test cost tracking
        gateway.set_provider("openai", "gpt-4o-mini")

        # Would need real API key to test actual calls
        print(f"\nCost summary: {gateway.get_cost_summary()}")

    asyncio.run(test())
