"""J.A.R.V.I.S. (Obsidian Research Tool)

Permite JARVIS să cerceteze și să extragă informații dintr-un Vault Obsidian.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from core.runtime_config import resolve_obsidian_vault_path


class ObsidianResearcher:
    """Cercetează într-un Vault Obsidian pentru informații relevante."""

    def __init__(self, vault_path: str = None):
        self.vault_path = Path(vault_path) if vault_path else None
        self._notes_cache = {}

    def set_vault(self, vault_path: str) -> str:
        """Setează calea către Vault-ul Obsidian."""
        path = Path(vault_path)
        if not path.exists():
            return f"❌ Vault-ul nu există: {vault_path}"

        self.vault_path = path
        # Găsește fișierele .md
        md_files = list(path.rglob("*.md"))
        return f"✅ Vault setat: {path.name} ({len(md_files)} note găsite)"

    def search_notes(self, query: str, max_results: int = 5) -> str:
        """Caută în toate notele din Vault după un query."""
        if not self.vault_path:
            return "❌ Niciun Vault setat. Folosește set_vault(path) mai întâi."

        query_lower = query.lower()
        results = []

        # Parcurge toate fișierele .md
        for md_file in self.vault_path.rglob("*.md"):
            # Skip template files
            if "Templates" in str(md_file) or md_file.name.startswith("."):
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
                content_lower = content.lower()

                # Caută query în conținut
                if query_lower in content_lower:
                    # Extrage primele 200 chars relevante
                    idx = content_lower.find(query_lower)
                    snippet = content[max(0, idx - 50) : idx + 150].replace("\n", " ")

                    results.append(
                        {
                            "file": md_file.stem,
                            "path": md_file.relative_to(self.vault_path),
                            "snippet": snippet,
                        }
                    )
            except Exception:
                continue

        if not results:
            return f"🔍 Niciun rezultat pentru: '{query}'"

        # Formatează rezultatele
        output = f"🔍 Rezultate din Vault pentru: '{query}'\n"
        output += f"   Găsite: {len(results)} note\n\n"

        for r in results[:max_results]:
            output += f"📄 [[{r['file']}]]\n"
            output += f"   {r['snippet'][:100]}...\n\n"

        return output

    def get_note(self, note_name: str) -> str:
        """Citește o notă specifică după nume."""
        if not self.vault_path:
            return "❌ Niciun Vault setat."

        # Caută fișierul
        for md_file in self.vault_path.rglob(f"{note_name}.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                return f"# {note_name}\n\n{content}"
            except Exception as e:
                return f"❌ Eroare la citire: {e}"

        # Caută partial match
        for md_file in self.vault_path.rglob("*.md"):
            if note_name.lower() in md_file.stem.lower():
                try:
                    content = md_file.read_text(encoding="utf-8")
                    return f"# {md_file.stem}\n\n{content}"
                except:
                    continue

        return f"❌ Notă negăsită: {note_name}"

    def get_graph_links(self, note_name: str) -> Dict[str, List[str]]:
        """Extrage toate link-urile ([[...]]) dintr-o notă."""
        if not self.vault_path:
            return {"backlinks": [], "outlinks": []}

        for md_file in self.vault_path.rglob(f"{note_name}.md"):
            try:
                content = md_file.read_text(encoding="utf-8")

                # Găsește [[links]]
                outlinks = re.findall(r"\[\[([^\]]+)\]\]", content)

                # Găsește backlinks (note care linkuitează la asta)
                backlinks = []
                for other_file in self.vault_path.rglob("*.md"):
                    if other_file == md_file:
                        continue
                    try:
                        other_content = other_file.read_text(encoding="utf-8")
                        if f"[[{note_name}]]" in other_content:
                            backlinks.append(other_file.stem)
                    except:
                        continue

                return {"outlinks": outlinks, "backlinks": backlinks}
            except:
                return {"backlinks": [], "outlinks": []}

        return {"backlinks": [], "outlinks": []}

    def list_all_notes(self) -> str:
        """Listează toate notele din Vault."""
        if not self.vault_path:
            return "❌ Niciun Vault setat."

        notes = []
        for md_file in self.vault_path.rglob("*.md"):
            if "Templates" not in str(md_file) and not md_file.name.startswith("."):
                notes.append(md_file.stem)

        if not notes:
            return "Vault-ul este gol."

        output = f"📚 Note în Vault ({len(notes)}):\n"
        for note in sorted(notes)[:20]:
            output += f"  - [[{note}]]\n"

        if len(notes) > 20:
            output += f"  ... și încă {len(notes) - 20} note"

        return output

    def create_note(self, title: str, content: str, tags: List[str] = None) -> str:
        """Creează o notă nouă în Vault (cu format Obsidian)."""
        if not self.vault_path:
            return "❌ Niciun Vault setat."

        # Clean title for filename
        safe_title = title.replace(" ", "_").replace("/", "-")[:50]
        file_path = self.vault_path / f"{safe_title}.md"

        # Format Obsidian
        tag_line = "\n" + " ".join([f"#{t}" for t in (tags or [])]) if tags else ""

        md_content = f"""---
tags: {tags or []}
created: {datetime.now().isoformat()}
---

# {title}

{content}

---

*Creat de JARVIS*
{tag_line}
"""

        try:
            file_path.write_text(md_content, encoding="utf-8")
            return f"✅ Notă creată: [[{title}]]"
        except Exception as e:
            return f"❌ Eroare la creare: {e}"


# ═══════════════════════════════════════════════════════════════
#  CONFIGURARE DEFAULT
# ═══════════════════════════════════════════════════════════════

DEFAULT_VAULT_PATH = str(resolve_obsidian_vault_path())

_obsidian_researcher = None


def get_obsidian_researcher() -> ObsidianResearcher:
    global _obsidian_researcher
    if _obsidian_researcher is None:
        _obsidian_researcher = ObsidianResearcher()
        if Path(DEFAULT_VAULT_PATH).exists():
            _obsidian_researcher.set_vault(DEFAULT_VAULT_PATH)
    return _obsidian_researcher


def obsidian_search(query: str, vault_path: str = None) -> str:
    """Tool pentru search în Obsidian Vault."""
    researcher = get_obsidian_researcher()

    if vault_path:
        result = researcher.set_vault(vault_path)
        if result.startswith("❌"):
            return result

    return researcher.search_notes(query)


def obsidian_get_note(note_name: str) -> str:
    """Tool pentru a citi o notă specifică."""
    return get_obsidian_researcher().get_note(note_name)
