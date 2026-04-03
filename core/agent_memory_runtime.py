"""ReMe-inspired memory scopes built on top of JARVIS structured memory."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from tools.memory_tool import StructuredMemory


class MemoryScope(str, Enum):
    PERSONAL = "personal"
    TASK = "task"
    TOOL = "tool"
    WORKING = "working"


class AgentMemoryRuntime:
    """High-level memory scopes mapped onto the existing 4-type memory system."""

    def __init__(self, structured_memory: StructuredMemory):
        self.structured_memory = structured_memory

    def write(
        self,
        scope: str,
        content: str,
        *,
        session_id: str = "default",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        scope_enum = MemoryScope(scope)
        metadata = metadata or {}
        tags = list(tags or [])

        if scope_enum == MemoryScope.WORKING:
            return self.structured_memory.store_short_term(
                content=content,
                role=metadata.get("role", "system"),
                session_id=session_id,
            )

        if scope_enum == MemoryScope.PERSONAL:
            entity_name = metadata.get("entity_name", "user_profile")
            attributes = {"latest_note": content, **metadata.get("attributes", {})}
            return self.structured_memory.store_entity(
                entity_name=entity_name,
                entity_type=metadata.get("entity_type", "person"),
                attributes=attributes,
            )

        if scope_enum == MemoryScope.TASK:
            long_term = self.structured_memory.store_long_term(
                observation=content,
                tags=list(dict.fromkeys(tags + ["task"])),
                quality_score=metadata.get("quality_score"),
                mission_type=metadata.get("mission_type", "general"),
            )
            episodic = self.structured_memory.store_episodic(
                event=content,
                context=metadata.get("context", ""),
                importance=float(metadata.get("importance", 0.6)),
                tags=list(dict.fromkeys(tags + ["task"])),
            )
            return {"long_term": long_term, "episodic": episodic}

        tool_name = metadata.get("tool_name", "unknown_tool")
        entity = self.structured_memory.store_entity(
            entity_name=tool_name,
            entity_type="tool",
            attributes={
                "latest_memory": content,
                "last_outcome": metadata.get("outcome", "unknown"),
            },
        )
        long_term = self.structured_memory.store_long_term(
            observation=f"Tool memory [{tool_name}]: {content}",
            tags=list(dict.fromkeys(tags + ["tool", tool_name])),
            quality_score=metadata.get("quality_score"),
            mission_type="tooling",
        )
        return {"entity": entity, "long_term": long_term}

    def recall(
        self,
        scope: str,
        *,
        query: str = "",
        session_id: str = "default",
        limit: int = 5,
    ) -> Dict[str, Any]:
        scope_enum = MemoryScope(scope)

        if scope_enum == MemoryScope.WORKING:
            return {"scope": scope, "results": self.structured_memory.recall_short_term(session_id=session_id, limit=limit)}

        if scope_enum == MemoryScope.PERSONAL:
            return {"scope": scope, "results": self.structured_memory.recall_entity(entity_name=query or None, entity_type="person")}

        if scope_enum == MemoryScope.TASK:
            keywords = [token for token in query.split() if token] or ["task"]
            return {
                "scope": scope,
                "episodic": self.structured_memory.recall_episodic(query=query or None, limit=limit),
                "long_term": self.structured_memory.recall_long_term(keywords=keywords, limit=limit),
            }

        tool_entities = self.structured_memory.recall_entity(entity_name=query or None, entity_type="tool")
        keywords = [token for token in query.split() if token] or ["tool"]
        return {
            "scope": scope,
            "entity": tool_entities[:limit],
            "long_term": self.structured_memory.recall_long_term(keywords=keywords, limit=limit),
        }

    def summary(self, *, session_id: str = "default") -> Dict[str, Any]:
        working = self.structured_memory.recall_short_term(session_id=session_id, limit=5)
        personal = self.structured_memory.recall_entity(entity_type="person")
        tool = self.structured_memory.recall_entity(entity_type="tool")
        episodic = self.structured_memory.recall_episodic(limit=5)
        return {
            "working_count": len(working),
            "personal_count": len(personal),
            "tool_count": len(tool),
            "episodic_count": len(episodic),
            "working_preview": [item.get("content", "")[:120] for item in working],
            "personal_preview": [item.get("entity_name", "") for item in personal[:5]],
            "tool_preview": [item.get("entity_name", "") for item in tool[:5]],
        }
