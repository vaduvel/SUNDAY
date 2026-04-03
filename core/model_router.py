"""
J.A.R.V.I.S. Model Routing on Roles
====================================

Sistem de model routing pe roluri:
- PLANNER: Pentru planificare și strategie (model mare, precis)
- CODER: Pentru generare cod (model rapid)
- VERIFIER: Pentru verificare și QA (model ieftin)
- RESEARCHER: Pentru research și analiză (model mediu)
- VOICE: Pentru procesare voice (model optimizat)
"""

import os
import sys

sys.path.insert(0, ".")

from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import logging

from core.runtime_config import configure_inception_openai_alias, load_project_env

logger = logging.getLogger(__name__)

# Set Mercury-2/OpenAI-compatible env via shared runtime config
load_project_env()
configure_inception_openai_alias()
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOG", "CRITICAL")

# Import LiteLLM
import litellm

# Suppress verbose logging
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
logging.getLogger("litellm").setLevel(logging.CRITICAL)


class ModelRole(Enum):
    """Roluri pentru modele"""

    PLANNER = "planner"
    CODER = "coder"
    VERIFIER = "verifier"
    RESEARCHER = "researcher"
    VOICE = "voice"
    GENERAL = "general"


@dataclass
class ModelConfig:
    """Configurație pentru un model"""

    name: str
    role: ModelRole
    description: str
    temperature: float = 0.3
    max_tokens: int = 2000
    fallback_to: Optional[str] = None
    cost_tier: str = "medium"  # low, medium, high


# ==================== MODEL ROUTING CONFIG ====================

MODEL_CONFIGS: Dict[ModelRole, ModelConfig] = {
    ModelRole.PLANNER: ModelConfig(
        name="openai/mercury-2",
        role=ModelRole.PLANNER,
        description="Planning and strategy - needs reasoning",
        temperature=0.2,
        max_tokens=3000,
        fallback_to="gemini/gemini-2.0-flash",
        cost_tier="high",
    ),
    ModelRole.CODER: ModelConfig(
        name="openai/mercury-2",
        role=ModelRole.CODER,
        description="Code generation - needs accuracy",
        temperature=0.1,
        max_tokens=2500,
        fallback_to="gemini/gemini-2.0-flash",
        cost_tier="medium",
    ),
    ModelRole.VERIFIER: ModelConfig(
        name="gemini/gemini-2.0-flash",
        role=ModelRole.VERIFIER,
        description="Verification - can be fast and cheap",
        temperature=0.1,
        max_tokens=1000,
        fallback_to="openai/gpt-4o-mini",
        cost_tier="low",
    ),
    ModelRole.RESEARCHER: ModelConfig(
        name="openai/mercury-2",
        role=ModelRole.RESEARCHER,
        description="Research - needs breadth",
        temperature=0.4,
        max_tokens=4000,
        fallback_to="gemini/gemini-2.0-flash",
        cost_tier="medium",
    ),
    ModelRole.VOICE: ModelConfig(
        name="gemini/gemini-2.0-flash",
        role=ModelRole.VOICE,
        description="Voice processing - needs speed",
        temperature=0.3,
        max_tokens=500,
        fallback_to="openai/gpt-4o-mini",
        cost_tier="low",
    ),
    ModelRole.GENERAL: ModelConfig(
        name="openai/mercury-2",
        role=ModelRole.GENERAL,
        description="General tasks",
        temperature=0.3,
        max_tokens=2000,
        fallback_to="gemini/gemini-2.0-flash",
        cost_tier="medium",
    ),
}


class ModelRouter:
    """
    Router care selectează modelul potrivit pentru rol.

    Flow:
    1. Determine rolul task-ului (planner, coder, etc)
    2. Selectează modelul configurat pentru acel rol
    3. Execută cu parametrii specifici
    4. Fallback la model secundar dacă eșuează
    """

    def __init__(self, api_key: str = None):
        self.api_key = (
            api_key
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("INCEPTION_API_KEY")
            or ""
        )
        self.usage_stats: Dict[str, int] = {}

    def determine_role(self, task_description: str) -> ModelRole:
        """
        Determină rolul based pe descrierea task-ului.
        """
        desc_lower = task_description.lower()

        # Code-related keywords
        if any(
            kw in desc_lower
            for kw in [
                "code",
                "script",
                "function",
                "program",
                "write",
                "debug",
                "implement",
                "python",
                "java",
                "javascript",
            ]
        ):
            return ModelRole.CODER

        # Research-related keywords
        if any(
            kw in desc_lower
            for kw in [
                "research",
                "caută",
                "find",
                "search",
                "analize",
                "information",
                "topic",
                "despre",
            ]
        ):
            return ModelRole.RESEARCHER

        # Verification/QA keywords
        if any(
            kw in desc_lower
            for kw in [
                "verify",
                "check",
                "validate",
                "test",
                "evaluează",
                "confirm",
                "asigură",
            ]
        ):
            return ModelRole.VERIFIER

        # Planning keywords
        if any(
            kw in desc_lower
            for kw in [
                "plan",
                "strategie",
                "design",
                "architect",
                "structur",
                "organiz",
            ]
        ):
            return ModelRole.PLANNER

        # Voice keywords
        if any(
            kw in desc_lower for kw in ["voice", "speak", "vorbește", "audio", "spune"]
        ):
            return ModelRole.VOICE

        # Default to general
        return ModelRole.GENERAL

    def get_model_for_role(self, role: ModelRole) -> ModelConfig:
        """Get model config for role"""
        return MODEL_CONFIGS.get(role, MODEL_CONFIGS[ModelRole.GENERAL])

    async def complete(
        self,
        task_description: str,
        messages: list = None,
        role: ModelRole = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Complete task cu modelul potrivit pentru rol.

        Args:
            task_description: Descriere task pentru determinare rol
            messages: Mesaje pentru LLM
            role: Override rol (opțional)
            **kwargs: Alți parametri

        Returns:
            Dict cu response, model used, tokens, etc.
        """
        # Determine role if not provided
        if role is None:
            role = self.determine_role(task_description)

        # Get model config
        config = self.get_model_for_role(role)

        # Use messages or create from task
        if messages is None:
            messages = [{"role": "user", "content": task_description}]

        # Override params with kwargs
        temperature = kwargs.get("temperature", config.temperature)
        max_tokens = kwargs.get("max_tokens", config.max_tokens)

        logger.info(f"🤖 [ROUTER] Using {config.name} for {role.value}")

        try:
            # Try primary model
            response = litellm.completion(
                model=config.name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=self.api_key,
            )

            result = {
                "success": True,
                "response": response.choices[0].message.content,
                "model_used": config.name,
                "role": role.value,
                "tokens_used": response.usage.total_tokens
                if hasattr(response, "usage")
                else 0,
                "fallback_used": False,
            }

            # Track usage
            self.usage_stats[config.name] = self.usage_stats.get(config.name, 0) + 1

            return result

        except Exception as e:
            logger.warning(f"⚠️ [ROUTER] Primary model failed: {str(e)[:50]}")

            # Try fallback
            if config.fallback_to:
                try:
                    logger.info(f"🔄 [ROUTER] Trying fallback: {config.fallback_to}")

                    response = litellm.completion(
                        model=config.fallback_to,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )

                    return {
                        "success": True,
                        "response": response.choices[0].message.content,
                        "model_used": config.fallback_to,
                        "role": role.value,
                        "tokens_used": response.usage.total_tokens
                        if hasattr(response, "usage")
                        else 0,
                        "fallback_used": True,
                    }
                except Exception as e2:
                    return {
                        "success": False,
                        "error": f"Primary and fallback failed: {str(e2)[:100]}",
                        "model_tried": config.name,
                        "fallback_tried": config.fallback_to,
                    }

            return {"success": False, "error": str(e)[:200], "model_tried": config.name}

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics by model"""
        total_calls = sum(self.usage_stats.values())

        return {
            "by_model": self.usage_stats,
            "total_calls": total_calls,
            "by_role": {
                role.value: sum(
                    1 for config in MODEL_CONFIGS.values() if config.role == role
                )
                for role in ModelRole
            },
        }

    def get_cost_estimate(self) -> Dict[str, float]:
        """Estimate cost by role (simplified)"""
        cost_per_1k = {"low": 0.001, "medium": 0.01, "high": 0.1}

        estimates = {}
        for role, config in MODEL_CONFIGS.items():
            calls = self.usage_stats.get(config.name, 0)
            # Assume ~500 tokens per call
            estimates[role.value] = (
                calls * 0.5 * cost_per_1k.get(config.cost_tier, 0.01)
            )

        return estimates


# ==================== GLOBAL INSTANCE ====================

_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    """Get or create global model router"""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


# ==================== TEST ====================

if __name__ == "__main__":
    import asyncio

    async def test_router():
        router = get_model_router()

        print("=== MODEL ROUTER TEST ===\n")

        # Test different roles
        test_tasks = [
            ("Scrie un script Python pentru factorial", ModelRole.CODER),
            ("Caută informații despre AI agents", ModelRole.RESEARCHER),
            ("Verifică dacă codul e corect", ModelRole.VERIFIER),
            ("Planifică structura proiectului", ModelRole.PLANNER),
            ("Ce este JARVIS?", ModelRole.GENERAL),
        ]

        for task, expected_role in test_tasks:
            # Check role detection
            detected_role = router.determine_role(task)
            config = router.get_model_for_role(detected_role)

            print(f"Task: {task[:40]}...")
            print(
                f"  Detected: {detected_role.value} | Expected: {expected_role.value}"
            )
            print(f"  Model: {config.name} | Cost: {config.cost_tier}")

            # Test actual completion (only for quick ones)
            if detected_role == ModelRole.GENERAL:
                result = await router.complete(task, role=detected_role)
                print(
                    f"  Result: {'✅' if result['success'] else '❌'} ({result.get('model_used', 'none')})"
                )

            print()

        # Show stats
        print("=== USAGE STATS ===")
        print(router.get_usage_stats())

    asyncio.run(test_router())
