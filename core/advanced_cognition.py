"""🧠 JARVIS Advanced Cognition - Beyond Opus Level

Makes JARVIS:
- Ask clarifying questions when confused
- Proactively suggest alternatives
- Judge requests ethically
- Self-correct when wrong
- Remember user preferences
- Understand deeper context
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json

logger = logging.getLogger(__name__)


class RequestType(Enum):
    """Type of user request."""

    CLEAR = "clear"  # Perfectly understood
    AMBIGUOUS = "ambiguous"  # Could mean multiple things
    INCOMPLETE = "incomplete"  # Missing information
    COMPLEX = "complex"  # Needs multiple steps
    RISKY = "risky"  # Potentially dangerous
    UNKNOWN = "unknown"  # Don't understand at all


@dataclass
class ClarifyingQuestion:
    """A question JARVIS asks to clarify."""

    id: str
    question: str
    options: List[str] = field(default_factory=list)
    context: str = ""
    priority: int = 1  # 1-5


@dataclass
class Suggestion:
    """A proactive suggestion from JARVIS."""

    id: str
    suggestion: str
    reason: str
    alternatives: List[str] = field(default_factory=list)
    confidence: float = 0.5


@dataclass
class UserPreference:
    """User preference stored for future reference."""

    key: str
    value: Any
    context: str
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Judgment:
    """Ethical judgment on a request."""

    is_safe: bool
    concerns: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    should_ask_confirmation: bool = False


class AdvancedCognition:
    """
    Makes JARVIS think like Opus - with judgment, questions, and self-correction.
    """

    def __init__(self, llm_executor: Optional[Callable] = None):
        self.llm_executor = llm_executor

        # User preferences memory
        self.preferences: Dict[str, UserPreference] = {}

        # Clarification history
        self.pending_clarifications: List[ClarifyingQuestion] = []

        # Self-correction history
        self.corrections: List[Dict] = []

    # ═══════════════════════════════════════════════════════════
    # CLARIFYING QUESTIONS (opus asks when unclear)
    # ═══════════════════════════════════════════════════════════

    async def analyze_request(self, request: str) -> RequestType:
        """Analyze how clear a request is."""

        # Check for ambiguity
        ambiguous_patterns = [
            "that",
            "it",
            "the same",
            "again",
            "those",
            "do it",
            "fix it",
            "change it",
            "update it",
        ]

        # Check for incompleteness
        incomplete_patterns = ["start", "begin", "try", "see", "check"]

        # Check for risk
        risky_patterns = [
            "delete everything",
            "remove all",
            "drop database",
            "format",
            "rm -rf",
            "sudo",
            "install",
            "execute",
        ]

        request_lower = request.lower()

        if any(p in request_lower for p in risky_patterns):
            return RequestType.RISKY

        if any(p in request_lower for p in ambiguous_patterns):
            return RequestType.AMBIGUOUS

        if any(p in request_lower for p in incomplete_patterns):
            return RequestType.INCOMPLETE

        return RequestType.CLEAR

    async def generate_clarifying_questions(
        self, request: str
    ) -> List[ClarifyingQuestion]:
        """Generate questions when request is unclear."""

        request_type = await self.analyze_request(request)

        if request_type == RequestType.CLEAR:
            return []

        questions = []

        if request_type == RequestType.AMBIGUOUS:
            questions.append(
                ClarifyingQuestion(
                    id="q1",
                    question="Nu e clar ce vrei să faci. Poți fi mai specific?",
                    options=[
                        "Vreau să modifici un fișier",
                        "Vrei să adaugi o funcționalitate nouă",
                        "Vrei să corectezi un bug",
                    ],
                    context=request,
                )
            )

        elif request_type == RequestType.INCOMPLETE:
            questions.append(
                ClarifyingQuestion(
                    id="q2",
                    question="Începi ceva dar nu spui cum vrei să se termine. Ce ar trebui să rezulte?",
                    options=[
                        "Un fișier creat",
                        "Un output în consolă",
                        "O modificare în proiect",
                    ],
                    context=request,
                )
            )

        elif request_type == RequestType.RISKY:
            questions.append(
                ClarifyingQuestion(
                    id="q3",
                    question="asta pare riscant. Ești sigur? Ce ar trebui să se întâmple exact?",
                    options=["Da, continuă", "Nu, anulează", "Explică-mi mai mult"],
                    context=request,
                    priority=5,
                )
            )

        return questions

    async def should_ask_question(self, request: str) -> bool:
        """Decide if JARVIS should ask clarification."""
        request_type = await self.analyze_request(request)
        return request_type != RequestType.CLEAR

    # ═══════════════════════════════════════════════════════════
    # PROACTIVE SUGGESTIONS (opus suggests alternatives)
    # ═══════════════════════════════════════════════════════════

    async def generate_suggestions(self, request: str) -> List[Suggestion]:
        """Generate proactive suggestions before executing."""

        suggestions = []

        # Check if there are better ways
        if self.llm_executor and callable(self.llm_executor):
            prompt = f"""User request: {request}

What are 3 different ways to approach this? Which is best?"""
            try:
                result = await self.llm_executor(prompt, "You are a helpful assistant.")

                # Parse into suggestions
                suggestions.append(
                    Suggestion(
                        id="s1",
                        suggestion="S-ar putea să existe o abordare mai bună",
                        reason="Am analizat cererea ta",
                        alternatives=result.content.split("\n")[:3]
                        if hasattr(result, "content")
                        else [],
                        confidence=0.7,
                    )
                )
            except:
                pass
        else:
            # Rule-based fallback
            if "write code" in request.lower():
                suggestions.append(
                    Suggestion(
                        id="s_code",
                        suggestion="Înainte să scriu cod, vrei să verific mai întâi structura existentă?",
                        reason="Înțelegerea contextului îmbunătățește calitatea",
                        alternatives=["Da, verifică", "Nu, scrie direct"],
                        confidence=0.8,
                    )
                )

            if "fix" in request.lower() or "debug" in request.lower():
                suggestions.append(
                    Suggestion(
                        id="s_debug",
                        suggestion="Vrei să rulez mai întâi testele ca să văd exact ce e stricat?",
                        reason="Testele arată exact ce e problema",
                        alternatives=["Da, rulează teste", "Nu, scrie direct"],
                        confidence=0.9,
                    )
                )

        return suggestions

    # ═══════════════════════════════════════════════════════════
    # ETHICAL JUDGMENT (opus refuses intelligently)
    # ═══════════════════════════════════════════════════════════

    async def judge_request(self, request: str) -> Judgment:
        """Judge if request is safe and appropriate."""

        concerns = []
        should_confirm = False

        request_lower = request.lower()

        # Security concerns
        security_risks = [
            ("sudo", "Comandă cu privilegii de administrator"),
            ("rm -rf", "Ștergere forțată și ireversibilă"),
            ("drop database", "Ștergerea bazei de date"),
            ("curl | sh", "Execuție cod din sursă externă"),
            ("chmod 777", "Permisiuni nesigure"),
            ("eval", "Execuție dinamică de cod"),
        ]

        for pattern, concern in security_risks:
            if pattern in request_lower:
                concerns.append(concern)
                should_confirm = True

        # Harmful content
        harmful_patterns = [
            "hack",
            "exploit",
            "bypass",
            "crack",
            "steal",
            "phish",
            "spam",
        ]

        for pattern in harmful_patterns:
            if pattern in request_lower:
                concerns.append(f"Conține cuvânt potențial periculos: {pattern}")
                should_confirm = True

        # Destructive operations
        destructive = ["delete all", "remove all", "format", "destroy", "wipe"]

        for pattern in destructive:
            if pattern in request_lower:
                concerns.append("Operație potențial distructivă")
                should_confirm = True

        return Judgment(
            is_safe=len(concerns) == 0,
            concerns=concerns,
            suggestions=self._generate_safety_suggestions(concerns),
            should_ask_confirmation=should_confirm,
        )

    def _generate_safety_suggestions(self, concerns: List[str]) -> List[str]:
        """Generate safety suggestions based on concerns."""
        suggestions = []

        if any("sudo" in c for c in concerns):
            suggestions.append("Verifică exact ce face comanda înainte de executare")

        if any("delete" in c or "remove" in c for c in concerns):
            suggestions.append("Fă backup înainte de a continua")

        if any("hack" in c for c in concerns):
            suggestions.append("Asigură-te că ai permisiunea pentru ce faci")

        return suggestions

    # ═══════════════════════════════════════════════════════════
    # SELF-CORRECTION (opus fixes itself)
    # ═══════════════════════════════════════════════════════════

    async def reflect_and_correct(
        self, action: str, result: Any, expected: Any
    ) -> Dict[str, Any]:
        """Self-correct after an action."""

        corrections_made = []

        # Check if result matches expectations
        if str(result) == "error" or "failed" in str(result).lower():
            corrections_made.append(
                "Execuția a eșuat - trebuie reconsiderată abordarea"
            )

        # Check if we should have asked first
        should_have_clarified = await self.should_ask_question(action)
        if should_have_clarified:
            corrections_made.append("Ar fi trebuit să întreb pentru clarificare")

        # Check for better alternatives we missed
        suggestions = await self.generate_suggestions(action)
        if suggestions:
            corrections_made.append(f"Am găsit {len(suggestions)} sugestii alternative")

        # Record correction
        correction = {
            "action": action,
            "result": str(result)[:200],
            "expected": str(expected)[:200] if expected else "unknown",
            "corrections": corrections_made,
            "timestamp": datetime.now().isoformat(),
        }

        self.corrections.append(correction)

        return {
            "needs_correction": len(corrections_made) > 0,
            "corrections": corrections_made,
            "lesson": self._extract_lesson(corrections_made),
        }

    def _extract_lesson(self, corrections: List[str]) -> str:
        """Extract a lesson from corrections."""
        if any("clarif" in c.lower() for c in corrections):
            return "Întreabă mai întâi când nu e clar"
        if any("error" in c.lower() or "fail" in c.lower() for c in corrections):
            return "Verifică rezultatele înainte de a continua"
        return "Analizează cererea mai bine"

    # ═══════════════════════════════════════════════════════════
    # USER PREFERENCES (opus remembers you)
    # ═══════════════════════════════════════════════════════════

    async def learn_preference(self, key: str, value: Any, context: str = ""):
        """Learn a user preference."""
        pref = UserPreference(key=key, value=value, context=context)
        self.preferences[key] = pref
        logger.info(f"💾 [PREF] Learned: {key} = {value}")

    async def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        pref = self.preferences.get(key)
        return pref.value if pref else default

    async def check_preferences(self, request: str) -> List[str]:
        """Check if request matches any user preferences."""
        matches = []

        for key, pref in self.preferences.items():
            if key.lower() in request.lower():
                matches.append(f"Știu că preferi: {pref.value}")

        return matches

    # ═══════════════════════════════════════════════════════════
    # DEEPER CONTEXT (opus understands more)
    # ═══════════════════════════════════════════════════════════

    async def understand_deeper(self, request: str, context: Dict) -> Dict[str, Any]:
        """Understand the deeper meaning/context of a request."""

        # Extract implicit goals
        implicit_goals = []

        if "make" in request.lower() or "create" in request.lower():
            implicit_goals.append("vrei să creezi ceva nou")

        if "fix" in request.lower() or "repair" in request.lower():
            implicit_goals.append("vrei să rezolvi o problemă")

        if "improve" in request.lower() or "better" in request.lower():
            implicit_goals.append("vrei să îmbunătățești ceva existent")

        # Check for emotional tone
        emotional_indicators = {
            "urgent": "par urgent",
            "asap": "par grabit",
            "important": "par important",
            "careful": "par nevoie de atenție",
        }

        tone = []
        for word, feeling in emotional_indicators.items():
            if word in request.lower():
                tone.append(feeling)

        return {
            "implicit_goals": implicit_goals,
            "emotional_tone": tone,
            "confidence": 0.7 if implicit_goals else 0.3,
        }

    # ═══════════════════════════════════════════════════════════
    # MAIN: FULL ANALYSIS (like opus does)
    # ═══════════════════════════════════════════════════════════

    async def full_analysis(self, request: str, context: Dict = None) -> Dict[str, Any]:
        """Full analysis like Opus would do."""

        context = context or {}

        # 1. Judge safety
        judgment = await self.judge_request(request)

        # 2. Check if should ask clarification
        should_clarify = await self.should_ask_question(request)
        questions = (
            await self.generate_clarifying_questions(request) if should_clarify else []
        )

        # 3. Generate proactive suggestions
        suggestions = await self.generate_suggestions(request)

        # 4. Check user preferences
        pref_matches = await self.check_preferences(request)

        # 5. Understand deeper context
        deeper = await self.understand_deeper(request, context)

        return {
            "judgment": {
                "is_safe": judgment.is_safe,
                "concerns": judgment.concerns,
                "needs_confirmation": judgment.should_ask_confirmation,
            },
            "clarification": {
                "needed": should_clarify,
                "questions": [q.question for q in questions],
            },
            "suggestions": [s.suggestion for s in suggestions],
            "preferences": pref_matches,
            "context": deeper,
            "ready_to_execute": judgment.is_safe and not should_clarify,
        }


# Standalone test
if __name__ == "__main__":

    async def test():
        cognition = AdvancedCognition()

        # Test 1: Ambiguous request
        print("=== Test 1: Ambiguous request ===")
        request = "fix it"
        analysis = await cognition.full_analysis(request)
        print(f"Should ask clarification: {analysis['clarification']['needed']}")
        print(f"Questions: {analysis['clarification']['questions']}")

        # Test 2: Risky request
        print("\n=== Test 2: Risky request ===")
        request = "sudo rm -rf /"
        analysis = await cognition.full_analysis(request)
        print(f"Is safe: {analysis['judgment']['is_safe']}")
        print(f"Concerns: {analysis['judgment']['concerns']}")

        # Test 3: Learn preference
        print("\n=== Test 3: Preferences ===")
        await cognition.learn_preference(
            "coding_style", "clean and documented", "user prefers clean code"
        )
        style = await cognition.get_preference("coding_style")
        print(f"User prefers: {style}")

        # Test 4: Clear request with suggestions
        print("\n=== Test 4: Clear request ===")
        request = "write a function to sort a list"
        analysis = await cognition.full_analysis(request)
        print(f"Can execute: {analysis['ready_to_execute']}")
        print(f"Suggestions: {analysis['suggestions']}")

    asyncio.run(test())
