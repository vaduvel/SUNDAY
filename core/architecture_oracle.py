"""J.A.R.V.I.S. (GALAXY NUCLEUS - ARCHITECTURE ORACLE)

High-fidelity symbol tracking and Blast Radius analysis using Tree-sitter AST.
"""

import os
import logging
from typing import List, Optional

try:
    import tree_sitter_python as tspython
    import tree_sitter_typescript as ts_typescript
    from tree_sitter import Language, Parser

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False
    tspython = None
    ts_typescript = None
    Language = None
    Parser = None

logger = logging.getLogger(__name__)


class SymbolOracle:
    """Uses Tree-sitter to index the graph of symbols and their dependencies."""

    def __init__(self, project_root: str):
        self.root = project_root
        self.symbol_map = {}  # path -> {definitions: [], references: []}

        if HAS_TREE_SITTER:
            self.languages = {
                "py": Language(tspython.language()),
                "ts": Language(ts_typescript.language_typescript()),
                "tsx": Language(ts_typescript.language_tsx()),
            }
            self.parsers = {ext: Parser(lang) for ext, lang in self.languages.items()}
        else:
            self.languages = {}
            self.parsers = {}
            logger.warning(
                "⚠️ [ORACLE] Tree-sitter not installed. AST features disabled."
            )

    def index_file(self, path: str):
        """Builds an AST for the file and extracts symbols."""
        if not HAS_TREE_SITTER or not self.parsers:
            logger.debug(f"⚠️ [ORACLE] Skipping {path} - tree-sitter not available")
            return

        ext = path.split(".")[-1]
        parser = self.parsers.get(ext)
        if not parser:
            return
        if not parser:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                tree = parser.parse(bytes(content, "utf8"))

                # Simplified symbol extraction logic
                defs = self._extract_definitions(tree.root_node)
                refs = self._extract_references(tree.root_node)

                self.symbol_map[path] = {"definitions": defs, "references": refs}
        except Exception as e:
            logger.error(f"❌ [ORACLE] Error indexing {path}: {str(e)}")

    def _extract_definitions(self, node) -> List[str]:
        """Recursive definition extraction (classes/functions)."""
        defs = []
        # node types: class_definition, function_definition, method_definition
        if node.type in [
            "class_definition",
            "function_definition",
            "method_definition",
        ]:
            name_node = node.child_by_field_name("name")
            if name_node:
                defs.append(name_node.text.decode("utf8"))

        for child in node.children:
            defs.extend(self._extract_definitions(child))
        return defs

    def _extract_references(self, node) -> List[str]:
        """Recursive call/reference extraction."""
        refs = []
        # node types: call, attribute, identifier
        if node.type == "call":
            function_node = node.child_by_field_name("function")
            if function_node:
                refs.append(function_node.text.decode("utf8"))

        for child in node.children:
            refs.extend(self._extract_references(child))
        return refs

    def calculate_blast_radius(self, modified_file: str) -> List[str]:
        """Identifies files that might break based on the modified file's definitions."""
        if modified_file not in self.symbol_map:
            return []

        impacted_files = set()
        my_defs = set(self.symbol_map[modified_file]["definitions"])

        for other_path, data in self.symbol_map.items():
            if other_path == modified_file:
                continue

            # Intersection of my definitions and their references
            other_refs = set(data["references"])
            overlap = my_defs.intersection(other_refs)

            if overlap:
                impacted_files.add(other_path)

        return list(impacted_files)


# ═══════════════════════════════════════════════════════════════
#  INTEGRATION TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    oracle = SymbolOracle(project_root=".")
    # (Simulated indexing for testing)
    test_path = "core/jarvis_engine.py"
    oracle.index_file(test_path)
    print(f"📡 [ORACLE] Symbols in {test_path}: {oracle.symbol_map.get(test_path)}")
