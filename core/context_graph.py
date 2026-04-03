"""World-state context graph for J.A.R.V.I.S."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

CONTEXT_FILE = ".jarvis/context_graph.json"


@dataclass
class ContextNode:
    """A node in the context graph."""

    id: str
    name: str
    node_type: str
    weight: float
    last_mentioned: str
    connections: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextEdge:
    """A typed relationship between two context nodes."""

    source: str
    target: str
    edge_type: str
    weight: float = 1.0
    last_observed: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}|{self.edge_type}|{self.target}"


@dataclass
class ActiveContext:
    """Current active context."""

    app: str = "unknown"
    task: str = ""
    topic: str = ""
    entities: List[str] = field(default_factory=list)
    started_at: str = ""
    active_goal: str = ""
    open_window_app: str = ""
    open_window_title: str = ""
    last_tool: str = ""
    last_failure: str = ""


class ContextGraph:
    """Graph-based world-state tracking."""

    def __init__(self, context_file: str = CONTEXT_FILE):
        self.context_file = context_file
        self.nodes: Dict[str, ContextNode] = {}
        self.edges: Dict[str, ContextEdge] = {}
        self.active = ActiveContext()
        self.context_history: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.context_file):
            return

        with open(self.context_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        for node in data.get("nodes", []):
            self.nodes[node["id"]] = ContextNode(
                id=node["id"],
                name=node["name"],
                node_type=node["node_type"],
                weight=node.get("weight", 50.0),
                last_mentioned=node.get("last_mentioned", datetime.now().isoformat()),
                connections=list(node.get("connections", [])),
                metadata=dict(node.get("metadata", {})),
            )

        for edge in data.get("edges", []):
            item = ContextEdge(
                source=edge["source"],
                target=edge["target"],
                edge_type=edge["edge_type"],
                weight=edge.get("weight", 1.0),
                last_observed=edge.get("last_observed", datetime.now().isoformat()),
                metadata=dict(edge.get("metadata", {})),
            )
            self.edges[item.key] = item

        if not self.edges:
            for node in self.nodes.values():
                for connection in node.connections:
                    self._connect(node.id, connection, "related")

        active = data.get("active", {})
        self.active = ActiveContext(
            app=active.get("app", "unknown"),
            task=active.get("task", ""),
            topic=active.get("topic", ""),
            entities=list(active.get("entities", [])),
            started_at=active.get("started_at", ""),
            active_goal=active.get("active_goal", ""),
            open_window_app=active.get("open_window_app", ""),
            open_window_title=active.get("open_window_title", ""),
            last_tool=active.get("last_tool", ""),
            last_failure=active.get("last_failure", ""),
        )
        self.context_history = list(data.get("context_history", []))

    def _save(self) -> None:
        directory = os.path.dirname(self.context_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.context_file, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "nodes": [asdict(node) for node in self.nodes.values()],
                    "edges": [asdict(edge) for edge in self.edges.values()],
                    "active": asdict(self.active),
                    "context_history": self.context_history[-100:],
                    "last_updated": datetime.now().isoformat(),
                },
                handle,
                indent=2,
            )

    def update_app(self, app_name: str) -> None:
        if self.active.app != app_name and self.active.app != "unknown":
            self.context_history.append(
                {
                    "app": self.active.app,
                    "task": self.active.task,
                    "goal": self.active.active_goal,
                    "ended_at": datetime.now().isoformat(),
                }
            )

        self.active.app = app_name
        self.active.started_at = datetime.now().isoformat()
        app_id = self._add_node(app_name, "app")

        if self.active.task:
            self._connect(app_id, self._add_node(self.active.task, "task"), "active_in")
        if self.active.active_goal:
            self._connect(
                app_id,
                self._add_node(self.active.active_goal, "active_goal"),
                "supports_goal",
            )
        self._save()

    def update_task(self, task: str) -> None:
        self.active.task = task
        task_id = self._add_node(task, "task")
        if self.active.app != "unknown":
            self._connect(task_id, self._add_node(self.active.app, "app"), "active_in")
        if self.active.active_goal:
            self._connect(
                task_id,
                self._add_node(self.active.active_goal, "active_goal"),
                "implements_goal",
            )
        self._save()

    def update_topic(self, topic: str) -> None:
        self.active.topic = topic
        topic_id = self._add_node(topic, "topic")
        if self.active.task:
            self._connect(topic_id, self._add_node(self.active.task, "task"), "topic_of")
        self._save()

    def add_entity(self, entity: str) -> None:
        if entity not in self.active.entities:
            self.active.entities.append(entity)
        entity_id = self._add_node(entity, "entity")
        if self.active.topic:
            self._connect(entity_id, self._add_node(self.active.topic, "topic"), "mentioned_in")
        if self.active.task:
            self._connect(entity_id, self._add_node(self.active.task, "task"), "mentioned_in")
        self._save()

    def set_active_goal(self, goal: str) -> None:
        self.active.active_goal = goal
        goal_id = self._add_node(goal, "active_goal")
        if self.active.task:
            self._connect(goal_id, self._add_node(self.active.task, "task"), "drives")
        if self.active.app != "unknown":
            self._connect(goal_id, self._add_node(self.active.app, "app"), "active_in")
        self._save()

    def set_active_window(self, app_name: str, title: str) -> None:
        self.active.open_window_app = app_name
        self.active.open_window_title = title
        window_id = self._add_node(title, "open_window", metadata={"app_name": app_name})
        app_id = self._add_node(app_name, "app")
        self._connect(window_id, app_id, "window_of")
        if self.active.active_goal:
            self._connect(
                window_id,
                self._add_node(self.active.active_goal, "active_goal"),
                "focused_for",
            )
        self._save()

    def record_tool_edge(self, tool: str, result: str) -> None:
        self.active.last_tool = tool
        tool_id = self._add_node(tool, "tool", metadata={"last_result": result})
        if self.active.task:
            self._connect(tool_id, self._add_node(self.active.task, "task"), "used_for")
        if self.active.active_goal:
            self._connect(
                tool_id,
                self._add_node(self.active.active_goal, "active_goal"),
                "supports_goal",
            )
        self._save()

    def record_failure_edge(self, step_id: str, code: str) -> None:
        self.active.last_failure = code
        step_node = self._add_node(step_id, "step")
        failure_node = self._add_node(code, "failure")
        self._connect(step_node, failure_node, "failed_with")
        if self.active.task:
            self._connect(failure_node, self._add_node(self.active.task, "task"), "blocks")
        if self.active.active_goal:
            self._connect(
                failure_node,
                self._add_node(self.active.active_goal, "active_goal"),
                "risks_goal",
            )
        self._save()

    def record_website(self, url: str, title: str = "") -> None:
        website_id = self._add_node(url, "website", metadata={"title": title})
        if self.active.task:
            self._connect(website_id, self._add_node(self.active.task, "task"), "researched_for")
        self._save()

    def get_related(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        results = []
        for node in self.nodes.values():
            if query_lower not in node.name.lower():
                continue
            edges = [
                edge
                for edge in self.edges.values()
                if edge.source == node.id or edge.target == node.id
            ]
            results.append(
                {
                    "name": node.name,
                    "type": node.node_type,
                    "weight": node.weight,
                    "connections": len(edges),
                }
            )

        results.sort(key=lambda item: (item["weight"], item["connections"]), reverse=True)
        return results[:limit]

    def get_current_context(self) -> Dict[str, Any]:
        return {
            "app": self.active.app,
            "task": self.active.task,
            "topic": self.active.topic,
            "entities": list(self.active.entities),
            "started_at": self.active.started_at,
            "active_goal": self.active.active_goal,
            "active_window": {
                "app": self.active.open_window_app,
                "title": self.active.open_window_title,
            },
            "last_tool": self.active.last_tool,
            "last_failure": self.active.last_failure,
        }

    def get_world_state(self) -> Dict[str, Any]:
        recent_failures = [
            node.name
            for node in self.nodes.values()
            if node.node_type == "failure"
        ][-5:]
        recent_tools = [
            node.name
            for node in self.nodes.values()
            if node.node_type == "tool"
        ][-5:]
        return {
            "active_goal": self.active.active_goal,
            "active_window": {
                "app": self.active.open_window_app,
                "title": self.active.open_window_title,
            },
            "recent_failures": recent_failures,
            "recent_tools": recent_tools,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }

    def get_status(self) -> Dict[str, Any]:
        node_types: Dict[str, int] = defaultdict(int)
        for node in self.nodes.values():
            node_types[node.node_type] += 1

        return {
            "active": True,
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "node_types": dict(node_types),
            "current_context": self.get_current_context(),
            "world_state": self.get_world_state(),
            "history_entries": len(self.context_history),
        }

    def _add_node(
        self, name: str, node_type: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        node_id = f"{node_type}_{name.lower().replace(' ', '_')[:48]}"
        now = datetime.now().isoformat()
        if node_id not in self.nodes:
            self.nodes[node_id] = ContextNode(
                id=node_id,
                name=name,
                node_type=node_type,
                weight=50.0,
                last_mentioned=now,
                metadata=dict(metadata or {}),
            )
        node = self.nodes[node_id]
        node.last_mentioned = now
        node.weight = min(100.0, node.weight + 5.0)
        if metadata:
            node.metadata.update(metadata)
        return node_id

    def _connect(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if source_id not in self.nodes or target_id not in self.nodes:
            return
        edge = ContextEdge(
            source=source_id,
            target=target_id,
            edge_type=edge_type,
            metadata=dict(metadata or {}),
        )
        current = self.edges.get(edge.key)
        if current:
            current.weight += 1.0
            current.last_observed = datetime.now().isoformat()
            current.metadata.update(metadata or {})
        else:
            self.edges[edge.key] = edge

        if target_id not in self.nodes[source_id].connections:
            self.nodes[source_id].connections.append(target_id)
        if source_id not in self.nodes[target_id].connections:
            self.nodes[target_id].connections.append(source_id)


_context_graph: ContextGraph | None = None


def get_context_graph() -> ContextGraph:
    global _context_graph
    if _context_graph is None:
        _context_graph = ContextGraph()
    return _context_graph


if __name__ == "__main__":
    graph = get_context_graph()
    graph.update_app("terminal")
    graph.update_task("inspect blueprint")
    graph.set_active_goal("continue document implementation")
    graph.record_tool_edge("rg", "success")
    print(graph.get_status())
