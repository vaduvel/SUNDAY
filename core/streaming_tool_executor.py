"""J.A.R.V.I.S. (GALAXY NUCLEUS - STREAMING TOOL EXECUTOR)

Claude Code's Speculative Execution Pattern:
- Tools start executing WHILE model is still streaming response
- Partition by safety: concurrent-safe tools run in parallel, serial tools wait
- Results yielded in submission order, not completion order
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ToolState(Enum):
    """Tool lifecycle states."""

    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"
    YIELDED = "yielded"
    FAILED = "failed"


class ToolSafety(Enum):
    """Concurrency safety classification."""

    SAFE = "safe"  # Can run in parallel
    UNSAFE = "unsafe"  # Must run serially
    UNKNOWN = "unknown"  # Default to serial


@dataclass
class TrackedTool:
    """A tool being tracked by the streaming executor."""

    id: str
    name: str
    input_data: Dict[str, Any]
    state: ToolState = ToolState.QUEUED
    safety: ToolSafety = ToolSafety.UNKNOWN
    result: Any = None
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    progress: List[str] = field(default_factory=list)
    context_modifier: Optional[callable] = None


# ═══════════════════════════════════════════════════════════════
#  TOOL SAFETY CLASSIFIERS
# ═══════════════════════════════════════════════════════════════


class ToolSafetyClassifier:
    """
    Classifies tools by concurrency safety.
    Claude Code pattern: safety is per-call, not per-tool-type.
    """

    # Always safe tools
    ALWAYS_SAFE = {
        "file_read",
        "duck_duck_go_search",
        "obsidian_search",
        "obsidian_read_note",
        "memory_summary",
        "search_memory",
        "compact_context",
    }

    # Always unsafe tools
    ALWAYS_UNSAFE = {"file_write", "save_lesson", "spawn_subagent_task"}

    # Command-based safety for execute_command
    READ_COMMANDS = {
        "ls",
        "cat",
        "grep",
        "rg",
        "find",
        "git status",
        "git diff",
        "git log",
        "head",
        "tail",
        "wc",
        "stat",
        "du",
        "df",
        "echo",
        "pwd",
        "which",
        "whereis",
        "file",
        "type",
    }

    WRITE_COMMANDS = {
        "rm",
        "rmdir",
        "mkdir",
        "touch",
        "chmod",
        "chown",
        "cp",
        "mv",
        "ln",
        "sed",
        "awk",
        "dd",
        "tar",
        "gzip",
        "pip install",
        "npm install",
        "apt-get install",
        "curl",
        "wget",
        "git push",
        "git commit",
    }

    @classmethod
    def classify(cls, tool_name: str, tool_input: Dict = None) -> ToolSafety:
        """Classify a tool call by concurrency safety."""

        # Known safe
        if tool_name in cls.ALWAYS_SAFE:
            return ToolSafety.SAFE

        # Known unsafe
        if tool_name in cls.ALWAYS_UNSAFE:
            return ToolSafety.UNSAFE

        # Check execute_command specifically
        if tool_name == "execute_command" and tool_input:
            command = tool_input.get("command", "")
            return cls._classify_bash_command(command)

        # Unknown defaults to unsafe (fail-closed)
        return ToolSafety.UNSAFE

    @classmethod
    def _classify_bash_command(cls, command: str) -> ToolSafety:
        """Classify a bash command by safety."""
        if not command:
            return ToolSafety.UNSAFE

        # Split compound commands
        parts = (
            command.replace("&&", "|").replace("||", "|").replace(";", "|").split("|")
        )

        for part in parts:
            part = part.strip().split()[0] if part.strip() else ""

            # Any write command makes entire compound unsafe
            if part in cls.WRITE_COMMANDS:
                return ToolSafety.UNSAFE

        # All parts are read-only
        return ToolSafety.SAFE


# ═══════════════════════════════════════════════════════════════
#  STREAMING TOOL EXECUTOR
# ═══════════════════════════════════════════════════════════════


class StreamingToolExecutor:
    """
    Claude Code's Streaming Tool Executor:
    - Starts tools WHILE model is still streaming response
    - Partitions into concurrent and serial batches
    - Yields results in submission order
    """

    def __init__(self, max_concurrency: int = 10):
        self.max_concurrency = max_concurrency
        self.tools: List[TrackedTool] = []
        self.executing_count = 0
        self._abort_controller = None
        self._sibling_error = None
        self.queue: asyncio.Queue = asyncio.Queue()

    def add_tool(self, tool_id: str, tool_name: str, tool_input: Dict) -> None:
        """Add a tool during streaming - may start immediately."""
        safety = ToolSafetyClassifier.classify(tool_name, tool_input)

        tool = TrackedTool(
            id=tool_id, name=tool_name, input_data=tool_input, safety=safety
        )
        self.tools.append(tool)

        # Try to start immediately if safe
        if safety == ToolSafety.SAFE and self.executing_count < self.max_concurrency:
            asyncio.create_task(self._execute_tool(tool))
        elif safety == ToolSafety.UNSAFE:
            logger.info(f"🔒 [TOOL] {tool_name} marked serial (waits)")

    async def _execute_tool(self, tool: TrackedTool) -> None:
        """Execute a single tool."""
        if tool.state != ToolState.QUEUED:
            return

        tool.state = ToolState.EXECUTING
        tool.start_time = time.time()
        self.executing_count += 1

        logger.info(
            f"⚡ [TOOL] Starting {tool.name} (concurrent: {tool.safety == ToolSafety.SAFE})"
        )

        try:
            # Execute based on tool type
            result = await self._run_tool_impl(tool.name, tool.input_data)
            tool.result = result
            tool.state = ToolState.COMPLETED

        except Exception as e:
            tool.error = str(e)
            tool.state = ToolState.FAILED
            logger.error(f"❌ [TOOL] {tool.name} failed: {e}")

            # Bash errors cascade to siblings
            if tool.name == "execute_command":
                self._sibling_error = tool
                # Cancel siblings
                for t in self.tools:
                    if t.state == ToolState.EXECUTING and t.id != tool.id:
                        t.error = f"Cancelled: {tool.name} errored"
                        t.state = ToolState.FAILED

        finally:
            tool.end_time = time.time()
            self.executing_count -= 1

            # Process queue - may start waiting serial tools
            await self._process_queue()

    async def _run_tool_impl(self, tool_name: str, tool_input: Dict) -> str:
        """Run the actual tool implementation."""
        # Import tools from orchestrator
        from core.orchestrator import (
            duckduckgo_tool,
            obsidian_search_tool,
            obsidian_read_note_tool,
            file_read_tool,
            file_write_tool,
            execute_command_tool,
            memory_summary_tool,
            search_memory_tool,
        )

        tool_map = {
            "duck_duck_go_search": duckduckgo_tool,
            "obsidian_search": obsidian_search_tool,
            "obsidian_read_note": obsidian_read_note_tool,
            "file_read": file_read_tool,
            "file_write": file_write_tool,
            "execute_command": execute_command_tool,
            "memory_summary": memory_summary_tool,
            "search_memory": search_memory_tool,
        }

        tool_func = tool_map.get(tool_name)
        if not tool_func:
            return f"❌ Unknown tool: {tool_name}"

        # Extract args based on tool
        if tool_name == "duck_duck_go_search":
            return tool_func(query=tool_input.get("query", ""))
        elif tool_name == "obsidian_search":
            return tool_func(query=tool_input.get("query", ""))
        elif tool_name == "obsidian_read_note":
            return tool_func(note_name=tool_input.get("note_name", ""))
        elif tool_name == "file_read":
            return tool_func(path=tool_input.get("path", ""))
        elif tool_name == "file_write":
            return tool_func(
                path=tool_input.get("path", ""), content=tool_input.get("content", "")
            )
        elif tool_name == "execute_command":
            return tool_func(command=tool_input.get("command", ""))
        else:
            return tool_func()

    async def _process_queue(self) -> None:
        """Check if new tools can start."""
        for tool in self.tools:
            if tool.state == ToolState.QUEUED:
                if (
                    tool.safety == ToolSafety.SAFE
                    and self.executing_count < self.max_concurrency
                ):
                    asyncio.create_task(self._execute_tool(tool))
                elif tool.safety == ToolSafety.UNSAFE and self.executing_count == 0:
                    asyncio.create_task(self._execute_tool(tool))

    def get_completed_results(self) -> List[Dict]:
        """
        Get completed results in SUBMISSION ORDER (not completion order).
        Critical: results must match the order model requested them.
        """
        results = []

        for tool in self.tools:
            # Drain progress first
            if tool.progress:
                results.append(
                    {"type": "progress", "tool": tool.name, "messages": tool.progress}
                )

            # Yield completed in order
            if tool.state in [ToolState.COMPLETED, ToolState.FAILED]:
                if tool.state == ToolState.COMPLETED:
                    results.append(
                        {
                            "type": "result",
                            "tool": tool.id,
                            "tool_name": tool.name,
                            "content": tool.result,
                            "success": True,
                        }
                    )
                else:
                    results.append(
                        {
                            "type": "result",
                            "tool": tool.id,
                            "tool_name": tool.name,
                            "content": tool.error,
                            "success": False,
                        }
                    )
                tool.state = ToolState.YIELDED

                # Stop at first serial tool still executing
                if tool.safety == ToolSafety.UNSAFE:
                    break

        return results

    async def get_remaining_results(self) -> AsyncGenerator[Dict, None]:
        """Drain remaining results after streaming completes."""
        # Wait for all to complete
        while self.executing_count > 0:
            await asyncio.sleep(0.1)

        # Yield remaining in order
        for tool in self.tools:
            if tool.state == ToolState.COMPLETED:
                yield {
                    "type": "result",
                    "tool": tool.id,
                    "tool_name": tool.name,
                    "content": tool.result,
                    "success": True,
                }
            elif tool.state == ToolState.FAILED:
                yield {
                    "type": "result",
                    "tool": tool.id,
                    "tool_name": tool.name,
                    "content": tool.error,
                    "success": False,
                }

    def get_status(self) -> Dict:
        """Get executor status."""
        return {
            "total_tools": len(self.tools),
            "executing": self.executing_count,
            "completed": sum(1 for t in self.tools if t.state == ToolState.COMPLETED),
            "queued": sum(1 for t in self.tools if t.state == ToolState.QUEUED),
            "failed": sum(1 for t in self.tools if t.state == ToolState.FAILED),
        }


# ═══════════════════════════════════════════════════════════════
#  TOOL PARTITIONING ALGORITHM
# ═══════════════════════════════════════════════════════════════


def partition_tool_calls(tool_calls: List[Dict]) -> List[List[Dict]]:
    """
    Partition tool calls into batches.
    Consecutive safe tools go together, unsafe tools are isolated.

    Example: [Read, Read, Grep, Edit, Read]
    Result: [[Read, Read, Grep], [Edit], [Read]]
    """
    batches = []
    current_batch = []

    for call in tool_calls:
        tool_name = call.get("name", "")
        safety = ToolSafetyClassifier.classify(tool_name, call.get("input", {}))

        if safety == ToolSafety.SAFE:
            current_batch.append(call)
        else:
            # Flush current batch if has items
            if current_batch:
                batches.append(current_batch)
                current_batch = []
            # Add unsafe as separate batch
            batches.append([call])

    # Flush remaining
    if current_batch:
        batches.append(current_batch)

    return batches


# ═══════════════════════════════════════════════════════════════
#  INTERRUPT BEHAVIOR
# ═══════════════════════════════════════════════════════════════


class InterruptBehavior:
    """
    Defines what happens when user interrupts during tool execution.
    - 'cancel': Stop immediately, discard partial results
    - 'block': Keep running, new message waits
    """

    @staticmethod
    def get_for_tool(tool_name: str) -> str:
        """Get interrupt behavior for a tool."""
        # Read-only tools can be cancelled
        safe_cancel = {
            "file_read",
            "duck_duck_go_search",
            "obsidian_search",
            "memory_summary",
            "search_memory",
        }

        if tool_name in safe_cancel:
            return "cancel"

        # Writes must complete
        return "block"


# ═══════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════

__all__ = [
    "StreamingToolExecutor",
    "ToolSafetyClassifier",
    "ToolSafety",
    "TrackedTool",
    "partition_tool_calls",
    "InterruptBehavior",
    "ToolState",
]
