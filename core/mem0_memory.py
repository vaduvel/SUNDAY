"""🧠 Mem0-inspired Memory Layer

Based on Mem0's intelligent memory system for AI agents.
Provides: user/session/agent memory, self-hosting, retrieval with ranking.
"""

import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict

MEM0_DIR = ".jarvis/mem0"


@dataclass
class MemoryEntry:
    """A memory entry with metadata."""

    id: str
    content: str
    memory_type: str  # "user", "session", "agent", "tool"
    user_id: str
    session_id: str
    importance: float
    created_at: str
    last_accessed: str
    access_count: int
    relevance_score: float = 0.0


class Mem0Memory:
    """Mem0-style memory with intelligent retrieval."""

    def __init__(self):
        self.memories: Dict[str, MemoryEntry] = {}
        self._user_id = "jarvis_user"
        self._load()

    def _load(self):
        """Load memories from disk."""
        mem_file = os.path.join(MEM0_DIR, "memories.json")
        os.makedirs(MEM0_DIR, exist_ok=True)

        if os.path.exists(mem_file):
            try:
                with open(mem_file, "r") as f:
                    data = json.load(f)
                    for m in data.get("memories", []):
                        self.memories[m["id"]] = MemoryEntry(**m)
            except:
                pass

    def _save(self):
        """Save memories to disk."""
        mem_file = os.path.join(MEM0_DIR, "memories.json")
        with open(mem_file, "w") as f:
            json.dump(
                {
                    "memories": [asdict(m) for m in self.memories.values()],
                    "updated": datetime.now().isoformat(),
                },
                f,
                indent=2,
            )

    def add(
        self,
        content: str,
        memory_type: str = "session",
        session_id: str = None,
        importance: float = 50.0,
    ) -> str:
        """Add a memory (Mem0-style)."""
        import uuid

        mem_id = f"mem_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        entry = MemoryEntry(
            id=mem_id,
            content=content,
            memory_type=memory_type,
            user_id=self._user_id,
            session_id=session_id or "default",
            importance=importance,
            created_at=now,
            last_accessed=now,
            access_count=1,
        )

        self.memories[mem_id] = entry
        self._save()

        return mem_id

    def get_all(self, memory_type: str = None, limit: int = 20) -> List[Dict]:
        """Get all memories, optionally filtered by type."""
        memories = list(self.memories.values())

        if memory_type:
            memories = [m for m in memories if m.memory_type == memory_type]

        # Sort by importance and recency
        memories.sort(key=lambda m: (m.importance, m.access_count), reverse=True)

        return [
            {
                "id": m.id,
                "content": m.content,
                "type": m.memory_type,
                "importance": m.importance,
                "access_count": m.access_count,
                "created_at": m.created_at,
            }
            for m in memories[:limit]
        ]

    def search(self, query: str, limit: int = 5, memory_type: str = None) -> List[Dict]:
        """Search memories with semantic-like matching (Mem0-style retrieval)."""
        results = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for mem in self.memories.values():
            if memory_type and mem.memory_type != memory_type:
                continue

            # Simple relevance scoring
            content_lower = mem.content.lower()
            content_words = set(content_lower.split())

            # Word overlap
            overlap = len(query_words & content_words)

            # Exact phrase match
            if query_lower in content_lower:
                overlap += 10

            # Calculate relevance score
            relevance = (overlap / max(len(query_words), 1)) * mem.importance / 100

            if relevance > 0:
                mem.relevance_score = relevance
                results.append(mem)

        # Sort by relevance
        results.sort(key=lambda m: m.relevance_score, reverse=True)

        # Update access counts
        for mem in results[:limit]:
            mem.access_count += 1
            mem.last_accessed = datetime.now().isoformat()

        self._save()

        return [
            {
                "id": m.id,
                "content": m.content,
                "type": m.memory_type,
                "relevance": m.relevance_score,
                "importance": m.importance,
            }
            for m in results[:limit]
        ]

    def get_user_preferences(self) -> Dict:
        """Get user preferences (high importance memories)."""
        prefs = {}

        for mem in self.memories.values():
            if mem.memory_type == "user" and mem.importance >= 70:
                # Extract simple key-value from content
                if ":" in mem.content:
                    key, value = mem.content.split(":", 1)
                    prefs[key.strip().lower()] = value.strip()

        return prefs

    def update_importance(self, memory_id: str, importance: float):
        """Update memory importance."""
        if memory_id in self.memories:
            self.memories[memory_id].importance = min(100, max(0, importance))
            self._save()

    def delete(self, memory_id: str):
        """Delete a memory."""
        if memory_id in self.memories:
            del self.memories[memory_id]
            self._save()

    def get_stats(self) -> Dict:
        """Get memory statistics."""
        types = {}
        total = len(self.memories)

        for mem in self.memories.values():
            types[mem.memory_type] = types.get(mem.memory_type, 0) + 1

        return {
            "total_memories": total,
            "by_type": types,
            "avg_importance": sum(m.importance for m in self.memories.values())
            / max(total, 1),
        }


# Singleton
_mem0 = None


def get_mem0_memory() -> Mem0Memory:
    global _mem0
    if _mem0 is None:
        _mem0 = Mem0Memory()
    return _mem0


# Test
if __name__ == "__main__":
    m = get_mem0_memory()

    print("🧠 Mem0-style Memory Test")

    # Add memories
    m.add("User prefers dark mode", "user", importance=80)
    m.add("Working on Python project", "session")
    m.add("User's name is George", "user", importance=90)
    m.add("JARVIS is being built", "agent")
    m.add("Prefers concise responses", "user", importance=70)

    print(f"\nTotal memories: {m.get_stats()}")

    # Search
    print("\nSearch 'user preferences':")
    results = m.search("user preferences")
    for r in results:
        print(f"  - {r['content'][:50]}... (relevance: {r['relevance']:.2f})")

    # Get preferences
    print("\nUser preferences:")
    print(m.get_user_preferences())

    print("\n✅ Mem0 memory ready!")
