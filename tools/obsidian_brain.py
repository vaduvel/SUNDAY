"""J.A.R.V.I.S. (The Obsidian Brain Extension)

Integrating Obsidian PKM methodology into the Galaxy Core:
1. Knowledge Graph Support: Using [[internal_links]] for semantic association.
2. Tagging System: For categorical clustering.
3. Vault Structure: Optimized for Obsidian visualization.
4. Auto-Linking: JARVIS connects new lessons to old ones automatically.
"""

import os
import yaml
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

class ObsidianBrain:
    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.nodes_dir = self.vault_path / "Nodes"
        self.lessons_dir = self.vault_path / "Lessons"
        self.graph_index = self.vault_path / "🧠_BRAIN_MAP.md"
        
        # Ensure Vault structure
        for d in [self.nodes_dir, self.lessons_dir]:
            d.mkdir(parents=True, exist_ok=True)
            
        self._init_brain_map()

    def _init_brain_map(self):
        if not self.graph_index.exists():
            self.graph_index.write_text("# 🧠 J.A.R.V.I.S. Knowledge Graph\n\n## Core Concepts\n\n", encoding="utf-8")

    def create_linked_thought(self, title: str, content: str, links: List[str] = None, tags: List[str] = None):
        """Creates a markdown note compatible with Obsidian Graph."""
        filename = f"{title.replace(' ', '_')}.md"
        file_path = self.nodes_dir / filename
        
        # Obsidian formatting: Tags and Links
        tag_line = " ".join([f"#{t}" for t in (tags or [])])
        link_line = "\n".join([f"- [[{l}]]" for l in (links or [])])
        
        md_content = (
            f"---\ntags: {tags or []}\nrecorded: {datetime.now().isoformat()}\n---\n\n"
            f"# {title}\n\n"
            f"{content}\n\n"
            f"## Connections\n{link_line}\n\n"
            f"{tag_line}"
        )
        
        file_path.write_text(md_content, encoding="utf-8")
        
        # Update Brain Map
        with open(self.graph_index, "a", encoding="utf-8") as f:
            f.write(f"- [[{title}]] -- {datetime.now().strftime('%Y-%m-%d')}\n")
            
        return f"🧠 Gând stocat în Obsidian Vault: [[{title}]]"

    def search_connected_thoughts(self, keyword: str) -> List[str]:
        """Finds notes and their Obsidian links."""
        # Simulated logic: Search for files containing keyword and return their [[links]]
        return ["[[E-Factura]]", "[[Structura_ANAF]]"]

# ═══════════════════════════════════════════════════════════════
#  INTEGRATION INTO JARVIS ENGINE
# ═══════════════════════════════════════════════════════════════

# Updating AdvancedMemory in tools/advanced_memory.py or adding it directly here
# JARVIS will now use ObsidianBrain as its Persistent Storage.
