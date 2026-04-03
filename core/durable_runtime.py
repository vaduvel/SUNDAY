"""🔄 LangGraph-style Durable Execution for JARVIS

Extends SessionRuntime with LangGraph patterns:
- Durable execution with checkpointing
- Resume capability (time-travel)
- Branching/forking sessions
- State management
"""

import os
import json
import uuid
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path

RUNTIME_DIR = ".jarvis/runtime"


class TaskState(Enum):
    """State of a task in the runtime."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"  # Waiting for input/approval
    PAUSED = "paused"  # Checkpointed, can resume
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Checkpoint:
    """A checkpoint of task state (LangGraph-style)."""

    id: str
    node_id: str
    state: Dict
    step: int
    created_at: str
    metadata: Dict = field(default_factory=dict)


@dataclass
class ExecutionNode:
    """A node in the execution DAG."""

    id: str
    name: str
    status: str
    input_state: Dict = field(default_factory=dict)
    output_state: Dict = field(default_factory=dict)
    result: Any = None
    error: str = None
    started_at: str = ""
    completed_at: str = ""


class DurableRuntime:
    """LangGraph-style durable execution runtime."""

    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        """Load sessions from disk."""
        sessions_file = os.path.join(RUNTIME_DIR, "durable_sessions.json")
        os.makedirs(RUNTIME_DIR, exist_ok=True)

        if os.path.exists(sessions_file):
            try:
                with open(sessions_file, "r") as f:
                    self.sessions = json.load(f)
            except:
                self.sessions = {}

    def _save(self):
        """Save sessions to disk."""
        sessions_file = os.path.join(RUNTIME_DIR, "durable_sessions.json")
        with open(sessions_file, "w") as f:
            json.dump(self.sessions, f, indent=2)

    def create_session(self, task: str, initial_state: Dict = None) -> str:
        """Create new execution session (like LangGraph new thread)."""
        session_id = f"task_{uuid.uuid4().hex[:8]}"

        self.sessions[session_id] = {
            "task": task,
            "state": initial_state or {},
            "nodes": {},
            "edges": [],
            "checkpoints": [],
            "current_node": None,
            "created_at": datetime.now().isoformat(),
            "status": "running",
        }

        self._save()
        return session_id

    def add_node(
        self, session_id: str, node_id: str, name: str, input_state: Dict = None
    ) -> bool:
        """Add a node to the execution DAG."""
        if session_id not in self.sessions:
            return False

        session = self.sessions[session_id]
        session["nodes"][node_id] = {
            "id": node_id,
            "name": name,
            "status": TaskState.PENDING.value,
            "input_state": input_state or {},
            "output_state": {},
            "result": None,
            "error": None,
            "started_at": datetime.now().isoformat(),
            "completed_at": "",
        }

        self._save()
        return True

    def add_edge(self, session_id: str, from_node: str, to_node: str) -> bool:
        """Add edge (like LangGraph.add_edge)."""
        if session_id not in self.sessions:
            return False

        self.sessions[session_id]["edges"].append({"from": from_node, "to": to_node})

        self._save()
        return True

    def execute_node(
        self, session_id: str, node_id: str, executor: Callable[[Dict], Any]
    ) -> Any:
        """Execute a node (like LangGraph node invocation)."""
        if (
            session_id not in self.sessions
            or node_id not in self.sessions[session_id]["nodes"]
        ):
            return None

        session = self.sessions[session_id]
        node = session["nodes"][node_id]

        # Update status
        node["status"] = TaskState.RUNNING.value
        self._save()

        try:
            # Execute with node's input state
            result = executor(node["input_state"])
            node["result"] = result
            node["output_state"] = {"result": str(result)[:100]}
            node["status"] = TaskState.COMPLETED.value
            node["completed_at"] = datetime.now().isoformat()

            # Create checkpoint
            self._create_checkpoint(session_id, node_id)

        except Exception as e:
            node["error"] = str(e)
            node["status"] = TaskState.FAILED.value
            node["completed_at"] = datetime.now().isoformat()

        self._save()
        return node.get("result")

    def _create_checkpoint(self, session_id: str, node_id: str):
        """Create checkpoint (LangGraph checkpoint mechanism)."""
        session = self.sessions[session_id]

        checkpoint = {
            "id": f"cp_{uuid.uuid4().hex[:8]}",
            "node_id": node_id,
            "state": session["state"].copy(),
            "step": len(session.get("checkpoints", [])),
            "created_at": datetime.now().isoformat(),
        }

        if "checkpoints" not in session:
            session["checkpoints"] = []

        session["checkpoints"].append(checkpoint)

        # Keep last 20
        session["checkpoints"] = session["checkpoints"][-20:]

    def pause(self, session_id: str) -> bool:
        """Pause execution (checkpoint and suspend)."""
        if session_id not in self.sessions:
            return False

        session = self.sessions[session_id]
        session["status"] = "paused"

        # Checkpoint current state
        if session.get("current_node"):
            self._create_checkpoint(session_id, session["current_node"])

        self._save()
        return True

    def resume(self, session_id: str, node_id: str = None) -> bool:
        """Resume paused session (like LangGraph resume)."""
        if session_id not in self.sessions:
            return False

        session = self.sessions[session_id]

        # Restore from latest checkpoint
        if session.get("checkpoints") and node_id is None:
            last_cp = session["checkpoints"][-1]
            session["state"] = last_cp["state"]

        # Resume node
        target = node_id or session.get("current_node")
        if target and target in session.get("nodes", {}):
            session["nodes"][target]["status"] = TaskState.RUNNING.value

        session["status"] = "running"
        self._save()
        return True

    def fork(self, session_id: str, reason: str = "exploration") -> str:
        """Fork session for parallel exploration (LangGraph branch)."""
        if session_id not in self.sessions:
            return None

        original = self.sessions[session_id]

        # Create fork
        fork_id = f"{session_id}_fork_{uuid.uuid4().hex[:4]}"

        self.sessions[fork_id] = {
            **json.loads(json.dumps(original)),
            "session_id": fork_id,
            "forked_from": session_id,
            "fork_reason": reason,
            "created_at": datetime.now().isoformat(),
            "status": "paused",
        }

        self._save()
        return fork_id

    def get_state(self, session_id: str) -> Optional[Dict]:
        """Get current state (LangGraph.get_state)."""
        return self.sessions.get(session_id, {}).get("state")

    def update_state(self, session_id: str, updates: Dict) -> bool:
        """Update state (LangGraph.update_state)."""
        if session_id not in self.sessions:
            return False

        self.sessions[session_id]["state"].update(updates)
        self._save()
        return True

    def get_next_nodes(self, session_id: str, completed_node: str) -> List[str]:
        """Get next nodes to execute (like LangGraph get_next_nodes)."""
        if session_id not in self.sessions:
            return []

        session = self.sessions[session_id]
        edges = session.get("edges", [])

        next_nodes = []
        for edge in edges:
            if edge.get("from") == completed_node:
                next_nodes.append(edge.get("to"))

        return next_nodes

    def get_status(self, session_id: str) -> Optional[Dict]:
        """Get session status."""
        if session_id not in self.sessions:
            return None

        session = self.sessions[session_id]
        return {
            "session_id": session_id,
            "task": session.get("task"),
            "status": session.get("status"),
            "current_node": session.get("current_node"),
            "nodes": len(session.get("nodes", {})),
            "checkpoints": len(session.get("checkpoints", [])),
        }

    def list_sessions(self) -> List[Dict]:
        """List all sessions."""
        return [self.get_status(sid) for sid in self.sessions.keys()]


# Singleton
_durable_runtime = None


def get_durable_runtime() -> DurableRuntime:
    global _durable_runtime
    if _durable_runtime is None:
        _durable_runtime = DurableRuntime()
    return _durable_runtime


# Test
if __name__ == "__main__":
    dr = get_durable_runtime()

    print("🔄 LangGraph-style Durable Runtime Test")
    print()

    # Create session
    sid = dr.create_session("Research AI agents", {"topic": "agent frameworks"})
    print(f"Created: {sid}")

    # Add nodes (like LangGraph graph)
    dr.add_node(sid, "analyze", "Analyze", {"phase": "analysis"})
    dr.add_node(sid, "search", "Search", {"phase": "search"})
    dr.add_node(sid, "report", "Report", {"phase": "report"})

    # Add edges
    dr.add_edge(sid, "analyze", "search")
    dr.add_edge(sid, "search", "report")

    print(f"Nodes: {list(dr.sessions[sid]['nodes'].keys())}")
    print(f"Edges: {dr.sessions[sid]['edges']}")

    # Execute
    def executor(state):
        print(f"  → Executing: {state}")
        return "done"

    dr.execute_node(sid, "analyze", executor)

    # Get next nodes
    next_nodes = dr.get_next_nodes(sid, "analyze")
    print(f"Next after 'analyze': {next_nodes}")

    # Fork
    fork_id = dr.fork(sid, "try_different_approach")
    print(f"Forked: {fork_id}")

    print()
    print("✅ Durable runtime ready!")
