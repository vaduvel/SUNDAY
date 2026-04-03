"""
J.A.R.V.I.S. Simple Sandbox
===========================

Sandbox simplu pentru izolarea task-urilor:
- Director dedicat per task
- Timeout pe comenzi
- Output capture
- Nu necesită Docker
"""

import os
import subprocess
import time
import shutil
from typing import Dict, Any, Optional
from pathlib import Path
import uuid


class SimpleSandbox:
    """
    Sandbox simplu fără Docker.

    Funcționalități:
    - Director de lucru izolat per task
    - Timeout pe execuție
    - Capture output
    - Cleanup automat
    """

    def __init__(self, sandbox_root: str = ".agent/sandbox"):
        self.sandbox_root = Path(sandbox_root)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

    def create_workspace(self, task_id: str = None) -> str:
        """Creează director de lucru pentru un task"""
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]

        workspace = self.sandbox_root / f"task_{task_id}"
        workspace.mkdir(exist_ok=True)

        # Create subdirectories
        (workspace / "input").mkdir(exist_ok=True)
        (workspace / "output").mkdir(exist_ok=True)
        (workspace / "temp").mkdir(exist_ok=True)

        return str(workspace)

    def run_command(
        self,
        command: str,
        cwd: str = None,
        timeout: int = 30,
        env: Dict[str, str] = None,
        capture_output: bool = True,
    ) -> Dict[str, Any]:
        """
        Rulează comandă în sandbox.

        Args:
            command: Comanda de executat
            cwd: Director de lucru (default: sandbox root)
            timeout: Timeout în secunde
            env: Variabile de mediu
            capture_output: Capturează stdout/stderr

        Returns:
            Dict cu success, stdout, stderr, returncode, elapsed
        """
        start_time = time.time()

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd or str(self.sandbox_root),
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                env=env or os.environ.copy(),
            )

            elapsed = time.time() - start_time

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout if capture_output else "",
                "stderr": result.stderr if capture_output else "",
                "returncode": result.returncode,
                "elapsed_seconds": round(elapsed, 2),
                "timeout": False,
            }

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "returncode": -1,
                "elapsed_seconds": round(elapsed, 2),
                "timeout": True,
            }

        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
                "elapsed_seconds": round(elapsed, 2),
                "timeout": False,
                "error": str(e),
            }

    def run_python(
        self, code: str, timeout: int = 30, workspace: str = None
    ) -> Dict[str, Any]:
        """
        Rulează cod Python în sandbox.

        Args:
            code: Codul Python
            timeout: Timeout în secunde
            workspace: Director de lucru

        Returns:
            Dict cu output și metrici
        """
        if workspace is None:
            workspace = self.create_workspace()

        # Write code to file
        code_file = Path(workspace) / "script.py"
        code_file.write_text(code)

        # Run with python
        result = self.run_command(
            f"python3 {code_file}", cwd=workspace, timeout=timeout
        )

        return result

    def write_file(self, workspace: str, filename: str, content: str) -> bool:
        """Scrie fișier în workspace"""
        try:
            filepath = Path(workspace) / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)
            return True
        except Exception:
            return False

    def read_file(self, workspace: str, filename: str) -> Optional[str]:
        """Citește fișier din workspace"""
        try:
            filepath = Path(workspace) / filename
            return filepath.read_text()
        except Exception:
            return None

    def list_files(self, workspace: str) -> list:
        """Listează fișiere din workspace"""
        try:
            workspace_path = Path(workspace)
            return [
                str(f.relative_to(workspace_path))
                for f in workspace_path.rglob("*")
                if f.is_file()
            ]
        except Exception:
            return []

    def cleanup(self, workspace: str = None) -> bool:
        """Șterge workspace sau toate"""
        try:
            if workspace:
                shutil.rmtree(workspace, ignore_errors=True)
            else:
                # Cleanup all
                for item in self.sandbox_root.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
            return True
        except Exception:
            return False

    def get_workspace_size(self, workspace: str) -> int:
        """Get workspace size in bytes"""
        total = 0
        try:
            for item in Path(workspace).rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
        except:
            pass
        return total


# ==================== GLOBAL INSTANCE ====================

_sandbox: Optional[SimpleSandbox] = None


def get_sandbox() -> SimpleSandbox:
    """Get or create global sandbox"""
    global _sandbox
    if _sandbox is None:
        _sandbox = SimpleSandbox()
    return _sandbox


# ==================== TEST ====================

if __name__ == "__main__":
    sandbox = get_sandbox()

    print("=== SIMPLE SANDBOX TEST ===")

    # Create workspace
    workspace = sandbox.create_workspace("test_001")
    print(f"Workspace: {workspace}")

    # Test write/read
    sandbox.write_file(workspace, "test.txt", "Hello from sandbox!")
    content = sandbox.read_file(workspace, "test.txt")
    print(f"Read: {content}")

    # Test command
    result = sandbox.run_command("echo 'Test command'", timeout=5)
    print(f"Command: {result['success']}, output: {result['stdout'].strip()}")

    # Test Python
    py_result = sandbox.run_python(
        "print('Python in sandbox!')", timeout=10, workspace=workspace
    )
    print(f"Python: {py_result['success']}, output: {py_result['stdout'].strip()}")

    # List files
    files = sandbox.list_files(workspace)
    print(f"Files: {files}")

    # Cleanup
    sandbox.cleanup(workspace)
    print("Cleaned up!")
