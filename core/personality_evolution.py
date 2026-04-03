"""🧠 Personality Evolution System

Based on Agent Friday's cognitive architecture.
The personality evolves based on interaction patterns and user feedback.
"""

import os
import json
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

PERSONALITY_FILE = ".jarvis/personality.json"


@dataclass
class PersonalityTraits:
    """Core personality dimensions that can evolve."""

    # Base traits (0-100 scale)
    formality: float = 50.0  # Formal vs casual
    humor: float = 50.0  # Serious vs humorous
    empathy: float = 50.0  # Logical vs emotional
    verbosity: float = 50.0  # Concise vs detailed
    authority: float = 50.0  # Humble vs confident
    curiosity: float = 50.0  # Focused vs curious

    # Dynamic traits (change based on interactions)
    trust_level: float = 50.0  # How much it trusts the user
    rapport: float = 30.0  # Relationship strength
    last_updated: str = ""


class PersonalityEvolution:
    """Personality that evolves through interaction."""

    def __init__(self):
        self.traits = self._load_traits()
        self.interaction_history: List[Dict] = []
        self.feedback_history: List[Dict] = []
        self._load_history()

    def _load_traits(self) -> PersonalityTraits:
        """Load personality traits or create defaults."""
        if os.path.exists(PERSONALITY_FILE):
            with open(PERSONALITY_FILE, "r") as f:
                data = json.load(f)
                return PersonalityTraits(**data.get("traits", {}))
        return PersonalityTraits()

    def _save_traits(self):
        """Save personality traits."""
        os.makedirs(os.path.dirname(PERSONALITY_FILE), exist_ok=True)
        with open(PERSONALITY_FILE, "w") as f:
            json.dump(
                {
                    "traits": asdict(self.traits),
                    "last_save": datetime.now().isoformat(),
                },
                f,
                indent=2,
            )

    def _load_history(self):
        """Load interaction history."""
        hist_file = PERSONALITY_FILE.replace(".json", "_history.json")
        if os.path.exists(hist_file):
            with open(hist_file, "r") as f:
                data = json.load(f)
                self.interaction_history = data.get("interactions", [])
                self.feedback_history = data.get("feedback", [])

    def _save_history(self):
        """Save interaction history."""
        hist_file = PERSONALITY_FILE.replace(".json", "_history.json")
        with open(hist_file, "w") as f:
            json.dump(
                {
                    "interactions": self.interaction_history[-200:],  # Keep last 200
                    "feedback": self.feedback_history[-100:],
                },
                f,
                indent=2,
            )

    def record_interaction(
        self, user_message: str, agent_response: str, context: Dict = None
    ):
        """Record an interaction for learning."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user_message": user_message[:100],  # Truncate
            "agent_response": agent_response[:100],
            "message_length_ratio": len(agent_response) / max(len(user_message), 1),
            "context": context or {},
        }
        self.interaction_history.append(entry)

        # Evolve based on interaction
        self._evolve_from_interaction(entry)

        # Keep history manageable
        self.interaction_history = self.interaction_history[-200:]
        self._save_history()
        self._save_traits()

    def _evolve_from_interaction(self, entry: Dict):
        """Adjust personality based on interaction patterns."""
        msg_len = entry.get("message_length_ratio", 1)

        # If user writes short messages, become more concise
        if msg_len > 3:
            self.traits.verbosity = max(0, self.traits.verbosity - 1)

        # If user writes long messages, become more detailed
        if msg_len < 1.5:
            self.traits.verbosity = min(100, self.traits.verbosity + 1)

        # Update timestamp
        self.traits.last_updated = datetime.now().isoformat()

    def record_feedback(self, rating: int, feedback_type: str = "general"):
        """Record user feedback to evolve personality."""
        # Rating: 1-5

        entry = {
            "timestamp": datetime.now().isoformat(),
            "rating": rating,
            "type": feedback_type,
        }
        self.feedback_history.append(entry)

        # Evolve based on feedback
        if rating >= 4:
            # Positive feedback - increase rapport
            self.traits.rapport = min(100, self.traits.rapport + 2)
            self.traits.trust_level = min(100, self.traits.trust_level + 1)
        elif rating <= 2:
            # Negative feedback
            self.traits.rapport = max(0, self.traits.rapport - 3)

        self.traits.last_updated = datetime.now().isoformat()
        self.feedback_history = self.feedback_history[-100:]
        self._save_history()
        self._save_traits()

    def get_adjusted_response_style(self) -> Dict[str, any]:
        """Get response style adjustments based on personality."""
        return {
            "formality": self.traits.formality / 100,
            "use_humor": self.traits.humor > 60,
            "show_empathy": self.traits.empathy > 50,
            "detail_level": "brief" if self.traits.verbosity < 40 else "detailed",
            "confidence": "humble" if self.traits.authority < 40 else "confident",
        }

    def should_explain_context(self) -> bool:
        """Should provide extra context/explanations?"""
        return self.traits.curiosity > 60

    def adjust_for_context(self, context_type: str) -> Dict:
        """Adjust personality for specific context."""
        adjustments = {
            "technical": {"formality": 70, "verbosity": 60, "empathy": 40},
            "creative": {"formality": 30, "humor": 70, "verbosity": 50},
            "casual": {"formality": 20, "humor": 60, "verbosity": 30},
            "formal": {"formality": 80, "humor": 20, "verbosity": 40},
        }

        base = adjustments.get(context_type, {})

        # Mix with current personality (blend)
        result = {}
        for key, value in base.items():
            current = getattr(self.traits, key, 50)
            result[key] = (current + value) / 2

        return result

    def get_status(self) -> Dict:
        """Get personality status."""
        return {
            "active": True,
            "traits": asdict(self.traits),
            "interactions_count": len(self.interaction_history),
            "feedback_count": len(self.feedback_history),
            "rapport": self.traits.rapport,
            "trust_level": self.traits.trust_level,
        }


# Singleton
_personality = None


def get_personality() -> PersonalityEvolution:
    global _personality
    if _personality is None:
        _personality = PersonalityEvolution()
    return _personality


# Test
if __name__ == "__main__":
    p = get_personality()

    print("🧠 Personality Status:")
    status = p.get_status()
    print(f"  Formality: {status['traits']['formality']}")
    print(f"  Humor: {status['traits']['humor']}")
    print(f"  Rapport: {status['rapport']}")
    print(f"  Trust: {status['trust_level']}")

    print("\n🧪 Testing evolution:")

    # Record some interactions
    p.record_interaction("Hi!", "Hello! How can I help?")
    p.record_interaction("What's the weather?", "The weather is sunny today, 22°C.")
    p.record_interaction("Thanks!", "You're welcome!")

    # Record feedback
    p.record_feedback(5, "good_response")
    p.record_feedback(5, "helpful")

    print("\nAfter feedback:")
    status = p.get_status()
    print(f"  Rapport: {status['rapport']}")
    print(f"  Trust: {status['trust_level']}")
