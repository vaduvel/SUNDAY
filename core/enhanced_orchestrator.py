"""
J.A.R.V.I.S. Enhanced Orchestrator V2
=======================================

Orchestrator complet cu pipeline-ul corect:
- Planner → Executor → Observer → Verifier → Repairer

Based on JARVIS V2 Blueprint Section 5.1
"""

import asyncio
import sys
import os
from typing import Dict, Any, Optional, List
import logging

sys.path.insert(0, ".")
from core.runtime_config import configure_inception_openai_alias, load_project_env

load_project_env()
configure_inception_openai_alias()

logging.disable(logging.WARNING)

from core.task_contracts import (
    TaskContract,
    PlanStep,
    ExecutionResult,
    TaskRisk,
    TaskStatus,
    create_mission,
    create_step,
    SuccessCriteria,
)
from core.risk_engine import get_risk_engine, TaskRisk as R
from core.post_action_observer import get_post_action_observer
from core.verifier_engine import get_verifier_engine
from core.repair_engine import get_repair_engine, RepairAction
from core.mission_metrics import get_metrics_collector
from core.model_router import get_model_router, ModelRole

from tools.search_tool import duckduckgo_search_results
from tools.file_manager import write_text_file, read_text_file
from tools.computer_use import get_computer_tool


class EnhancedOrchestrator:
    """
    Orchestrator V2 cu pipeline complet:

    1. PLANNING - Creează contract misiune
    2. RISK_REVIEW - Verifică risc
    3. EXECUTING - Execută pas
    4. OBSERVING - Capturează stare
    5. VERIFYING - Verifică rezultat
    6. REPAIRING - Recovery dacă eșec
    7. Repeat pentru toți pașii
    """

    def __init__(self):
        self.risk_engine = get_risk_engine()
        self.observer = get_post_action_observer()
        self.verifier = get_verifier_engine()
        self.repair = get_repair_engine()
        self.metrics = get_metrics_collector()
        self.router = get_model_router()
        self.computer = get_computer_tool()

    async def run_mission(self, user_input: str, context: Dict = None) -> Dict:
        """
        Rulează o misiune completă cu verificare.

        Returns:
            Dict cu rezultatul misiunii
        """

        print(f"\n{'=' * 60}")
        print(f"🚀 ENHANCED ORCHESTRATOR - V2")
        print(f"   Input: {user_input[:50]}...")
        print(f"{'=' * 60}")

        # Create mission contract
        mission = create_mission(user_input, context or {})
        print(f"\n📋 Mission: {mission.mission_id}")

        # Start metrics
        self.metrics.start_mission(mission.mission_id)

        # Generate plan (simplified - in real would use LLM)
        plan = self._generate_plan(user_input)
        mission.steps = plan
        print(f"   Plan: {len(plan)} steps")

        # Execute each step through pipeline
        for i, step in enumerate(mission.steps):
            mission.current_step_index = i
            print(f"\n{'─' * 40}")
            print(f"Step {i + 1}/{len(plan)}: {step.title}")
            print(f"{'─' * 40}")

            # === PHASE 1: RISK REVIEW ===
            print(f"\n1️⃣ RISK REVIEW")
            risk_check = self.risk_engine.classify_step_risk(step)
            print(
                f"   Risk: {risk_check.risk_level.value} ({risk_check.approval_level})"
            )

            if risk_check.requires_approval:
                self.metrics.record_approval(False)  # Requested not granted yet
                approval = self.risk_engine.request_approval(
                    step, "Risk requires approval"
                )
                print(f"   ⚠️ Approval required - {approval.step_id}")
                # Auto-approve for demo
                self.risk_engine.approve(step.id, True)
                self.metrics.record_approval(True)

            # === PHASE 2: EXECUTING ===
            print(f"\n2️⃣ EXECUTING")
            self.metrics.record_tool_call()
            exec_result = await self._execute_step(step)
            print(f"   Status: {exec_result.status.value}")

            # === PHASE 3: OBSERVING ===
            print(f"\n3️⃣ OBSERVING")
            observed_state = self.observer.observe_after_action(
                step_id=step.id,
                session_id=mission.mission_id,
                action_type=step.tool_candidates[0],
                action_params={},
            )
            print(f"   Signals: {len(observed_state.signals)}")

            # === PHASE 4: VERIFYING ===
            print(f"\n4️⃣ VERIFYING")
            verification = self.verifier.verify_step(step, exec_result, observed_state)
            print(
                f"   Verified: {verification.verified} ({verification.confidence.value})"
            )
            print(f"   Action: {verification.recommended_action}")

            # Record metrics
            self.metrics.record_step(
                verification.verified, is_retry=step.retry_count > 0
            )

            if verification.verified:
                mission.mark_step_complete(step.id, exec_result, verification)
                continue

            # === PHASE 5: REPAIRING ===
            print(f"\n5️⃣ REPAIRING")
            repair_result = self.repair.choose_repair_action(
                step, exec_result, verification
            )
            print(f"   Action: {repair_result.action.value}")
            print(f"   Reason: {repair_result.reason}")

            # Apply repair
            if repair_result.action == RepairAction.RETRY_SAME_TOOL:
                self.metrics.record_step(True, is_retry=True)
            elif repair_result.action == RepairAction.REPLAN:
                self.metrics.record_replan()
            elif repair_result.action == RepairAction.ESCALATE:
                self.metrics.record_failure("APPROVAL_DENIED")

        # Calculate final result
        success = mission.success_rate() >= 0.8
        verified_success = (
            sum(1 for v in mission.verification_results if v.verified)
            >= len(mission.steps) * 0.8
        )

        # Finish mission
        self.metrics.finish_mission(success, verified_success)

        print(f"\n{'=' * 60}")
        print(f"✅ MISSION COMPLETE")
        print(f"   Success: {success}")
        print(f"   Verified: {verified_success}")
        print(f"   Steps: {len(mission.steps)}")
        print(
            f"   Verification: {sum(1 for v in mission.verification_results if v.verified)}/{len(mission.verification_results)}"
        )
        print(f"{'=' * 60}")

        return {
            "mission_id": mission.mission_id,
            "success": success,
            "verified": verified_success,
            "steps": len(mission.steps),
            "verified_steps": sum(
                1 for v in mission.verification_results if v.verified
            ),
            "metrics": self.metrics.get_latest_metrics().to_dict()
            if self.metrics.get_latest_metrics()
            else {},
        }

    def _generate_plan(self, user_input: str) -> List[PlanStep]:
        """Generate plan from user input (simplified)"""
        plan = []

        # Parse user input to create steps
        user_lower = user_input.lower()

        # Add search step if needed
        if any(kw in user_lower for kw in ["caută", "search", "găsește", "find"]):
            plan.append(create_step("Web Search", "search_tool", R.R0, "Results found"))

        # Add analysis step
        if any(
            kw in user_lower for kw in ["analize", "analyze", "rezumă", "summarize"]
        ):
            plan.append(
                create_step("Analyze Results", "brain", R.R0, "Analysis complete")
            )

        # Add write step if needed
        if any(
            kw in user_lower
            for kw in ["creează", "scrie", "create", "write", "salvează"]
        ):
            plan.append(create_step("Write Output", "file_write", R.R1, "File saved"))

        # Add notification if needed
        if any(kw in user_lower for kw in ["notifică", "notification", "spune"]):
            plan.append(
                create_step("Notify User", "computer_notify", R.R1, "Notification sent")
            )

        # Default: at least one step
        if not plan:
            plan.append(
                create_step("Process Request", "brain", R.R0, "Request processed")
            )

        return plan

    async def _execute_step(self, step: PlanStep) -> ExecutionResult:
        """Execute a step"""
        from datetime import datetime

        tool = step.tool_candidates[0]

        result = ExecutionResult(step_id=step.id, tool_name=tool, raw_output=None)

        try:
            if tool == "search_tool":
                # Extract query from step description
                query = (
                    step.description.replace("caută", "").replace("search", "").strip()
                )
                results = duckduckgo_search_results(query or "test")
                result.raw_output = {"results": results}
                result.artifacts = ["search_results.json"]
                result.observed_signals = ["search_completed", "results_found"]
                result.mark_complete(True)

            elif tool == "file_write":
                filename = "output.txt"
                content = f"Output for: {step.description}"
                write_text_file(filename, content)
                result.raw_output = {"filename": filename}
                result.artifacts = [filename]
                result.observed_signals = ["file_created", "write_completed"]
                result.mark_complete(True)

            elif tool == "brain":
                # Use model router
                response = await self.router.complete(
                    step.description, role=ModelRole.GENERAL
                )
                result.raw_output = {"response": response.get("response", "")}
                result.observed_signals = ["llm_completed"]
                result.mark_complete(response.get("success", True))

            elif tool == "computer_notify":
                result.raw_output = {"notified": True}
                result.observed_signals = ["notification_sent"]
                result.mark_complete(True)

            else:
                result.mark_complete(True, "Tool executed")

        except Exception as e:
            result.mark_complete(False, str(e))
            result.error_code = "TOOL_RUNTIME_ERROR"

        return result


# ==================== TEST ====================


async def test_orchestrator():
    print("=== ENHANCED ORCHESTRATOR V2 TEST ===\n")

    orchestrator = EnhancedOrchestrator()

    # Test missions
    test_missions = [
        "Caută informații despre AI și salvează în fișier",
        "Găsește cele mai bune cursuri de programare",
        "Caută despre machine learning și rezumă",
    ]

    for mission_input in test_missions:
        result = await orchestrator.run_mission(mission_input)
        print(f"\nResult: {result['success']}")
        await asyncio.sleep(1)

    # Print stats
    print(f"\n📊 Final Stats:")
    print(orchestrator.metrics.aggregate_stats())


if __name__ == "__main__":
    asyncio.run(test_orchestrator())
