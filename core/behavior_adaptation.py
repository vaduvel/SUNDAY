"""
J.A.R.V.I.S. Memory → Behavior Adaptation
=========================================

Sistem de memory care schimbă comportamentul:
- Învață preferințe reale din interacțiuni
- Învață anti-patterns (ce nu merge)
- Învață secvențe de succes pe aplicații
- Promovează automat skills care trec evals
- Feedback loop pentru auto-îmbunătățire
"""

import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class BehaviorPattern:
    """Pattern de comportament învățat"""

    pattern_id: str
    trigger: str  # Ce a declanșat
    action_sequence: List[str]  # Ce a făcut
    success_count: int = 0
    failure_count: int = 0
    last_used: float = field(default_factory=time.time)
    success_rate: float = 0.0

    def update(self, success: bool):
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1

        total = self.success_count + self.failure_count
        self.success_rate = self.success_count / total if total > 0 else 0
        self.last_used = time.time()


@dataclass
class UserPreference:
    """Preferință învățată de la user"""

    preference_id: str
    key: str  # ex: "verbose_level", "code_style"
    value: str
    confidence: float = 0.5
    evidence_count: int = 0

    def reinforce(self, value: str):
        if value == self.value:
            self.confidence = min(1.0, self.confidence + 0.1)
            self.evidence_count += 1
        else:
            self.confidence = max(0.0, self.confidence - 0.05)


@dataclass
class AntiPattern:
    """Pattern care nu funcționează"""

    pattern_id: str
    description: str
    context: str  # Când apare
    failure_count: int = 0
    last_seen: float = field(default_factory=time.time)


class BehaviorAdaptation:
    """
    Sistem de adaptare comportamentală din memorie.

    Funcționalități:
    1. Învață din feedback
    2. Identifică pattern-uri de succes
    3. Evită anti-patterns
    4. Ajustează răspunsuri după preferințe
    5. Propune skill improvements
    """

    def __init__(self, storage_path: str = ".agent/behavior"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # In-memory storage
        self.behavior_patterns: Dict[str, BehaviorPattern] = {}
        self.user_preferences: Dict[str, UserPreference] = {}
        self.anti_patterns: Dict[str, AntiPattern] = {}

        # Learning config
        self.min_successes_for_promotion = 3
        self.min_confidence_for_adaptation = 0.7

        # Load from disk
        self._load_data()

    def _load_data(self):
        """Load saved data"""
        try:
            # Load patterns
            patterns_file = self.storage_path / "patterns.json"
            if patterns_file.exists():
                data = json.loads(patterns_file.read_text())
                for p_data in data.get("patterns", []):
                    p = BehaviorPattern(**p_data)
                    self.behavior_patterns[p.pattern_id] = p

            # Load preferences
            prefs_file = self.storage_path / "preferences.json"
            if prefs_file.exists():
                data = json.loads(prefs_file.read_text())
                for p_data in data.get("preferences", []):
                    p = UserPreference(**p_data)
                    self.user_preferences[p.preference_id] = p

            # Load anti-patterns
            anti_file = self.storage_path / "anti_patterns.json"
            if anti_file.exists():
                data = json.loads(anti_file.read_text())
                for a_data in data.get("anti_patterns", []):
                    a = AntiPattern(**a_data)
                    self.anti_patterns[a.pattern_id] = a

            logger.info(
                f"Loaded {len(self.behavior_patterns)} patterns, {len(self.user_preferences)} prefs"
            )
        except Exception as e:
            logger.warning(f"Could not load behavior data: {e}")

    def _save_data(self):
        """Save data to disk"""
        try:
            # Save patterns
            patterns_data = {
                "patterns": [
                    {
                        "pattern_id": p.pattern_id,
                        "trigger": p.trigger,
                        "action_sequence": p.action_sequence,
                        "success_count": p.success_count,
                        "failure_count": p.failure_count,
                        "last_used": p.last_used,
                        "success_rate": p.success_rate,
                    }
                    for p in self.behavior_patterns.values()
                ]
            }
            (self.storage_path / "patterns.json").write_text(
                json.dumps(patterns_data, indent=2)
            )

            # Save preferences
            prefs_data = {
                "preferences": [
                    {
                        "preference_id": p.preference_id,
                        "key": p.key,
                        "value": p.value,
                        "confidence": p.confidence,
                        "evidence_count": p.evidence_count,
                    }
                    for p in self.user_preferences.values()
                ]
            }
            (self.storage_path / "preferences.json").write_text(
                json.dumps(prefs_data, indent=2)
            )

            # Save anti-patterns
            anti_data = {
                "anti_patterns": [
                    {
                        "pattern_id": a.pattern_id,
                        "description": a.description,
                        "context": a.context,
                        "failure_count": a.failure_count,
                        "last_seen": a.last_seen,
                    }
                    for a in self.anti_patterns.values()
                ]
            }
            (self.storage_path / "anti_patterns.json").write_text(
                json.dumps(anti_data, indent=2)
            )
        except Exception as e:
            logger.warning(f"Could not save behavior data: {e}")

    # ==================== LEARNING ====================

    def learn_from_interaction(
        self,
        trigger: str,
        actions: List[str],
        success: bool,
        user_feedback: Optional[str] = None,
    ):
        """
        Învață dintr-o interacțiune.

        Args:
            trigger: Ce a declanșat acțiunea
            actions: Ce acțiuni s-au executat
            success: Dacă a fost successful
            user_feedback: Opțional feedback de la user
        """
        # Create or update pattern
        pattern_key = f"{trigger}:{'->'.join(actions[:2])}"

        if pattern_key in self.behavior_patterns:
            pattern = self.behavior_patterns[pattern_key]
            pattern.update(success)
        else:
            pattern = BehaviorPattern(
                pattern_id=pattern_key,
                trigger=trigger,
                action_sequence=actions,
                success_count=1 if success else 0,
                failure_count=0 if success else 1,
                success_rate=1.0 if success else 0.0,
            )
            self.behavior_patterns[pattern_key] = pattern

        # Learn from user feedback
        if user_feedback:
            self._learn_from_feedback(trigger, user_feedback)

        # Learn anti-pattern if failed
        if not success:
            self._learn_anti_pattern(trigger, actions)

        # Save
        self._save_data()

    def _learn_from_feedback(self, context: str, feedback: str):
        """Învață din feedback explicit"""
        feedback_lower = feedback.lower()

        # Detect preference type
        if any(
            kw in feedback_lower
            for kw in ["mai", "more", "more detailed", "mai detaliat"]
        ):
            self._update_preference("verbose_level", "detailed", context)
        elif any(kw in feedback_lower for kw in ["scurt", "short", "concise"]):
            self._update_preference("verbose_level", "concise", context)

        if any(kw in feedback_lower for kw in ["code bun", "good code", "clean"]):
            self._update_preference("code_style", "clean", context)
        elif any(kw in feedback_lower for kw in ["code simplu", "simple"]):
            self._update_preference("code_style", "simple", context)

        if any(kw in feedback_lower for kw in ["mulțumesc", "thanks", "good"]):
            self._update_preference("tone", "formal", context)
        elif any(kw in feedback_lower for kw in ["ok", "nice", "cool"]):
            self._update_preference("tone", "casual", context)

    def _update_preference(self, key: str, value: str, context: str):
        """Update or create preference"""
        pref_id = f"{key}:{value}"

        if pref_id in self.user_preferences:
            self.user_preferences[pref_id].reinforce(value)
        else:
            pref = UserPreference(
                preference_id=pref_id,
                key=key,
                value=value,
                confidence=0.5,
                evidence_count=1,
            )
            self.user_preferences[pref_id] = pref

    def _learn_anti_pattern(self, trigger: str, actions: List[str]):
        """Înregistrează pattern care a eșuat"""
        anti_key = f"{trigger}:{actions[0]}"

        if anti_key in self.anti_patterns:
            self.anti_patterns[anti_key].failure_count += 1
            self.anti_patterns[anti_key].last_seen = time.time()
        else:
            anti = AntiPattern(
                pattern_id=anti_key,
                description=f"Failed when doing {actions[0]} after {trigger}",
                context=trigger,
                failure_count=1,
            )
            self.anti_patterns[anti_key] = anti

    # ==================== RETRIEVAL ====================

    def get_best_action_sequence(self, trigger: str) -> Optional[List[str]]:
        """Get best action sequence for a trigger"""
        candidates = [
            p
            for p in self.behavior_patterns.values()
            if p.trigger == trigger and p.success_rate >= 0.5
        ]

        if not candidates:
            return None

        # Sort by success rate and recency
        candidates.sort(key=lambda p: (p.success_rate, p.last_used), reverse=True)

        return candidates[0].action_sequence

    def get_adjusted_response_style(self, base_response: str) -> str:
        """Adjust response based on learned preferences"""
        # Get active preferences
        verbose_pref = next(
            (
                p
                for p in self.user_preferences.values()
                if p.key == "verbose_level" and p.confidence >= 0.5
            ),
            None,
        )

        if verbose_pref:
            if verbose_pref.value == "concise":
                # Shorten response
                sentences = base_response.split(".")
                return ".".join(sentences[:2]) + "."
            elif verbose_pref.value == "detailed":
                # Add more detail
                return (
                    base_response + "\n\n[Informații adiționale disponibile la cerere.]"
                )

        return base_response

    def should_avoid(self, trigger: str, action: str) -> bool:
        """Check if action should be avoided"""
        anti_key = f"{trigger}:{action}"

        if anti_key in self.anti_patterns:
            anti = self.anti_patterns[anti_key]
            # Avoid if failed more than twice
            return anti.failure_count >= 2

        return False

    def get_skill_improvements(self) -> List[Dict[str, Any]]:
        """Get skills that should be improved based on performance"""
        improvements = []

        for pattern in self.behavior_patterns.values():
            if pattern.success_count >= self.min_successes_for_promotion:
                improvements.append(
                    {
                        "pattern_id": pattern.pattern_id,
                        "trigger": pattern.trigger,
                        "success_rate": pattern.success_rate,
                        "suggestion": "Promote to skill library",
                    }
                )

        return improvements

    def get_status(self) -> Dict[str, Any]:
        """Get behavior adaptation status"""
        return {
            "patterns_learned": len(self.behavior_patterns),
            "preferences_learned": len(self.user_preferences),
            "anti_patterns_identified": len(self.anti_patterns),
            "high_confidence_preferences": sum(
                1
                for p in self.user_preferences.values()
                if p.confidence >= self.min_confidence_for_adaptation
            ),
            "successful_patterns": sum(
                1 for p in self.behavior_patterns.values() if p.success_rate >= 0.7
            ),
        }


# ==================== GLOBAL INSTANCE ====================

_behavior_adaptation: Optional[BehaviorAdaptation] = None


def get_behavior_adaptation() -> BehaviorAdaptation:
    """Get or create global behavior adaptation"""
    global _behavior_adaptation
    if _behavior_adaptation is None:
        _behavior_adaptation = BehaviorAdaptation()
    return _behavior_adaptation


# ==================== TEST ====================

if __name__ == "__main__":
    behavior = get_behavior_adaptation()

    print("=== BEHAVIOR ADAPTATION TEST ===\n")

    # Learn from interactions
    behavior.learn_from_interaction(
        trigger="code_factorial", actions=["search", "write_code", "test"], success=True
    )

    behavior.learn_from_interaction(
        trigger="code_factorial", actions=["search", "write_code", "test"], success=True
    )

    behavior.learn_from_interaction(
        trigger="code_factorial", actions=["write_code_direct", "test"], success=False
    )

    behavior.learn_from_interaction(
        trigger="general",
        actions=["search"],
        success=True,
        user_feedback="Mulțumesc, foarte detaliat!",
    )

    # Test retrieval
    best = behavior.get_best_action_sequence("code_factorial")
    print(f"Best action for code_factorial: {best}")

    # Test avoid
    avoid = behavior.should_avoid("code_factorial", "write_code_direct")
    print(f"Should avoid write_code_direct: {avoid}")

    # Test response adjustment
    test_response = (
        "Acesta este un răspuns foarte detaliat cu multe informații utile pentru tine."
    )
    adjusted = behavior.get_adjusted_response_style(test_response)
    print(f"Adjusted response: {adjusted[:50]}...")

    # Status
    print(f"\nStatus: {behavior.get_status()}")
