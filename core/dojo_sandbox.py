"""J.A.R.V.I.S. (GALAXY NUCLEUS - DOJO SANDBOX V2)

Closed-Loop Self-Repair engine with error profiling and autonomous fix attempts.
Inspired by OpenSpace 'Auto-Fix' and Devin 'Recursive Debugging'.
"""

import subprocess
import logging
import os
import time
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)

class DojoSandbox:
    """The automated testing and git-branching engine with Self-Repair DNA."""
    
    def __init__(self, project_root: str):
        self.root = project_root
        self.active_branch = None
        self.repair_attempts = 0
        self.max_repairs = 3

    def create_isolation_branch(self, task_name: str):
        """[ISOLATE]: Creates a new git branch for a specific experimentation."""
        branch_id = f"jarvis-dojo-{task_name.lower().replace(' ', '-')}-{int(time.time())}"
        logger.info(f"🧪 [DOJO] Isolation branch created: {branch_id}")
        
        try:
            subprocess.run(["git", "checkout", "-b", branch_id], cwd=self.root, check=True, capture_output=True)
            self.active_branch = branch_id
            return branch_id
        except Exception as e:
            logger.error(f"❌ [DOJO] Error creating branch: {str(e)}")
            return None

    def run_validation_suite(self, test_command: str = "npm test") -> Dict:
        """[TEST]: Executes the project's test suite and returns the survival report."""
        logger.info(f"🧪 [DOJO] Running validation suite: {test_command}...")
        
        try:
            result = subprocess.run(test_command.split(), cwd=self.root, capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                logger.info("✅ [DOJO] Evolution Success: All tests passed.")
                return {"status": "SUCCESS", "logs": result.stdout}
            else:
                logger.warning("❌ [DOJO] Evolution Failure: Regressions detected.")
                # We extract the 'Heart' of the error for the Self-Fixer
                error_profile = self._profile_error(result.stderr)
                return {"status": "FAILURE", "logs": result.stderr, "profile": error_profile}
                
        except Exception as e:
            return {"status": "ERROR", "logs": str(e)}

    def _profile_error(self, stderr: str) -> str:
        """Extracts the most relevant error lines for LLM context."""
        lines = stderr.splitlines()
        # Look for 'Error:', 'Exception:', 'Failures:'
        relevant = [line for line in lines if any(x in line for x in ["Error", "Exception", "FAIL", "expected"])]
        return "\n".join(relevant[-10:]) # last 10 relevant lines

    async def autonomous_repair_cycle(self, task: str, engine_fix_callback: Callable, test_command: str):
        """[REPLICATE]: The Closed-Loop Self-Repair logic."""
        self.repair_attempts = 0
        
        while self.repair_attempts < self.max_repairs:
            report = self.run_validation_suite(test_command)
            
            if report["status"] == "SUCCESS":
                return True
            
            self.repair_attempts += 1
            logger.warning(f"🛠️ [DOJO] Self-Repair Attempt {self.repair_attempts}/{self.max_repairs}...")
            
            # We call the engine to 'Dream a Fix' based on the error profile
            fix_context = f"Task: {task}\nError Profile: {report['profile']}"
            await engine_fix_callback(fix_context)
            
        logger.error("🛑 [DOJO] Self-Repair exhausted maximum attempts. Rollback required.")
        return False

    def commit_and_promote(self, message: str) -> bool:
        """[MERGE]: Finalizes the successful code and merges it back."""
        if not self.active_branch: return False
        
        try:
            subprocess.run(["git", "add", "."], cwd=self.root, check=True)
            subprocess.run(["git", "commit", "-m", f"JARVIS APPROVED: {message}"], cwd=self.root, check=True)
            
            # Switch back to previous branch (simulated 'main')
            subprocess.run(["git", "checkout", "-"], cwd=self.root, check=True)
            subprocess.run(["git", "merge", self.active_branch], cwd=self.root, check=True)
            
            # Clean up the dojo branch
            subprocess.run(["git", "branch", "-D", self.active_branch], cwd=self.root, check=True)
            self.active_branch = None
            return True
        except Exception as e:
            logger.error(f"❌ [DOJO] Merge Failure: {str(e)}")
            return False

    def rollback(self):
        """[ABANDON]: If evolution fails, we destroy the branch."""
        if not self.active_branch: return
        subprocess.run(["git", "checkout", "-"], cwd=self.root, check=True)
        subprocess.run(["git", "branch", "-D", self.active_branch], cwd=self.root, capture_output=True)
        self.active_branch = None
