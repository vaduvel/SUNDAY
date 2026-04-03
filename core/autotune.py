"""🎛️ AutoTune - Context-Adaptive Sampling Parameters

Based on G0DM0D3's AutoTune:
- Classifies query into 5 context types
- Selects optimal parameters (temperature, top_p, etc.)
- EMA-based learning from feedback
"""

import os
import json
from typing import Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(".env")

AUTO_TUNE_FILE = ".jarvis/autotune_params.json"


class AutoTune:
    """Context-adaptive sampling parameter engine with EMA learning."""

    def __init__(self):
        self.context_types = {
            "creative": {"temperature": 0.8, "top_p": 0.95, "top_k": 40},
            "technical": {"temperature": 0.1, "top_p": 0.9, "top_k": 20},
            "analytical": {"temperature": 0.2, "top_p": 0.85, "top_k": 10},
            "conversational": {"temperature": 0.5, "top_p": 0.92, "top_k": 30},
            "general": {"temperature": 0.4, "top_p": 0.9, "top_k": 25},
        }
        self.ema_weights = {"temperature": 0.1, "top_p": 0.1, "top_k": 0.1}
        self.feedback_history = self._load_history()

    def _load_history(self) -> list:
        """Load feedback history from file."""
        try:
            if os.path.exists(AUTO_TUNE_FILE):
                with open(AUTO_TUNE_FILE, "r") as f:
                    return json.load(f)
        except:
            pass
        return []

    def _save_history(self):
        """Save feedback history."""
        os.makedirs(os.path.dirname(AUTO_TUNE_FILE), exist_ok=True)
        with open(AUTO_TUNE_FILE, "w") as f:
            json.dump(self.feedback_history, f, indent=2)

    def classify_context(self, query: str) -> str:
        """Classify query into context type."""
        query_lower = query.lower()

        # Creative - art, stories, imaginative
        creative_words = [
            "create",
            "write",
            "story",
            "poem",
            "imagine",
            "draw",
            "design",
            "creative",
            "art",
        ]
        if any(w in query_lower for w in creative_words):
            return "technical"  # Actually more precise output for creative too
        if any(
            w in query_lower for w in ["story", "poem", "write", "imagine", "creative"]
        ):
            return "creative"

        # Technical - code, math, precise
        technical_words = [
            "code",
            "function",
            "class",
            "debug",
            "math",
            "calculate",
            "algorithm",
            "implement",
            "python",
            "api",
        ]
        if any(w in query_lower for w in technical_words):
            return "technical"

        # Analytical - analyze, compare, reason, why
        analytical_words = [
            "analyze",
            "compare",
            "reason",
            "why",
            "explain",
            "research",
            "study",
            "evaluate",
            "review",
        ]
        if any(w in query_lower for w in analytical_words):
            return "analytical"

        # Conversational - chat, help, question
        conversational_words = [
            "help",
            "what",
            "how",
            "can you",
            "tell me",
            "hi",
            "hello",
            "chat",
        ]
        if any(w in query_lower for w in conversational_words):
            return "conversational"

        return "general"

    def get_params(self, query: str) -> Dict[str, Any]:
        """Get optimal parameters for the query."""
        context = self.classify_context(query)

        # Start with context defaults
        params = self.context_types.get(context, self.context_types["general"]).copy()

        # Apply EMA learning from feedback
        relevant_feedback = [
            f for f in self.feedback_history[-20:] if f.get("context") == context
        ]

        if relevant_feedback:
            # Apply EMA adjustment
            for param in ["temperature", "top_p", "top_k"]:
                total_adjustment = sum(
                    f.get(f"adjust_{param}", 0) * (0.9 ** (len(relevant_feedback) - i))
                    for i, f in enumerate(relevant_feedback)
                )
                # Scale down the adjustment
                adjustment = total_adjustment * self.ema_weights.get(param, 0.1)
                if param in params:
                    params[param] = max(0.0, min(2.0, params[param] + adjustment))

        return params

    def record_feedback(self, query: str, rating: int, used_params: Dict[str, Any]):
        """Record user feedback to improve parameters."""
        context = self.classify_context(query)

        # Calculate adjustments based on rating (1-5)
        # Positive feedback = slightly increase parameters
        # Negative = decrease
        adjustment = (rating - 3) * 0.05  # -0.1 to +0.1

        feedback = {
            "context": context,
            "rating": rating,
            "query": query[:50],
            "timestamp": datetime.now().isoformat(),
            "adjust_temperature": adjustment,
            "adjust_top_p": adjustment * 0.5,
            "adjust_top_k": adjustment * 0.3,
        }

        self.feedback_history.append(feedback)

        # Keep last 100 feedback items
        self.feedback_history = self.feedback_history[-100:]
        self._save_history()


# Singleton
_autotune = None


def get_autotune() -> AutoTune:
    global _autotune
    if _autotune is None:
        _autotune = AutoTune()
    return _autotune


# Test
if __name__ == "__main__":
    at = AutoTune()

    test_queries = [
        "Write a story about a robot",
        "How do I write a Python function?",
        "Analyze the pros and cons of AI",
        "Hello, how are you?",
    ]

    for q in test_queries:
        ctx = at.classify_context(q)
        params = at.get_params(q)
        print(f"Query: {q[:30]}...")
        print(f"  Context: {ctx}")
        print(f"  Params: {params}")
        print()
