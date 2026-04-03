"""J.A.R.V.I.S. (GALAXY NUCLEUS - SYMBOLIC CHECK AEON V2)

The Neuro-Symbolic Validation layer with AEGIS Protection.
Combines LLM planning with hard-coded symbolic logic rules for safety and logic.
Now includes protection for the .agent/ directory (Kill Switch).
"""

import os
import re
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

class SymbolicValidator:
    """The 'God-Eye' that validates AI plans against hard logic rules."""
    
    def __init__(self, root_dir: str):
        self.root = root_dir
        self.forbidden_patterns = [
            r"rm\s+-rf\s+/",
            r"chmod\s+777",
            r">/dev/null",
            r"sudo\s+",
            r"\.agent/",        # [AEGIS] Protect the protocol directory
            r"AEGIS_PROTOCOL"   # [AEGIS] Protect the switch name
        ]

    def validate_plan(self, plan_steps: List[str]) -> Tuple[bool, List[str]]:
        """[VALIDATE]: Checks each step for logical and security violations."""
        errors = []
        
        for i, step in enumerate(plan_steps):
            # 1. SECURITY CHECK (Regex)
            for pattern in self.forbidden_patterns:
                if re.search(pattern, step):
                    errors.append(f"Step {i+1}: Security violation (forbidden pattern '{pattern}').")
            
            # 2. PATH EXISTENCE CHECK
            # If the step mentions a file to read, check if it actually exists
            path_match = re.search(r"(?:view_file|read|index)\(['\"](.+?)['\"]\)", step)
            if path_match:
                path = path_match.group(1)
                full_path = os.path.join(self.root, path) if not os.path.isabs(path) else path
                if not os.path.exists(full_path):
                    errors.append(f"Step {i+1}: Logical error (path '{path}' does not exist).")

            # 3. NO-OP CHECK
            if len(step.strip()) < 5:
                errors.append(f"Step {i+1}: Meaningless or empty operation.")

        if errors:
            logger.warning(f"❌ [SYMBOLIC] Plan rejected: {len(errors)} errors found.")
            return False, errors
            
        logger.info("✅ [SYMBOLIC] Plan validated against all symbolic rules.")
        return True, []

    def validate(self, file_path: str, content: str = "") -> bool:
        """Validate a file write request using the same symbolic safety rules."""
        path_for_check = file_path if os.path.isabs(file_path) else os.path.join(self.root, file_path)
        steps = [f"write('{path_for_check}')"]
        if content:
            steps.append(content[:500])
        is_valid, _ = self.validate_plan(steps)
        return is_valid

# ═══════════════════════════════════════════════════════════════
#  INTEGRATION TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    validator = SymbolicValidator(root_dir=".")
    test_plan = [
        "view_file('.agent/AEGIS_PROTOCOL.json')", # [AEGIS] Should be forbidden
        "rm -rf /",                                # Forbidden
        "read('core/jarvis_engine.py')"            # Valid
    ]
    
    is_valid, report = validator.validate_plan(test_plan)
    print(f"📡 [SYMBOLIC] Validation: {is_valid}")
    for err in report: print(f" - {err}")
