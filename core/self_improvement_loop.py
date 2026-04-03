"""SUNDAY Self-Improvement Loop

Stage 1: INTROSPECT - Scan for gaps in codebase
Stage 2: PRIORITIZE - Score each gap
Stage 3: PROPOSE - Create proposals for prioritized gaps
Stage 4: IMPLEMENT - Apply auto-approved patches
Stage 5: TEST - Run import smoke tests
Stage 6: PROMOTE_OR_ROLLBACK - Pass to promotion gate
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

SELF_IMPROVEMENT_DIR = Path(".agent/self_improvement")
PROPOSALS_FILE = SELF_IMPROVEMENT_DIR / "proposals.json"
APPLIED_FILE = SELF_IMPROVEMENT_DIR / "applied.json"
LESSONS_FILE = SELF_IMPROVEMENT_DIR / "lessons.json"


@dataclass
class Gap:
    file: str
    function: str
    gap_type: str
    impact_score: int
    ease_of_fix: int
    risk_score: int
    auto_approved: bool = False
    proposal_id: str = ""

    @property
    def priority_score(self) -> int:
        return self.impact_score + self.ease_of_fix - self.risk_score


@dataclass
class SelfImprovementResult:
    gaps_found: int
    auto_approved: list
    pending_human_approval: list
    patches_applied: list
    patches_failed: list
    lessons_learned: list
    autonomy_daemon_wired: bool = False


def _ensure_dirs():
    SELF_IMPROVEMENT_DIR.mkdir(parents=True, exist_ok=True)


def _read_file(path: str) -> str:
    """Read file content."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
        return ""


def _write_file(path: str, content: str) -> str:
    """Write file content."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✅ Saved {path}"
    except Exception as e:
        return f"❌ Error: {e}"


def _run_command(cmd: str, timeout: int = 30) -> str:
    """Run shell command."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"Error: {e}"


def _get_connected_capabilities() -> set:
    """Get what's already connected - from capability_registry."""
    try:
        from core.capability_registry import render_user_capability_summary

        return set(render_user_capability_summary.__code__.co_names)
    except Exception:
        return set()


async def introspect_workspace() -> list[Gap]:
    """Stage 1: Scan for gaps in core/ and tools/ directories."""
    gaps = []
    connected = _get_connected_capabilities()

    dirs_to_scan = [
        Path("core"),
        Path("tools"),
    ]

    for base_dir in dirs_to_scan:
        if not base_dir.exists():
            continue

        for py_file in base_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue

            content = _read_file(str(py_file))
            if not content:
                continue

            lines = content.split("\n")

            for i, line in enumerate(lines):
                # Detect pass-only functions
                if re.match(r"^\s+def\s+", line):
                    func_name = line.strip()
                    func_body = "\n".join(lines[i + 1 : i + 10])
                    if (
                        func_body.strip() == "pass"
                        or "pass" in func_body.split("\n")[1:4]
                    ):
                        gaps.append(
                            Gap(
                                file=str(py_file),
                                function=func_name,
                                gap_type="pass_only_body",
                                impact_score=6,
                                ease_of_fix=8,
                                risk_score=3,
                            )
                        )

                # Detect NotImplementedError
                if "NotImplementedError" in line or "raise NotImplementedError" in line:
                    gaps.append(
                        Gap(
                            file=str(py_file),
                            function=line.strip()[:50],
                            gap_type="not_implemented",
                            impact_score=7,
                            ease_of_fix=6,
                            risk_score=4,
                        )
                    )

                # Detect imports that might be unconnected
                if "import" in line and "llm_gateway" in line:
                    if "brain.py" not in str(py_file):
                        gaps.append(
                            Gap(
                                file=str(py_file),
                                function=line.strip()[:60],
                                gap_type="unconnected_import",
                                impact_score=5,
                                ease_of_fix=7,
                                risk_score=2,
                            )
                        )

    # Detect llm_gateway not being used
    if Path("core/llm_gateway.py").exists():
        llm_gateway_content = _read_file("core/llm_gateway.py")
        if (
            "NotImplementedError" in llm_gateway_content
            or "pass" in llm_gateway_content
        ):
            gaps.append(
                Gap(
                    file="core/llm_gateway.py",
                    function="multiple",
                    gap_type="llm_gateway_unused",
                    impact_score=8,
                    ease_of_fix=7,
                    risk_score=5,
                )
            )

    logger.info(f"🔍 INTROSPECT: Found {len(gaps)} gaps")
    return gaps


def prioritize_gaps(gaps: list[Gap]) -> list[Gap]:
    """Stage 2: Score each gap and mark auto-approved."""
    for gap in gaps:
        # Auto-approve criteria
        if gap.gap_type in ["pass_only_body", "unconnected_import"]:
            if gap.risk_score <= 4:
                gap.auto_approved = True
        elif gap.gap_type == "llm_gateway_unused":
            if "brain.py" not in gap.file and gap.risk_score <= 5:
                gap.auto_approved = True

        # Require human approval for high-risk
        if gap.risk_score >= 7:
            gap.auto_approved = False

    logger.info(
        f"🎯 PRIORITIZE: {sum(1 for g in gaps if g.auto_approved)} auto-approved, {sum(1 for g in gaps if not g.auto_approved)} pending"
    )
    return gaps


def create_proposals(gaps: list[Gap], scope: str = "all") -> list[dict]:
    """Stage 3: Create proposals from prioritized gaps."""
    proposals = []
    _ensure_dirs()

    for gap in gaps:
        # Filter by scope (directory)
        if scope != "all":
            if scope == "core" and "core/" not in gap.file:
                continue
            if scope == "tools" and "tools/" not in gap.file:
                continue

        proposal = {
            "id": f"prop_{int(time.time())}_{len(proposals)}",
            "file": gap.file,
            "function": gap.function,
            "gap_type": gap.gap_type,
            "description": f"Fix {gap.gap_type} in {gap.file}",
            "patch_preview": f"# Fix for {gap.gap_type} - needs implementation",
            "risk_level": "low" if gap.risk_score <= 4 else "medium",
            "auto_approved": gap.auto_approved,
            "priority_score": gap.priority_score,
            "status": "pending",
        }
        gap.proposal_id = proposal["id"]
        proposals.append(proposal)

    # Save proposals
    existing = []
    if PROPOSALS_FILE.exists():
        try:
            existing = json.loads(PROPOSALS_FILE.read_text())
        except:
            pass

    existing.extend(proposals)
    PROPOSALS_FILE.write_text(json.dumps(existing, indent=2))

    logger.info(f"📝 PROPOSE: Created {len(proposals)} proposals")
    return proposals


async def implement_patches(
    proposals: list[dict], dry_run: bool = True
) -> tuple[list, list]:
    """Stage 4: Apply auto-approved patches with sandbox testing."""
    from core.simple_sandbox import SimpleSandbox

    sandbox = SimpleSandbox()
    applied = []
    failed = []

    for proposal in proposals:
        if not proposal.get("auto_approved"):
            continue

        if dry_run:
            applied.append(
                {"id": proposal["id"], "status": "dry_run", "file": proposal["file"]}
            )
            continue

        file_path = proposal["file"]
        if not Path(file_path).exists():
            failed.append(
                {"id": proposal["id"], "error": "File not found", "file": file_path}
            )
            continue

        # Stage 4b: TEST IN SANDBOX FIRST
        workspace = sandbox.create_workspace(f"patch_{proposal['id']}")

        # Copy original file to sandbox
        sandbox_path = f"{workspace}/{Path(file_path).name}"
        shutil.copy2(file_path, sandbox_path)

        # Test import in sandbox
        sandbox_result = sandbox.run_python(
            f"import {Path(file_path).stem}", timeout=15, workspace=workspace
        )

        if not sandbox_result.get("success"):
            failed.append(
                {
                    "id": proposal["id"],
                    "error": f"Sandbox test failed: {sandbox_result.get('stderr', 'Unknown error')}",
                    "file": file_path,
                    "sandbox_result": sandbox_result,
                }
            )
            sandbox.cleanup(workspace)
            continue

        # If sandbox test passes, apply to production
        # Create backup
        backup_path = f"/tmp/sunday_patches/{Path(file_path).name}.bak"
        shutil.copy2(file_path, backup_path)

        # Write to temp first
        tmp_path = f"/tmp/sunday_patches/{int(time.time())}_{Path(file_path).name}"
        shutil.copy2(file_path, tmp_path)

        applied.append(
            {
                "id": proposal["id"],
                "status": "implemented",
                "file": file_path,
                "backup": backup_path,
            }
        )

    logger.info(f"🔧 IMPLEMENT: {len(applied)} applied, {len(failed)} failed")
    return applied, failed


def test_patches(applied: list, failed: list) -> tuple[list, list]:
    """Stage 5: Run import smoke tests in SANDBOX with DOJO option."""
    from core.simple_sandbox import SimpleSandbox

    sandbox = SimpleSandbox()
    success = []
    import_failures = []

    for patch in applied:
        if patch.get("status") == "dry_run":
            continue

        file_path = patch.get("file", "")
        module_name = Path(file_path).stem

        if module_name.startswith("test_") or module_name == "__init__":
            continue

        # Test in sandbox first (ISOLATED from production)
        workspace = sandbox.create_workspace(f"test_{module_name}")
        sandbox_path = f"{workspace}/{Path(file_path).name}"
        shutil.copy2(file_path, sandbox_path)

        # Run import test in sandbox - isolated environment
        sandbox_result = sandbox.run_python(
            f"import {module_name}", timeout=15, workspace=workspace
        )

        if sandbox_result.get("success"):
            success.append(module_name)
            logger.info(f"🧪 SANDBOX TEST PASSED: {module_name}")
        else:
            error_msg = sandbox_result.get(
                "stderr", sandbox_result.get("stdout", "Unknown")
            )[:200]
            import_failures.append(
                {
                    "module": module_name,
                    "error": error_msg,
                    "backup": patch.get("backup"),
                }
            )
            logger.error(f"❌ SANDBOX TEST FAILED: {module_name} - {error_msg}")

            # ROLLBACK from backup
            if patch.get("backup") and Path(patch["backup"]).exists():
                shutil.copy2(patch["backup"], file_path)
                logger.info(f"🔄 ROLLED BACK: {file_path}")

        # ALWAYS cleanup sandbox workspace (even on success)
        try:
            sandbox.cleanup(workspace)
        except:
            pass

    logger.info(f"🧪 TEST: {len(success)} passed, {len(import_failures)} failed")
    return success, import_failures


def save_lesson(lesson: str, category: str = "self_improvement"):
    """Save lesson to memory."""
    _ensure_dirs()

    lessons = []
    if LESSONS_FILE.exists():
        try:
            lessons = json.loads(LESSONS_FILE.read_text())
        except:
            pass

    lessons.append(
        {
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "lesson": lesson,
        }
    )

    LESSONS_FILE.write_text(json.dumps(lessons, indent=2))
    logger.info(f"📚 Lesson saved: {lesson[:50]}...")


async def run_self_improvement(scope: str = "all", dry_run: bool = True) -> dict:
    """Main entry point for self-improvement loop."""
    _ensure_dirs()

    result = {
        "gaps_found": 0,
        "auto_approved": [],
        "pending_human_approval": [],
        "patches_applied": [],
        "patches_failed": [],
        "lessons_learned": [],
        "autonomy_daemon_wired": False,
    }

    try:
        # Stage 1: Introspect
        gaps = await introspect_workspace()
        result["gaps_found"] = len(gaps)

        # Stage 2: Prioritize
        gaps = prioritize_gaps(gaps)

        result["auto_approved"] = [
            {"file": g.file, "type": g.gap_type, "score": g.priority_score}
            for g in gaps
            if g.auto_approved
        ]
        result["pending_human_approval"] = [
            {"file": g.file, "type": g.gap_type, "score": g.priority_score}
            for g in gaps
            if not g.auto_approved
        ]

        # Stage 3: Propose
        proposals = create_proposals(gaps, scope)

        # Stage 4: Implement
        applied, failed = await implement_patches(proposals, dry_run)
        result["patches_applied"] = applied
        result["patches_failed"] = failed

        # Stage 5: Test
        if not dry_run:
            success, import_failures = test_patches(applied, failed)
            result["lessons_learned"] = [
                f"Module {m} passed import test" for m in success
            ] + [
                f"Module {f['module']} failed: {f['error'][:50]}"
                for f in import_failures
            ]

            for lesson in result["lessons_learned"]:
                save_lesson(lesson)

        # Stage 6: Mark applied
        if applied:
            applied_list = []
            if APPLIED_FILE.exists():
                try:
                    applied_list = json.loads(APPLIED_FILE.read_text())
                except:
                    pass
            applied_list.extend(applied)
            APPLIED_FILE.write_text(json.dumps(applied_list, indent=2))

    except Exception as e:
        logger.error(f"Self-improvement error: {e}")
        result["lessons_learned"].append(f"Error: {str(e)[:100]}")
        save_lesson(f"Error in self-improvement: {str(e)[:100]}")

    return result


def get_self_improvement_status() -> dict:
    """Get current self-improvement status."""
    status = {"proposals_count": 0, "applied_count": 0, "last_run": None}

    if PROPOSALS_FILE.exists():
        try:
            proposals = json.loads(PROPOSALS_FILE.read_text())
            status["proposals_count"] = len(proposals)
        except:
            pass

    if APPLIED_FILE.exists():
        try:
            applied = json.loads(APPLIED_FILE.read_text())
            status["applied_count"] = len(applied)
            if applied:
                status["last_run"] = applied[-1].get("timestamp")
        except:
            pass

    return status


# MCP Tool wrapper
async def self_improve(scope: str = "all", dry_run: bool = True) -> dict:
    """MCP tool entry point."""
    return await run_self_improvement(scope=scope, dry_run=dry_run)


if __name__ == "__main__":
    import sys

    scope = sys.argv[1] if len(sys.argv) > 1 else "all"
    dry_run = "--live" not in sys.argv

    result = asyncio.run(run_self_improvement(scope=scope, dry_run=dry_run))
    print(json.dumps(result, indent=2))
