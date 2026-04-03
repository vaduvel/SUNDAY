"""Structured long-term memory with auto-learning capabilities.

Provides:
- Tagged, scored memory entries
- Lesson extraction (what worked / what failed)
- Anti-repetition guard
- Relevance-based retrieval
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MEMORY_PATH = Path("memory/long_term_memory.json")
LESSONS_PATH = Path("memory/lessons_learned.json")


def _get_mem0_bridge():
    try:
        from core.mem0_memory import get_mem0_memory

        return get_mem0_memory()
    except Exception:
        return None


def _mirror_to_mem0(
    content: str,
    *,
    memory_type: str = "session",
    session_id: str | None = None,
    importance: float = 50.0,
) -> None:
    if not content.strip():
        return
    mem0 = _get_mem0_bridge()
    if mem0 is None:
        return
    try:
        mem0.add(
            content=content.strip(),
            memory_type=memory_type,
            session_id=session_id,
            importance=importance,
        )
    except Exception:
        pass


def _search_mem0(query: str, limit: int = 3) -> list[dict[str, Any]]:
    mem0 = _get_mem0_bridge()
    if mem0 is None or not query.strip():
        return []
    try:
        results = mem0.search(query, limit=limit)
        return results if isinstance(results, list) else []
    except Exception:
        return []


# ─── File helpers ───────────────────────────────────────────────


def _ensure_file(path: Path, default: str = "[]") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(default, encoding="utf-8")


def _load_json(path: Path) -> list[dict[str, Any]]:
    _ensure_file(path)
    raw = path.read_text(encoding="utf-8").strip() or "[]"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = []
    return data if isinstance(data, list) else []


def _save_json(path: Path, data: list) -> None:
    _ensure_file(path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Core memory API ───────────────────────────────────────────


def load_memory() -> list[dict[str, Any]]:
    """Load all memory entries."""
    return _load_json(MEMORY_PATH)


def save_to_memory(
    observation: str,
    source: str = "Chronos",
    tags: list[str] | None = None,
    quality_score: int | None = None,
    mission_type: str | None = None,
) -> dict[str, Any]:
    """Save a structured memory entry.

    Args:
        observation: What happened (the learning content).
        source: Which agent or system recorded this.
        tags: Categorization tags (e.g. ["marketing", "cafea", "landing-page"]).
        quality_score: Self-assessed quality 1-10 (None if not evaluated).
        mission_type: Type of mission (business, code, research, design, general).
    """
    if not observation.strip():
        raise ValueError("Observation cannot be empty.")

    entries = load_memory()
    entry = {
        "id": len(entries) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "observation": observation.strip(),
        "tags": tags or [],
        "quality_score": quality_score,
        "mission_type": mission_type or "general",
    }
    entries.append(entry)
    _save_json(MEMORY_PATH, entries)
    _mirror_to_mem0(
        observation,
        memory_type="agent" if source.lower() == "jarvis" else "session",
        importance=float(quality_score or 50),
    )
    return entry


# ─── Lessons Learned (Auto-Learning) ──────────────────────────


def load_lessons() -> list[dict[str, Any]]:
    """Load extracted lessons."""
    return _load_json(LESSONS_PATH)


def save_lesson(
    lesson: str,
    category: str,
    severity: str = "info",
    agent: str = "system",
) -> dict[str, Any]:
    """Save a learned lesson for future missions.

    Args:
        lesson: The actionable insight (e.g. "Always include pricing tables").
        category: Domain category (marketing, code, design, research, process).
        severity: Importance level - "critical", "warning", "info".
        agent: Which agent discovered this.
    """
    lessons = load_lessons()
    entry = {
        "id": len(lessons) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lesson": lesson.strip(),
        "category": category.strip().lower(),
        "severity": severity,
        "agent": agent,
        "times_applied": 0,
    }
    lessons.append(entry)
    _save_json(LESSONS_PATH, lessons)
    _mirror_to_mem0(
        f"[lesson:{category}] {lesson.strip()}",
        memory_type="agent",
        importance=85.0 if severity == "critical" else 70.0 if severity == "warning" else 55.0,
    )
    return entry


def get_relevant_lessons(mission_type: str, limit: int = 5) -> list[dict]:
    """Get lessons relevant to a mission type.

    Returns the most relevant lessons sorted by severity and recency.
    """
    lessons = load_lessons()
    if not lessons:
        return []

    # Score each lesson for relevance
    severity_weight = {"critical": 3, "warning": 2, "info": 1}

    scored = []
    for lesson in lessons:
        score = severity_weight.get(lesson.get("severity", "info"), 1)
        # Boost if category matches
        if lesson.get("category", "") == mission_type:
            score += 5
        # Boost if category is "process" (always relevant)
        if lesson.get("category", "") == "process":
            score += 2
        scored.append((score, lesson))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]


# ─── Retrieval helpers ────────────────────────────────────────


def search_memory(keywords: list[str], limit: int = 5) -> list[dict]:
    """Search memory entries by keywords (simple text matching).

    Returns entries that match any of the keywords, scored by match count.
    """
    entries = load_memory()
    if not entries or not keywords:
        return entries[-limit:]  # Return most recent if no keywords

    scored = []
    for entry in entries:
        text = (
            entry.get("observation", "") + " " + " ".join(entry.get("tags", []))
        ).lower()
        match_count = sum(1 for kw in keywords if kw.lower() in text)
        if match_count > 0:
            scored.append((match_count, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def get_memory_summary() -> str:
    """Create a concise summary of all memory for agents to consume."""
    entries = load_memory()
    lessons = load_lessons()

    if not entries and not lessons:
        return "Memorie goală. Aceasta este prima misiune."

    lines = []

    # Memory statistics
    total = len(entries)
    scored = [e for e in entries if e.get("quality_score") is not None]
    avg_quality = sum(e["quality_score"] for e in scored) / len(scored) if scored else 0

    lines.append(
        f"📊 STATISTICI MEMORIE: {total} misiuni înregistrate, scor mediu calitate: {avg_quality:.1f}/10"
    )
    lines.append("")

    # Recent missions (last 3)
    recent = entries[-3:]
    if recent:
        lines.append("📋 ULTIMELE 3 MISIUNI:")
        for e in recent:
            score_str = (
                f" [Scor: {e['quality_score']}/10]" if e.get("quality_score") else ""
            )
            tags_str = f" #{' #'.join(e['tags'])}" if e.get("tags") else ""
            lines.append(f"  • {e['observation'][:150]}{score_str}{tags_str}")
        lines.append("")

    # Active lessons
    if lessons:
        lines.append("🎓 LECȚII ÎNVĂȚATE:")
        for lesson in lessons[-5:]:
            severity_icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(
                lesson.get("severity", "info"), "🔵"
            )
            lines.append(f"  {severity_icon} [{lesson['category']}] {lesson['lesson']}")

    return "\n".join(lines)


def get_anti_repetition_guard(mission: str) -> str:
    """Check if we've done this exact mission before and what to avoid.

    Returns guidance text for agents to prevent repeating mistakes.
    """
    entries = load_memory()
    lessons = load_lessons()

    warnings = []

    # Check for similar past missions
    mission_lower = mission.lower()
    mission_words = set(re.findall(r"\w+", mission_lower))

    for entry in entries:
        obs_words = set(re.findall(r"\w+", entry.get("observation", "").lower()))
        overlap = len(mission_words & obs_words)
        if overlap >= 3:  # Similar mission
            score = entry.get("quality_score")
            if score and score < 5:
                warnings.append(
                    f"⚠️ O misiune similară a avut scor {score}/10. "
                    f"Observație: {entry['observation'][:100]}"
                )

    # Add critical lessons
    critical = [l for l in lessons if l.get("severity") == "critical"]
    for lesson in critical[-3:]:
        warnings.append(f"🔴 LECȚIE CRITICĂ: {lesson['lesson']}")

    if not warnings:
        return "Nu există avertismente din misiuni anterioare."

    return "\n".join(warnings)


# ═══════════════════════════════════════════════════════════════
#  LLM RECALL - Semantic Memory Search (Claude Code Pattern)
# ═══════════════════════════════════════════════════════════════


async def llm_recall(query: str, limit: int = 5) -> str:
    """
    LLM-powered memory recall - finds relevant memories using AI, not keywords.
    Like Claude Code's "Sonnet side-query selects relevant memories".
    """
    try:
        from core.brain import call_brain, PRO_MODEL

        entries = load_memory()
        lessons = load_lessons()

        if not entries and not lessons:
            return "Nu am memorie încă."

        # Build context for LLM
        memory_context = "## MEMORIE EXISTENTĂ:\n"

        # Add recent missions
        for e in entries[-10:]:
            memory_context += f"- Misiune: {e.get('observation', '')[:200]}\n"
            if e.get("tags"):
                memory_context += f"  Tags: {', '.join(e['tags'])}\n"

        # Add lessons
        if lessons:
            memory_context += "\n## LECȚII ÎNVĂȚATE:\n"
            for l in lessons[-5:]:
                memory_context += f"- [{l.get('severity')}] {l.get('lesson', '')}\n"

        # Ask LLM to find relevant info
        prompt = f"""Ești un asistent de memorie. Analizează memoria și găsește ce e relevant pentru query-ul utilizatorului.

{memory_context}

## QUERY: {query}

Returnează cele mai relevante 3-5 entries din memorie care au legătură cu query-ul.
Dacă nu găsești nimic relevant, spune "Nu am găsit memorie relevantă pentru '{query}'"."""

        result = await call_brain(
            [{"role": "user", "content": prompt}], model=PRO_MODEL, profile="precise"
        )

        return result

    except Exception as e:
        return f"LLM recall failed: {e}. Folosesc căutare basic."


async def semantic_memory_search(query: str) -> list[dict]:
    """Hybrid search: LLM for semantic, keyword as fallback."""
    try:
        llm_result = await llm_recall(query, limit=5)

        if (
            llm_result
            and "Nu am găsit" not in llm_result
            and "LLM recall failed" not in llm_result
        ):
            return [{"type": "llm", "content": llm_result}]
        else:
            keywords = query.lower().split()
            results = search_memory(keywords, limit=5)
            return [{"type": "keyword", "results": results}]
    except:
        keywords = query.lower().split()
        return search_memory(keywords, limit=5)


# ═══════════════════════════════════════════════════════════════
#  STRUCTURED MEMORY — 4 Types (PraisonAI Pattern)
#
#  short_term  — recent conversation turns (volatile, last N)
#  long_term   — existing MEMORY_PATH (persisted missions)
#  entity      — facts about specific people/projects/tools
#  episodic    — timestamped events with importance scoring
# ═══════════════════════════════════════════════════════════════

SHORT_TERM_PATH = Path("memory/short_term.json")
ENTITY_MEMORY_PATH = Path("memory/entity_memory.json")
EPISODIC_MEMORY_PATH = Path("memory/episodic_memory.json")

_SHORT_TERM_LIMIT = 30  # Max items in short-term memory


class StructuredMemory:
    """4-type memory system inspired by PraisonAI."""

    # ── Short-term ─────────────────────────────────────────────

    def store_short_term(
        self, content: str, role: str = "user", session_id: str = "default"
    ) -> dict[str, Any]:
        """Store a recent conversation turn."""
        data = _load_json(SHORT_TERM_PATH)
        entry = {
            "id": len(data) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "role": role,
            "content": content.strip(),
        }
        data.append(entry)
        # Keep only last N
        if len(data) > _SHORT_TERM_LIMIT:
            data = data[-_SHORT_TERM_LIMIT:]
        _save_json(SHORT_TERM_PATH, data)
        if role in {"user", "assistant"}:
            _mirror_to_mem0(
                f"[{role}] {content.strip()}",
                memory_type="session",
                session_id=session_id,
                importance=25.0,
            )
        return entry

    def recall_short_term(self, session_id: str = None, limit: int = 10) -> list[dict]:
        """Recall recent conversation turns."""
        data = _load_json(SHORT_TERM_PATH)
        if session_id:
            data = [d for d in data if d.get("session_id") == session_id]
        return data[-limit:]

    def clear_short_term(self, session_id: str = None):
        """Clear short-term memory (end of session)."""
        if session_id is None:
            _save_json(SHORT_TERM_PATH, [])
        else:
            data = [
                d
                for d in _load_json(SHORT_TERM_PATH)
                if d.get("session_id") != session_id
            ]
            _save_json(SHORT_TERM_PATH, data)

    # ── Entity ─────────────────────────────────────────────────

    def store_entity(
        self,
        entity_name: str,
        entity_type: str,
        attributes: dict[str, Any],
    ) -> dict[str, Any]:
        """Store or update a fact about a specific entity.

        entity_type: person | project | tool | concept | organization
        """
        data = _load_json(ENTITY_MEMORY_PATH)
        # Upsert by entity_name
        existing = next(
            (d for d in data if d.get("entity_name") == entity_name), None
        )
        if existing:
            existing["attributes"].update(attributes)
            existing["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save_json(ENTITY_MEMORY_PATH, data)
            _mirror_to_mem0(
                f"[entity:{entity_type}] {entity_name}: {json.dumps(existing['attributes'], ensure_ascii=False)}",
                memory_type="user" if entity_type == "person" else "agent",
                importance=80.0,
            )
            return existing

        entry = {
            "id": len(data) + 1,
            "entity_name": entity_name,
            "entity_type": entity_type,
            "attributes": attributes,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        data.append(entry)
        _save_json(ENTITY_MEMORY_PATH, data)
        _mirror_to_mem0(
            f"[entity:{entity_type}] {entity_name}: {json.dumps(attributes, ensure_ascii=False)}",
            memory_type="user" if entity_type == "person" else "agent",
            importance=80.0,
        )
        return entry

    def recall_entity(
        self, entity_name: str = None, entity_type: str = None
    ) -> list[dict]:
        """Recall entities by name or type."""
        data = _load_json(ENTITY_MEMORY_PATH)
        if entity_name:
            data = [
                d
                for d in data
                if entity_name.lower() in d.get("entity_name", "").lower()
            ]
        if entity_type:
            data = [d for d in data if d.get("entity_type") == entity_type]
        return data

    # ── Episodic ───────────────────────────────────────────────

    def store_episodic(
        self,
        event: str,
        context: str = "",
        importance: float = 0.5,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Store a timestamped event with importance scoring (0-1)."""
        data = _load_json(EPISODIC_MEMORY_PATH)
        entry = {
            "id": len(data) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event.strip(),
            "context": context.strip(),
            "importance": max(0.0, min(1.0, importance)),
            "tags": tags or [],
        }
        data.append(entry)
        _save_json(EPISODIC_MEMORY_PATH, data)
        _mirror_to_mem0(
            f"[episodic] {event.strip()} | {context.strip()}",
            memory_type="session",
            importance=max(30.0, min(100.0, importance * 100.0)),
        )
        return entry

    def recall_episodic(
        self, query: str = None, min_importance: float = 0.0, limit: int = 10
    ) -> list[dict]:
        """Recall episodic events, optionally filtered by keyword + importance."""
        data = _load_json(EPISODIC_MEMORY_PATH)
        data = [d for d in data if d.get("importance", 0) >= min_importance]
        if query:
            q = query.lower()
            data = [
                d
                for d in data
                if q in d.get("event", "").lower()
                or q in d.get("context", "").lower()
                or any(q in t.lower() for t in d.get("tags", []))
            ]
        # Sort by importance desc, then recency
        data.sort(key=lambda d: (d.get("importance", 0), d.get("id", 0)), reverse=True)
        return data[:limit]

    # ── Long-term (proxy to existing API) ─────────────────────

    def store_long_term(
        self,
        observation: str,
        tags: list[str] | None = None,
        quality_score: int | None = None,
        mission_type: str | None = None,
    ) -> dict[str, Any]:
        """Persist to long-term memory (existing mission memory)."""
        return save_to_memory(
            observation=observation,
            tags=tags,
            quality_score=quality_score,
            mission_type=mission_type,
        )

    def recall_long_term(self, keywords: list[str], limit: int = 5) -> list[dict]:
        return search_memory(keywords, limit=limit)

    # ── Unified context ────────────────────────────────────────

    def get_full_context(self, query: str = "", session_id: str = "default") -> str:
        """Unified context string from all 4 memory types for LLM injection."""
        lines = ["## JARVIS STRUCTURED MEMORY\n"]

        # Short-term (current session)
        st = self.recall_short_term(session_id=session_id, limit=5)
        if st:
            lines.append("### Short-term (recent turns):")
            for m in st:
                lines.append(f"  [{m['role']}] {m['content'][:100]}")

        # Entity memory
        entities = self.recall_entity()
        if entities:
            lines.append("\n### Entity memory (known facts):")
            for e in entities[:5]:
                attrs = ", ".join(f"{k}={v}" for k, v in e["attributes"].items())
                lines.append(f"  [{e['entity_type']}] {e['entity_name']}: {attrs[:100]}")

        # Episodic (important events)
        episodic = self.recall_episodic(query=query, min_importance=0.6, limit=5)
        if episodic:
            lines.append("\n### Episodic (key events):")
            for ep in episodic:
                lines.append(
                    f"  [{ep['importance']:.1f}] {ep['event'][:100]}"
                )

        # Long-term summary
        lt_summary = get_memory_summary()
        if lt_summary and "goală" not in lt_summary:
            lines.append(f"\n### Long-term:\n{lt_summary[:400]}")

        mem0_hits = _search_mem0(query, limit=3)
        if mem0_hits:
            lines.append("\n### Mem0 bridge:")
            for hit in mem0_hits:
                content = str(hit.get("content") or "").strip()
                if not content:
                    continue
                relevance = hit.get("relevance")
                prefix = f"  [{relevance:.2f}] " if isinstance(relevance, (int, float)) else "  "
                lines.append(f"{prefix}{content[:140]}")

        return "\n".join(lines)


# Module-level singleton for convenience
_structured_memory: StructuredMemory | None = None


def get_structured_memory() -> StructuredMemory:
    global _structured_memory
    if _structured_memory is None:
        _structured_memory = StructuredMemory()
    return _structured_memory
