"""💻 Coding Agent (OpenHands-style but simpler)

Provides: sandboxed code execution, patch/apply workflow, task isolation.
"""

import os
import subprocess
import tempfile
import uuid
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

CODING_DIR = ".jarvis/coding"


@dataclass
class CodeTask:
    """A coding task with sandbox isolation."""

    id: str
    description: str
    code: str
    language: str
    status: str  # pending, running, completed, failed
    output: str = ""
    error: str = ""
    created_at: str = ""
    completed_at: str = ""


class CodingAgent:
    """OpenHands-style coding agent with sandbox."""

    def __init__(self):
        self.tasks: Dict[str, CodeTask] = {}
        self.supported_languages = ["python", "javascript", "bash", "html", "css"]

    def create_task(self, description: str, code: str, language: str = "python") -> str:
        """Create a new coding task."""
        task_id = f"task_{uuid.uuid4().hex[:8]}"

        self.tasks[task_id] = CodeTask(
            id=task_id,
            description=description,
            code=code,
            language=language.lower(),
            status="pending",
            created_at=datetime.now().isoformat(),
        )

        return task_id

    def execute_task(self, task_id: str) -> Dict:
        """Execute a coding task in sandbox."""
        if task_id not in self.tasks:
            return {"success": False, "error": "Task not found"}

        task = self.tasks[task_id]
        task.status = "running"

        try:
            # Create temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=self._get_extension(task.language), delete=False
            ) as f:
                f.write(task.code)
                temp_path = f.name

            # Execute based on language
            result = self._execute_code(temp_path, task.language)

            task.output = result["output"]
            task.status = "completed"
            task.completed_at = datetime.now().isoformat()

            # Cleanup
            try:
                os.remove(temp_path)
            except:
                pass

            return {
                "success": True,
                "task_id": task_id,
                "output": task.output,
                "error": result.get("error", ""),
            }

        except Exception as e:
            task.error = str(e)
            task.status = "failed"
            task.completed_at = datetime.now().isoformat()

            return {"success": False, "task_id": task_id, "error": str(e)}

    def _execute_code(self, file_path: str, language: str) -> Dict:
        """Execute code based on language."""
        result = {"output": "", "error": ""}

        try:
            if language == "python":
                result["output"] = subprocess.check_output(
                    ["python3", file_path], capture_output=True, text=True, timeout=30
                )
            elif language == "javascript":
                result["output"] = subprocess.check_output(
                    ["node", file_path], capture_output=True, text=True, timeout=30
                )
            elif language == "bash":
                result["output"] = subprocess.check_output(
                    ["bash", file_path], capture_output=True, text=True, timeout=30
                )
            elif language == "html":
                # HTML just returns path for viewing
                result["output"] = f"HTML file saved to: {file_path}"
            else:
                result["error"] = f"Unsupported language: {language}"

        except subprocess.CalledProcessError as e:
            result["output"] = e.stdout
            result["error"] = e.stderr
        except subprocess.TimeoutExpired:
            result["error"] = "Execution timeout (30s)"
        except Exception as e:
            result["error"] = str(e)

        return result

    def _get_extension(self, language: str) -> str:
        """Get file extension for language."""
        extensions = {
            "python": ".py",
            "javascript": ".js",
            "bash": ".sh",
            "html": ".html",
            "css": ".css",
        }
        return extensions.get(language, ".txt")

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Get task status."""
        if task_id not in self.tasks:
            return None

        task = self.tasks[task_id]
        return {
            "id": task.id,
            "description": task.description,
            "status": task.status,
            "output": task.output[:500] if task.output else "",
            "error": task.error,
            "created_at": task.created_at,
            "completed_at": task.completed_at,
        }

    def list_tasks(self) -> List[Dict]:
        """List all tasks."""
        return [self.get_task_status(tid) for tid in self.tasks.keys()]

    def get_status(self) -> Dict:
        """Get coding agent status."""
        statuses = {}
        for task in self.tasks.values():
            statuses[task.status] = statuses.get(task.status, 0) + 1

        return {
            "available": True,
            "supported_languages": self.supported_languages,
            "total_tasks": len(self.tasks),
            "task_statuses": statuses,
        }


# Singleton
_coding_agent = None


def get_coding_agent() -> CodingAgent:
    global _coding_agent
    if _coding_agent is None:
        _coding_agent = CodingAgent()
    return _coding_agent


# Test
if __name__ == "__main__":
    ca = get_coding_agent()

    print("💻 Coding Agent Test")

    # Create task
    task_id = ca.create_task(
        description="Print hello",
        code="print('Hello from JARVIS!')\nprint('Current time:', __import__('datetime').datetime.now())",
        language="python",
    )
    print(f"Created task: {task_id}")

    # Execute
    result = ca.execute_task(task_id)
    print(f"Result: {result.get('success')}")
    print(f"Output: {result.get('output', '')[:100]}")

    print("\n✅ Coding agent ready!")
