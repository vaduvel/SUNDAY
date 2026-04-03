"""J.A.R.V.I.S. (GALAXY NUCLEUS - CONTEXT COMPACTOR V2)

The physical engine for handling massive token windows with Persistent Memory.
Integrated with Obsidian for 'Long-term Semantic Anchoring'.

4-Layer Context Compression (Claude Code Pattern):
1. SNIP - remove recent duplicates
2. MICROCOMPACT - summarize short sections
3. COLLAPSE - merge similar messages
4. AUTOCOMPACT - auto-truncate when hitting limits
"""

import os
import re
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Token estimation (approx 1 token = 0.25 words)
TOKENS_PER_CHAR = 0.25


class FourLayerCompressor:
    """
    Claude Code's 4-layer context compression:
    - snip: remove duplicate recent messages
    - microcompact: summarize short sections
    - collapse: merge similar messages
    - autocompact: auto-truncate when hitting limits
    """

    def __init__(self, limit: int = 120000):
        self.limit = limit

    def compress(self, messages: List[Dict]) -> List[Dict]:
        if not messages:
            return messages

        # Layer 1: SNIP - remove duplicates
        messages = self._layer1_snip(messages)

        # Layer 2: MICROCOMPACT - summarize short messages
        messages = self._layer2_microcompact(messages)

        # Layer 3: COLLAPSE - merge similar
        messages = self._layer3_collapse(messages)

        # Layer 4: AUTOCOMPACT - truncate if needed
        messages = self._layer4_autocompact(messages)

        return messages

    def _layer1_snip(self, messages: List[Dict]) -> List[Dict]:
        """Remove exact consecutive duplicates in memory."""
        if not messages: return []
        
        result = [messages[0]]
        for msg in messages[1:]:
            # If completely identical to the previous, discard
            if msg.get("role") == result[-1].get("role") and msg.get("content") == result[-1].get("content"):
                continue
            result.append(msg)
            
        return result

    def _layer2_microcompact(self, messages: List[Dict]) -> List[Dict]:
        """Filters out non-essential microssages safely without destruction."""
        result = []
        for msg in messages:
            content = msg.get("content", "").strip()
            # If the agent merely said 'ok' or similar very low value padding, ignore it
            # But ONLY if it is less than 15 chars. Do not buffer and drop like before.
            if msg.get("role") == "assistant" and len(content) < 15 and content.lower() in ["ok", "done", "understood", "yes"]:
                continue
            result.append(msg)
            
        return result

    def _layer3_collapse(self, messages: List[Dict]) -> List[Dict]:
        """Properly merge consecutive messages of the same role."""
        if len(messages) < 2:
            return messages

        result = [messages[0].copy()]

        for i in range(1, len(messages)):
            curr = messages[i]
            prev = result[-1]

            # Merge if the same role, ensuring 0 data loss
            if curr.get("role") == prev.get("role"):
                result[-1]["content"] = f"{prev.get('content', '')}\n\n{curr.get('content', '')}"
            else:
                result.append(curr.copy())

        return result

    def _layer4_autocompact(self, messages: List[Dict]) -> List[Dict]:
        """Auto-truncate when hitting token limits."""
        total_tokens = 0
        result = []

        for msg in messages:
            content = msg.get("content", "")
            tokens = len(content) * TOKENS_PER_CHAR

            if total_tokens + tokens > self.limit:
                # Truncate this message to fit
                remaining = self.limit - total_tokens
                chars_remaining = int(remaining / TOKENS_PER_CHAR)
                if chars_remaining > 50:  # Keep if meaningful
                    truncated_content = content[:chars_remaining] + "... [truncated]"
                    result.append({**msg, "content": truncated_content})
                break

            total_tokens += tokens
            result.append(msg)

        return result


class TokenCompactor:
    """Legacy wrapper - now uses 4-layer compressor."""

    def __init__(self, limit: int = 120000):
        self.limit = limit
        self.compressor = FourLayerCompressor(limit)

    def compact(self, messages: List[Dict]) -> List[Dict]:
        """[COMPACT]: 4-layer compression."""
        return self.compressor.compress(messages)

    def distill_to_anchor(self, messages: List[Dict]) -> str:
        """[DISTILL]: Summarizes old context into a dense Semantic Anchor."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        anchor = f"### 🔱 Semantic Anchor [{timestamp}]\n"
        for msg in messages:
            content_snippet = msg["content"][:200].replace("\n", " ")
            anchor += f"- **{msg['role'].upper()}**: {content_snippet}...\n"
        return anchor


class ContextManager:
    """Manages the sliding window and persistent Obsidian memory."""

    def __init__(self, vault_path: str):
        self.compactor = TokenCompactor()
        self.memory_file = os.path.join(vault_path, "🧠_LONG_TERM_MEMORY.md")
        self._ensure_memory_exists()

    def _ensure_memory_exists(self):
        if not os.path.exists(self.memory_file):
            with open(self.memory_file, "w", encoding="utf-8") as f:
                f.write("# 🧠 J.A.R.V.I.S. Long-term Semantic Memory\n\n")

    def persist_anchor(self, anchor_text: str):
        """[PERSIST]: Writes the semantic anchor to the Obsidian brain vault."""
        logger.info("💾 [MEM] Persisting Semantic Anchor to Obsidian...")
        with open(self.memory_file, "a", encoding="utf-8") as f:
            f.write(f"\n{anchor_text}\n---\n")

    def prepare_next_turn(self, history: List[Dict]) -> List[Dict]:
        """Orchestrates compaction and periodic persistence."""
        if len(history) > 20:
            # Distill middle history (5:15)
            archived = history[5:15]
            anchor = self.compactor.distill_to_anchor(archived)
            self.persist_anchor(anchor)

            # Rebuild with in-context anchor reference
            new_history = (
                history[:5]
                + [
                    {
                        "role": "system",
                        "content": f"REFERINȚĂ MEMORIE EXTERNĂ: {anchor}",
                    }
                ]
                + history[15:]
            )
            return self.compactor.compact(new_history)

        return self.compactor.compact(history)
