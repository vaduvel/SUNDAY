"""🕸️ JARVIS Knowledge Graph - Codebase Understanding
Inspired by GitNexus: Graph-based code intelligence that understands
dependencies, call chains, and execution flows.

Features:
- Zero-server: Runs in process (no external server needed)
- Knowledge Graph: Nodes for files, functions, classes, variables
- Graph RAG: Semantic search over code relationships
- MCP Server: Can serve as MCP tool for Cursor, Claude Code, Windsurf
"""

import os
import ast
import hashlib
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
import re
import json

logger = logging.getLogger(__name__)


@dataclass
class CodeNode:
    """A node in the code knowledge graph."""

    id: str
    name: str
    node_type: str  # file, function, class, method, variable, import
    file_path: str
    line_start: int = 0
    line_end: int = 0
    content: str = ""
    docstring: str = ""
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeEdge:
    """An edge in the code knowledge graph."""

    source_id: str
    target_id: str
    edge_type: str  # calls, imports, inherits, defines, uses
    metadata: Dict[str, Any] = field(default_factory=dict)


class CodeKnowledgeGraph:
    """Knowledge graph for code understanding."""

    RELATIONSHIP_EDGE_TYPES = {"calls", "uses", "imports", "inherits"}

    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self.nodes: Dict[str, CodeNode] = {}
        self.edges: List[CodeEdge] = []
        self.file_nodes: Dict[str, str] = {}
        self._index = defaultdict(list)

    def clear(self):
        """Reset the entire graph."""
        self.nodes.clear()
        self.edges.clear()
        self.file_nodes.clear()
        self._index.clear()

    def index_directory(
        self, extensions: List[str] = None, ignore_patterns: List[str] = None
    ):
        """Index entire directory tree."""
        extensions = extensions or [
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".java",
            ".go",
            ".rs",
        ]
        ignore_patterns = ignore_patterns or [
            "__pycache__",
            ".git",
            "node_modules",
            ".venv",
            "venv",
            "dist",
            "build",
        ]

        self.clear()

        for root, dirs, files in os.walk(self.root_path):
            dirs[:] = [d for d in dirs if d not in ignore_patterns]

            for file_name in files:
                if not any(file_name.endswith(ext) for ext in extensions):
                    continue
                file_path = os.path.join(root, file_name)
                try:
                    self.index_file(file_path, rebuild=False)
                except Exception as e:
                    logger.warning("Failed to index %s: %s", file_path, e)

        self._rebuild_relationship_edges()
        logger.info(
            "Indexed %s nodes from %s files", len(self.nodes), len(self.file_nodes)
        )

    def index_file(self, file_path: str, rebuild: bool = True):
        """Index a single file and extract code elements."""
        path = Path(file_path)
        if not path.is_absolute():
            path = (self.root_path / path).resolve()
        else:
            path = path.resolve()

        if not path.exists():
            return

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return

        normalized_path = str(path)
        self._remove_file_graph(normalized_path)

        file_id = self._get_file_node_id(normalized_path)
        file_node = CodeNode(
            id=file_id,
            name=path.name,
            node_type="file",
            file_path=normalized_path,
            content=content[:500],
            metadata={
                "relative_path": self._relative_path(normalized_path),
                "import_names": [],
            },
        )
        self.nodes[file_id] = file_node
        self.file_nodes[normalized_path] = file_id

        if path.suffix == ".py":
            self._parse_python(file_id, content, normalized_path)
        elif path.suffix in [".js", ".ts", ".jsx", ".tsx"]:
            self._parse_javascript(file_id, content, normalized_path)

        if rebuild:
            self._rebuild_relationship_edges()

    def _parse_python(self, file_id: str, content: str, file_path: str):
        """Parse Python file and extract symbols + relationships."""
        try:
            tree = ast.parse(content)
        except Exception:
            return

        file_node = self.nodes[file_id]
        file_node.metadata["import_names"] = self._collect_import_names(tree)

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                self._add_class(node, content, file_path, file_id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add_function(node, content, file_path, file_id)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_id = self._make_node_id(file_path, "variable", target.id)
                        var_node = CodeNode(
                            id=var_id,
                            name=target.id,
                            node_type="variable",
                            file_path=file_path,
                            line_start=node.lineno,
                            line_end=getattr(node, "end_lineno", node.lineno),
                            content=self._source_segment(content, node),
                        )
                        self.nodes[var_id] = var_node
                        self._add_edge(file_id, var_id, "contains")

    def _add_class(self, node: ast.ClassDef, content: str, file_path: str, file_id: str):
        """Add a class node and its methods."""
        node_id = self._make_node_id(file_path, "class", node.name)
        class_node = CodeNode(
            id=node_id,
            name=node.name,
            node_type="class",
            file_path=file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            content=self._source_segment(content, node),
            docstring=ast.get_docstring(node) or "",
            dependencies=self._collect_base_names(node),
            metadata={
                "full_name": node.name,
                "call_names": self._collect_call_names(node, current_class=node.name),
                "use_names": self._collect_used_names(node, current_class=node.name),
            },
        )
        self.nodes[node_id] = class_node
        self._add_edge(file_id, node_id, "contains")

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add_method(item, content, file_path, node.name, node_id)

    def _add_method(
        self,
        node: ast.FunctionDef,
        content: str,
        file_path: str,
        class_name: str,
        class_node_id: str,
    ):
        """Add a method node."""
        full_name = f"{class_name}.{node.name}"
        node_id = self._make_node_id(file_path, "method", full_name)
        method_node = CodeNode(
            id=node_id,
            name=node.name,
            node_type="method",
            file_path=file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            content=self._source_segment(content, node),
            docstring=ast.get_docstring(node) or "",
            metadata={
                "class": class_name,
                "full_name": full_name,
                "call_names": self._collect_call_names(node, current_class=class_name),
                "use_names": self._collect_used_names(node, current_class=class_name),
            },
        )
        self.nodes[node_id] = method_node
        self._add_edge(class_node_id, node_id, "contains")

    def _add_function(
        self,
        node: ast.FunctionDef,
        content: str,
        file_path: str,
        file_id: str,
    ):
        """Add a function node."""
        node_id = self._make_node_id(file_path, "function", node.name)
        func_node = CodeNode(
            id=node_id,
            name=node.name,
            node_type="function",
            file_path=file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            content=self._source_segment(content, node),
            docstring=ast.get_docstring(node) or "",
            metadata={
                "full_name": node.name,
                "call_names": self._collect_call_names(node),
                "use_names": self._collect_used_names(node),
            },
        )
        self.nodes[node_id] = func_node
        self._add_edge(file_id, node_id, "contains")

    def _parse_javascript(self, file_id: str, content: str, file_path: str):
        """Basic JavaScript/TypeScript parsing."""
        file_node = self.nodes[file_id]
        import_names = []

        func_pattern = re.compile(
            r"(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[^=])\s*=>)"
        )
        class_pattern = re.compile(r"class\s+(\w+)")
        import_pattern = re.compile(r"(?:import|require)\s*(?:.+?\sfrom\s*)?['\"]([^'\"]+)['\"]")

        for match in import_pattern.finditer(content):
            import_names.append(match.group(1))

        file_node.metadata["import_names"] = list(dict.fromkeys(import_names))

        for match in func_pattern.finditer(content):
            name = match.group(1) or match.group(2)
            if not name:
                continue
            line_start = content[: match.start()].count("\n") + 1
            snippet = content[match.start() : match.start() + 400]
            node_id = self._make_node_id(file_path, "function", name)
            func_node = CodeNode(
                id=node_id,
                name=name,
                node_type="function",
                file_path=file_path,
                line_start=line_start,
                content=snippet,
                metadata={
                    "full_name": name,
                    "call_names": self._collect_js_call_names(snippet),
                    "use_names": [],
                },
            )
            self.nodes[node_id] = func_node
            self._add_edge(file_id, node_id, "contains")

        for match in class_pattern.finditer(content):
            class_name = match.group(1)
            node_id = self._make_node_id(file_path, "class", class_name)
            line_start = content[: match.start()].count("\n") + 1
            class_node = CodeNode(
                id=node_id,
                name=class_name,
                node_type="class",
                file_path=file_path,
                line_start=line_start,
                content=content[match.start() : match.start() + 400],
                metadata={"full_name": class_name, "call_names": [], "use_names": []},
            )
            self.nodes[node_id] = class_node
            self._add_edge(file_id, node_id, "contains")

    def _make_node_id(self, file_path: str, node_type: str, name: str) -> str:
        return hashlib.md5(f"{file_path}:{node_type}:{name}".encode()).hexdigest()[:16]

    def _get_file_node_id(self, file_path: str) -> str:
        if file_path in self.file_nodes:
            return self.file_nodes[file_path]
        return self._make_node_id(file_path, "file", file_path)

    def _relative_path(self, file_path: str) -> str:
        try:
            return str(Path(file_path).resolve().relative_to(self.root_path))
        except Exception:
            return str(file_path)

    def _remove_file_graph(self, file_path: str):
        """Remove existing nodes/edges for a file before re-indexing it."""
        doomed_ids = {node_id for node_id, node in self.nodes.items() if node.file_path == file_path}
        if not doomed_ids:
            self.file_nodes.pop(file_path, None)
            return

        self.nodes = {
            node_id: node for node_id, node in self.nodes.items() if node_id not in doomed_ids
        }
        self.edges = [
            edge
            for edge in self.edges
            if edge.source_id not in doomed_ids and edge.target_id not in doomed_ids
        ]
        self.file_nodes.pop(file_path, None)

    def _add_edge(
        self, source_id: str, target_id: str, edge_type: str, metadata: Dict[str, Any] | None = None
    ):
        if source_id == target_id:
            return
        metadata = metadata or {}
        for edge in self.edges:
            if (
                edge.source_id == source_id
                and edge.target_id == target_id
                and edge.edge_type == edge_type
            ):
                return
        self.edges.append(CodeEdge(source_id, target_id, edge_type, metadata))

    def _source_segment(self, content: str, node: ast.AST) -> str:
        segment = ast.get_source_segment(content, node)
        if segment:
            return segment
        start = max(0, getattr(node, "lineno", 1) - 1)
        end = getattr(node, "end_lineno", start + 1)
        lines = content.splitlines()
        return "\n".join(lines[start:end])

    def _collect_import_names(self, tree: ast.AST) -> List[str]:
        import_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_names.append(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                for alias in node.names:
                    import_names.append(alias.asname or alias.name)
                    if module_name:
                        import_names.append(f"{module_name}.{alias.name}")
        return list(dict.fromkeys(import_names))

    def _collect_base_names(self, node: ast.ClassDef) -> List[str]:
        bases = []
        for base in node.bases:
            base_name = self._extract_python_name(base, current_class=node.name)
            if base_name:
                bases.append(base_name)
        return list(dict.fromkeys(bases))

    def _collect_call_names(self, node: ast.AST, current_class: str | None = None) -> List[str]:
        names = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = self._extract_python_name(child.func, current_class=current_class)
                if name:
                    names.append(name)
        return list(dict.fromkeys(names))

    def _collect_used_names(self, node: ast.AST, current_class: str | None = None) -> List[str]:
        names = []
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                if child.id not in {"self", "cls"}:
                    names.append(child.id)
            elif isinstance(child, ast.Attribute):
                attr_name = self._extract_python_name(child, current_class=current_class)
                if attr_name and attr_name != current_class:
                    names.append(attr_name)
        return list(dict.fromkeys(names))

    def _extract_python_name(self, node: ast.AST, current_class: str | None = None) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"} and current_class:
                return f"{current_class}.{node.attr}"
            return node.attr
        return None

    def _collect_js_call_names(self, snippet: str) -> List[str]:
        calls = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", snippet)
        excluded = {"if", "for", "while", "switch", "return", "function"}
        return [name for name in dict.fromkeys(calls) if name not in excluded]

    def _ensure_indexed(self):
        if not self.nodes:
            self.index_directory()

    def _lookup_file_node(self, symbol_name: str) -> Optional[CodeNode]:
        symbol_tail = symbol_name.split(".")[-1]
        normalized = symbol_tail.replace("-", "_")
        for file_path, file_id in self.file_nodes.items():
            path = Path(file_path)
            stem = path.stem.replace("-", "_")
            rel = self._relative_path(file_path).replace(os.sep, ".").replace("-", "_")
            if normalized in {stem, rel} or rel.endswith(f".{normalized}"):
                return self.nodes.get(file_id)
        return None

    def _lookup_symbol(self, name: str, file_path: str | None = None) -> Optional[CodeNode]:
        search_names = [name]
        if "." in name:
            search_names.append(name.split(".")[-1])

        normalized_file = self._normalize_path(file_path) if file_path else None

        # Prefer same-file matches
        for candidate_name in search_names:
            for node in self.nodes.values():
                full_name = node.metadata.get("full_name")
                if node.node_type == "file":
                    continue
                if normalized_file and node.file_path != normalized_file:
                    continue
                if candidate_name in {node.name, full_name}:
                    return node

        # Fallback to global exact/full-name matches
        for candidate_name in search_names:
            for node in self.nodes.values():
                full_name = node.metadata.get("full_name")
                if node.node_type == "file":
                    continue
                if candidate_name in {node.name, full_name}:
                    return node

        return None

    def _rebuild_relationship_edges(self):
        """Rebuild non-structural edges after indexing all symbols."""
        self.edges = [edge for edge in self.edges if edge.edge_type == "contains"]

        for node in list(self.nodes.values()):
            if node.node_type == "file":
                for import_name in node.metadata.get("import_names", []):
                    target = self._lookup_symbol(import_name) or self._lookup_file_node(import_name)
                    if target:
                        self._add_edge(node.id, target.id, "imports", {"symbol": import_name})
                continue

            if node.node_type == "class":
                for base_name in node.dependencies:
                    target = self._lookup_symbol(base_name, node.file_path) or self._lookup_symbol(base_name)
                    if target:
                        self._add_edge(node.id, target.id, "inherits", {"symbol": base_name})

            for call_name in node.metadata.get("call_names", []):
                target = self._lookup_symbol(call_name, node.file_path) or self._lookup_symbol(call_name)
                if target:
                    self._add_edge(node.id, target.id, "calls", {"symbol": call_name})

            for used_name in node.metadata.get("use_names", []):
                target = self._lookup_symbol(used_name, node.file_path) or self._lookup_symbol(used_name)
                if target:
                    self._add_edge(node.id, target.id, "uses", {"symbol": used_name})

    def _normalize_path(self, file_path: str | None) -> str | None:
        if not file_path:
            return None
        path = Path(file_path)
        if not path.is_absolute():
            path = self.root_path / path
        return str(path.resolve())

    def find_definition(self, name: str, file_path: str = None) -> Optional[CodeNode]:
        """Find definition of a name (function, class, variable)."""
        self._ensure_indexed()
        normalized_file = self._normalize_path(file_path)
        return self._lookup_symbol(name, normalized_file) or self._lookup_symbol(name)

    def find_references(self, node_id: str) -> List[CodeNode]:
        """Find where a symbol is referenced via semantic relationship edges."""
        self._ensure_indexed()
        references = []
        for edge in self.edges:
            if edge.target_id == node_id and edge.edge_type in self.RELATIONSHIP_EDGE_TYPES:
                source = self.nodes.get(edge.source_id)
                if source:
                    references.append(source)
        return references

    def find_callers(self, function_name: str) -> List[CodeNode]:
        """Find who calls a specific function or method."""
        self._ensure_indexed()
        target = self.find_definition(function_name)
        if not target:
            return []
        callers = []
        for edge in self.edges:
            if edge.target_id == target.id and edge.edge_type == "calls":
                source = self.nodes.get(edge.source_id)
                if source:
                    callers.append(source)
        return callers

    def get_call_chain(
        self, start_function: str, max_depth: int = 3
    ) -> List[List[str]]:
        """Get call chain from a function (who it calls)."""
        chains = []

        def traverse(node_id: str, depth: int, path: List[str]):
            if depth >= max_depth:
                chains.append(path)
                return

            node = self.nodes.get(node_id)
            if not node:
                return

            path = path + [node.name]

            # Find functions this function calls
            for edge in self.edges:
                if edge.source_id == node_id and edge.edge_type == "calls":
                    traverse(edge.target_id, depth + 1, path)

        start_node = self.find_definition(start_function)
        if start_node:
            traverse(start_node.id, 0, [])

        return chains

    def search(self, query: str, node_types: List[str] = None) -> List[CodeNode]:
        """Search nodes by name, docstring, or content."""
        self._ensure_indexed()
        results = []
        query_lower = query.lower()

        for node in self.nodes.values():
            if node_types and node.node_type not in node_types:
                continue

            # Search in name, docstring, content
            if (
                query_lower in node.name.lower()
                or query_lower in node.docstring.lower()
                or query_lower in node.content.lower()
            ):
                results.append(node)

        # Sort by relevance (simple: more matches = higher)
        results.sort(
            key=lambda n: (
                query_lower in n.name.lower()
                and 3
                or query_lower in n.docstring.lower()
                and 2
                or query_lower in n.content.lower()
                and 1
            ),
            reverse=True,
        )

        return results[:20]

    def get_file_dependencies(self, file_path: str) -> List[str]:
        """Get files that import or are imported by this file."""
        self._ensure_indexed()
        normalized = self._normalize_path(file_path)
        file_id = self.file_nodes.get(normalized or "")
        if not file_id:
            return []

        dependencies = []

        for edge in self.edges:
            if edge.source_id == file_id and edge.edge_type == "imports":
                target = self.nodes.get(edge.target_id)
                if target:
                    dependencies.append(target.file_path)

        return list(set(dependencies))

    def get_graph_stats(self) -> Dict[str, Any]:
        """Get statistics about the knowledge graph."""
        self._ensure_indexed()
        type_counts = defaultdict(int)
        for node in self.nodes.values():
            type_counts[node.node_type] += 1

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "files_indexed": len(self.file_nodes),
            "node_types": dict(type_counts),
        }

    # ═══════════════════════════════════════════════════════════
    #  GitNexus patterns: impact, detect_changes, symbol_context
    # ═══════════════════════════════════════════════════════════

    def impact(self, symbol_name: str) -> Dict[str, Any]:
        """Blast radius analysis: what breaks if this symbol changes?

        Returns direct + indirect dependents with confidence scoring.
        Inspired by GitNexus 'impact' MCP tool.
        """
        self._ensure_indexed()
        node = self.find_definition(symbol_name)
        if not node:
            return {"error": f"Symbol '{symbol_name}' not found in graph"}

        direct_refs = self.find_references(node.id)
        seen = {node.id} | {ref.id for ref in direct_refs}
        indirect: List[CodeNode] = []
        frontier = list(direct_refs)
        depth = 0

        while frontier and depth < 3:
            next_frontier = []
            for ref in frontier:
                for downstream in self.find_references(ref.id):
                    if downstream.id in seen:
                        continue
                    seen.add(downstream.id)
                    indirect.append(downstream)
                    next_frontier.append(downstream)
            frontier = next_frontier
            depth += 1

        affected_files = list({ref.file_path for ref in direct_refs + indirect})
        blast_radius = len(direct_refs) + len(indirect)
        relationship_edges = [
            edge for edge in self.edges if edge.edge_type in self.RELATIONSHIP_EDGE_TYPES
        ]
        confidence = min(
            0.98,
            0.35 + (len(relationship_edges) / max(1, len(self.nodes))) * 0.65,
        )

        return {
            "symbol": symbol_name,
            "type": node.node_type,
            "file": node.file_path,
            "line": node.line_start,
            "blast_radius_score": blast_radius,
            "confidence": round(confidence, 2),
            "direct_dependents": [
                {
                    "name": r.name,
                    "type": r.node_type,
                    "file": r.file_path,
                    "line": r.line_start,
                }
                for r in direct_refs[:15]
            ],
            "indirect_dependents": [
                {"name": r.name, "type": r.node_type, "file": r.file_path}
                for r in indirect[:15]
            ],
            "affected_files": affected_files[:20],
            "summary": (
                f"Changing '{symbol_name}' directly affects {len(direct_refs)} symbols "
                f"across {len(affected_files)} files "
                f"(+{len(indirect)} indirect). "
                f"Confidence: {round(confidence * 100)}%"
            ),
        }

    def detect_changes(self, changed_lines: Dict[str, List[int]]) -> Dict[str, Any]:
        """Map modified lines to affected symbols and downstream effects.

        Args:
            changed_lines: {file_path: [line_numbers_changed]}

        Inspired by GitNexus 'detect_changes' MCP tool.
        """
        self._ensure_indexed()
        directly_modified: List[CodeNode] = []
        normalized_map = {
            self._normalize_path(file_path): lines for file_path, lines in changed_lines.items()
        }

        for file_path, lines in normalized_map.items():
            for node in self.nodes.values():
                if node.file_path != file_path:
                    continue
                if node.node_type not in ("function", "method", "class"):
                    continue
                line_end = node.line_end or node.line_start + 1
                for line in lines:
                    if node.line_start <= line <= line_end:
                        directly_modified.append(node)
                        break

        # Downstream effects
        downstream: Dict[str, CodeNode] = {}
        for sym in directly_modified:
            for ref in self.find_references(sym.id):
                if ref.id not in {s.id for s in directly_modified}:
                    downstream[ref.id] = ref

        return {
            "changed_files": [path for path in normalized_map.keys() if path],
            "directly_modified_symbols": [
                {
                    "name": s.name,
                    "type": s.node_type,
                    "file": s.file_path,
                    "line": s.line_start,
                }
                for s in directly_modified[:20]
            ],
            "downstream_affected": [
                {"name": r.name, "type": r.node_type, "file": r.file_path}
                for r in list(downstream.values())[:20]
            ],
            "summary": (
                f"{len(directly_modified)} symbols directly modified, "
                f"{len(downstream)} downstream effects detected."
            ),
        }

    def get_symbol_context(self, symbol_name: str) -> Dict[str, Any]:
        """360-degree view of a symbol: definition + refs + callers + deps.

        Inspired by GitNexus 'context' MCP tool.
        """
        self._ensure_indexed()
        node = self.find_definition(symbol_name)
        if not node:
            return {"error": f"Symbol '{symbol_name}' not found"}

        references = self.find_references(node.id)
        callers = self.find_callers(symbol_name)

        return {
            "symbol": symbol_name,
            "type": node.node_type,
            "file": node.file_path,
            "line_start": node.line_start,
            "line_end": node.line_end,
            "docstring": node.docstring[:300] if node.docstring else "",
            "dependencies": node.dependencies[:10],
            "references_count": len(references),
            "references": [
                {"name": r.name, "file": r.file_path, "line": r.line_start}
                for r in references[:10]
            ],
            "callers": [
                {"name": c.name, "file": c.file_path}
                for c in callers[:10]
            ],
        }

    def to_json(self) -> str:
        """Export graph as JSON."""
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": n.id,
                        "name": n.name,
                        "type": n.node_type,
                        "file": n.file_path,
                        "line": n.line_start,
                        "doc": n.docstring[:200],
                    }
                    for n in self.nodes.values()
                ],
                "edges": [
                    {"source": e.source_id, "target": e.target_id, "type": e.edge_type}
                    for e in self.edges
                ],
            },
            indent=2,
        )


class GraphRAGAgent:
    """Graph RAG agent for code exploration."""

    def __init__(self, knowledge_graph: CodeKnowledgeGraph):
        self.graph = knowledge_graph
        self.context_history = []

    async def query(self, question: str) -> str:
        """Answer questions about the codebase."""
        self.context_history.append({"role": "user", "content": question})

        # Extract key entities from question
        entities = self._extract_entities(question)

        # Search graph for relevant nodes
        results = []
        for entity in entities:
            results.extend(self.graph.search(entity))

        if not results:
            return "I couldn't find relevant code for your question."

        # Build answer from results
        answer = self._build_answer(question, results)

        self.context_history.append({"role": "assistant", "content": answer})
        return answer

    def _extract_entities(self, text: str) -> List[str]:
        """Extract key entities from question."""
        # Simple extraction: function/class names
        entities = []

        # Look for quoted names
        import re

        quoted = re.findall(r'"([^"]+)"', text)
        entities.extend(quoted)

        # Look for "function X", "class Y" patterns
        for pattern in [r"function\s+(\w+)", r"class\s+(\w+)", r"method\s+(\w+)"]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities.extend(matches)

        # If no entities found, use whole question
        if not entities:
            entities = [text]

        return entities

    def _build_answer(self, question: str, results: List[CodeNode]) -> str:
        """Build answer from search results."""
        answer_parts = [f"Based on my analysis of the codebase:\n"]

        for node in results[:5]:
            location = f"{node.file_path}:{node.line_start}"
            answer_parts.append(f"**{node.name}** ({node.node_type}) at {location}")

            if node.docstring:
                answer_parts.append(f"  {node.docstring[:150]}")

            # Show relationships
            refs = self.graph.find_references(node.id)
            if refs:
                answer_parts.append(f"  Used by: {', '.join(r.name for r in refs[:3])}")

            answer_parts.append("")

        return "\n".join(answer_parts)


class KnowledgeGraphMCP:
    """MCP server for knowledge graph (GitNexus-style)."""

    def __init__(self, root_path: str, port: int = 8765):
        self.graph = CodeKnowledgeGraph(root_path)
        self.port = port

    def index_project(self, extensions: List[str] = None):
        """Index the project."""
        self.graph.index_directory(extensions)

    def get_tools(self) -> Dict[str, Any]:
        """Get MCP tool definitions."""
        return {
            "index_codebase": {
                "description": "Index the codebase to build knowledge graph",
                "parameters": {
                    "extensions": {"type": "array", "items": {"type": "string"}}
                },
            },
            "impact": {
                "description": "Analyze blast radius for a symbol change",
                "parameters": {"symbol_name": {"type": "string"}},
            },
            "find_definition": {
                "description": "Find definition of a function/class/variable",
                "parameters": {"name": {"type": "string"}, "file": {"type": "string"}},
            },
            "find_references": {
                "description": "Find where a symbol is used",
                "parameters": {"name": {"type": "string"}},
            },
            "search_code": {
                "description": "Search code by name/docstring",
                "parameters": {"query": {"type": "string"}, "types": {"type": "array"}},
            },
            "get_dependencies": {
                "description": "Get file dependencies",
                "parameters": {"file_path": {"type": "string"}},
            },
            "graph_stats": {
                "description": "Get knowledge graph statistics",
                "parameters": {},
            },
            "detect_changes": {
                "description": "Map changed lines to symbols and downstream effects",
                "parameters": {"changed_lines": {"type": "object"}},
            },
            "symbol_context": {
                "description": "Get rich context for a symbol",
                "parameters": {"symbol_name": {"type": "string"}},
            },
        }

    async def handle_tool(self, tool_name: str, params: Dict) -> Any:
        """Handle MCP tool call."""
        if tool_name == "index_codebase":
            self.graph.index_directory(params.get("extensions"))
            return {
                "indexed": len(self.graph.nodes),
                "files": len(self.graph.file_nodes),
            }

        elif tool_name == "impact":
            return self.graph.impact(params["symbol_name"])

        elif tool_name == "find_definition":
            node = self.graph.find_definition(params["name"], params.get("file"))
            if node:
                return {
                    "id": node.id,
                    "name": node.name,
                    "type": node.node_type,
                    "file": node.file_path,
                    "line": node.line_start,
                }
            return None

        elif tool_name == "find_references":
            def_node = self.graph.find_definition(params["name"])
            if def_node:
                refs = self.graph.find_references(def_node.id)
                return [
                    {
                        "name": r.name,
                        "type": r.node_type,
                        "file": r.file_path,
                        "line": r.line_start,
                    }
                    for r in refs
                ]
            return []

        elif tool_name == "search_code":
            results = self.graph.search(params["query"], params.get("types"))
            return [
                {
                    "name": r.name,
                    "type": r.node_type,
                    "file": r.file_path,
                    "line": r.line_start,
                }
                for r in results
            ]

        elif tool_name == "get_dependencies":
            return self.graph.get_file_dependencies(params["file_path"])

        elif tool_name == "graph_stats":
            return self.graph.get_graph_stats()

        elif tool_name == "detect_changes":
            return self.graph.detect_changes(params["changed_lines"])

        elif tool_name == "symbol_context":
            return self.graph.get_symbol_context(params["symbol_name"])

        return None


# Standalone usage
if __name__ == "__main__":
    # Example: Index current directory
    import sys

    if len(sys.argv) > 1:
        root = sys.argv[1]
    else:
        root = "."

    kg = CodeKnowledgeGraph(root)
    kg.index_directory()

    print(f"Graph stats: {kg.get_graph_stats()}")

    # Test search
    results = kg.search("function")
    print(f"Found {len(results)} matching nodes")
