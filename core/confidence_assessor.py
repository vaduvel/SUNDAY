"""🎯 Confidence Self-Assessment

Based on Agent Friday's confidence assessor.
The agent evaluates its own confidence in responses and actions.
"""

from typing import Dict, List, Optional
from datetime import datetime


class ConfidenceAssessor:
    """Self-assessment of confidence in responses."""

    def __init__(self):
        self.confidence_history: List[Dict] = []
        self.avg_confidence = 70.0  # Default baseline

    def assess(self, query: str, response: str, context: Dict = None) -> Dict:
        """Assess confidence in the response."""
        context = context or {}

        # Factors that affect confidence
        score = 50.0  # Start neutral
        factors = []

        # 1. Query clarity - is the query clear?
        unclear_indicators = ["?", "maybe", "perhaps", "how about", "unsure"]
        if any(ind in query.lower() for ind in unclear_indicators):
            score -= 10
            factors.append("unclear_query")

        # 2. Response completeness
        if len(response) < 20:
            score -= 15
            factors.append("very_short_response")
        elif len(response) > 500:
            score += 10
            factors.append("detailed_response")

        # 3. Factual indicators
        factual_words = ["definitely", "certainly", "actually", "specifically"]
        if any(w in response.lower() for w in factual_words):
            score += 5
            factors.append("factual_language")

        # 4. Uncertainty indicators
        uncertain_words = [
            "might",
            "could",
            "perhaps",
            "possibly",
            "probably",
            "I think",
            "I'm not sure",
        ]
        if any(w in response.lower() for w in uncertain_words):
            score -= 15
            factors.append("uncertain_language")

        # 5. Technical context
        if context.get("type") == "technical":
            score += 5  # More confident with technical tasks
            factors.append("technical_context")

        # 6. Code/technical content
        if "```" in response or "def " in response or "class " in response:
            score += 10
            factors.append("code_provided")

        # Clamp score
        score = max(10, min(100, score))

        # Determine confidence level
        if score >= 80:
            level = "high"
        elif score >= 50:
            level = "medium"
        else:
            level = "low"

        result = {
            "score": score,
            "level": level,
            "factors": factors,
            "timestamp": datetime.now().isoformat(),
        }

        # Record for history
        self.confidence_history.append(
            {**result, "query_length": len(query), "response_length": len(response)}
        )

        # Keep last 100
        self.confidence_history = self.confidence_history[-100:]

        # Update average
        if self.confidence_history:
            self.avg_confidence = sum(
                h["score"] for h in self.confidence_history
            ) / len(self.confidence_history)

        return result

    def get_contextual_modifier(self, context_type: str) -> float:
        """Get confidence modifier for different contexts."""
        modifiers = {
            "code": 1.1,  # More confident with code
            "technical": 1.05,
            "creative": 0.95,
            "casual": 0.9,
            "research": 0.85,  # Less confident with research
            "legal": 0.8,  # Much less confident with legal
            "medical": 0.7,
        }
        return modifiers.get(context_type, 1.0)

    def should_add_caveat(self, confidence: Dict) -> bool:
        """Should add a caveat/qualification to response?"""
        return confidence["level"] == "low" or confidence["score"] < 50

    def get_caveat_text(self, confidence: Dict) -> str:
        """Get appropriate caveat text based on confidence."""
        if confidence["score"] < 30:
            return "I'm not very confident about this - please verify with additional sources."
        elif confidence["score"] < 50:
            return "I'm somewhat uncertain about this - take this with a grain of salt."
        else:
            return ""

    def get_status(self) -> Dict:
        """Get confidence system status."""
        return {
            "active": True,
            "avg_confidence": self.avg_confidence,
            "assessments_count": len(self.confidence_history),
            "recent_trend": "stable"
            if len(self.confidence_history) < 5
            else (
                "improving"
                if self.confidence_history[-1]["score"]
                > self.confidence_history[-5]["score"]
                else "declining"
            ),
        }


# Singleton
_confidence = None


def get_confidence() -> ConfidenceAssessor:
    global _confidence
    if _confidence is None:
        _confidence = ConfidenceAssessor()
    return _confidence


# Test
if __name__ == "__main__":
    c = get_confidence()

    print("🎯 Confidence Assessor:")
    status = c.get_status()
    print(f"  Avg confidence: {status['avg_confidence']}")

    print("\n🧪 Testing:")

    # Test cases
    test_cases = [
        ("What's the weather?", "The weather is sunny today.", {"type": "general"}),
        (
            "How do I fix this bug?",
            "```python\ndef fix():\n    pass\n```",
            {"type": "technical"},
        ),
        (
            "Maybe what do you think about AI?",
            "I think perhaps it might be good.",
            {"type": "casual"},
        ),
    ]

    for query, response, ctx in test_cases:
        result = c.assess(query, response, ctx)
        print(f"  Query: {query[:30]}...")
        print(f"    Confidence: {result['score']} ({result['level']})")
        print(f"    Factors: {result['factors']}")
