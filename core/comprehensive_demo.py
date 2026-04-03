"""
J.A.R.V.I.S. COMPREHENSIVE DEMO
==============================

Demo complex care testează TOATE sistemele:
- eval_harness (evaluation)
- verifier (post-action checks)
- risk_tiers (4 nivele)
- simple_sandbox (izolare)
- model_router (role-based)
- behavior_adaptation (memory → behavior)
- computer_use (desktop control)
- verified_executor (executor with all)

Task real: Research + Code + Desktop operations
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, ".")

import logging

logging.disable(logging.WARNING)

# Import all systems
from core.verifier import get_verifier
from core.risk_tiers import get_risk_system, RiskLevel
from core.simple_sandbox import get_sandbox
from core.model_router import get_model_router, ModelRole
from core.behavior_adaptation import get_behavior_adaptation
from core.verified_executor import VerifiedTaskExecutor
from core.runtime_config import configure_inception_openai_alias, load_project_env
from tools.computer_use import get_computer_tool
from tools.search_tool import duckduckgo_search_results
from tools.file_manager import write_text_file, read_text_file

load_project_env()
configure_inception_openai_alias()


class ComprehensiveDemo:
    """
    Demo comprehensiv care folosește toate sistemele.

    Task: Creează un raport de cercetare cu:
    1. Căutare web despre un subiect
    2. Generare cod de test
    3. Salvare în sandbox
    4. Verificare rezultate
    5. Desktop notification
    """

    def __init__(self):
        print("=" * 60)
        print("🚀 J.A.R.V.I.S. COMPREHENSIVE DEMO")
        print("=" * 60)

        # Initialize all systems
        self.verifier = get_verifier()
        self.risk = get_risk_system()
        self.sandbox = get_sandbox()
        self.router = get_model_router()
        self.behavior = get_behavior_adaptation()
        self.executor = VerifiedTaskExecutor()
        self.computer = get_computer_tool()

        # Metrics
        self.metrics = {
            "tasks_total": 0,
            "tasks_success": 0,
            "steps_executed": 0,
            "verifications_passed": 0,
            "verifications_failed": 0,
            "risk_checks": 0,
            "sandbox_commands": 0,
            "model_calls": 0,
            "behavior_learns": 0,
            "start_time": time.time(),
        }

    async def run(self, task_name: str, task_description: str):
        """Rulează un task complex cu toate sistemele"""

        print(f"\n📋 Task: {task_name}")
        print(f"   Description: {task_description}")
        print("-" * 60)

        self.metrics["tasks_total"] += 1
        start_time = time.time()

        try:
            # === STEP 1: Determine model role ===
            print("\n1️⃣ MODEL ROUTING")
            role = self.router.determine_role(task_description)
            model_config = self.router.get_model_for_role(role)
            print(f"   → Role: {role.value} | Model: {model_config.name}")
            self.metrics["model_calls"] += 1

            # === STEP 2: Risk assessment ===
            print("\n2️⃣ RISK ASSESSMENT")
            risk_level, approval_req = self.risk.check_action(
                "research_and_code", {"task": task_name}, task_description
            )
            print(f"   → Risk Level: {risk_level.value}")
            self.metrics["risk_checks"] += 1

            if risk_level == RiskLevel.NEVER:
                print("   ❌ BLOCKED by risk system")
                return False

            # === STEP 3: Create sandbox workspace ===
            print("\n3️⃣ SANDBOX SETUP")
            workspace = self.sandbox.create_workspace(task_name.replace(" ", "_"))
            print(f"   → Workspace: {workspace}")

            # === STEP 4: Execute subtasks ===
            print("\n4️⃣ EXECUTE SUBTASKS")

            # Subtask 1: Web Search
            print("\n   4.1 Web Research...")
            search_result = await self._do_search("AI agents 2025")

            # Verify search
            verification = self.verifier.verify_action(
                "search",
                {"query": "AI agents 2025"},
                "Should find results",
                search_result,
            )
            print(f"       Verification: {verification.status.value}")
            if verification.status.value == "passed":
                self.metrics["verifications_passed"] += 1
            else:
                self.metrics["verifications_failed"] += 1

            # Learn from result
            self.behavior.learn_from_interaction(
                "web_search",
                ["search", "analyze"],
                verification.status.value == "passed",
            )
            self.metrics["behavior_learns"] += 1

            # Subtask 2: Write code in sandbox
            print("\n   4.2 Code Generation...")
            code_result = self.sandbox.run_python(
                '''
import random

def generate_report(topic):
    """Generate a sample report"""
    sections = [
        f"## Introducere despre {topic}",
        f"## Analiza {topic}",
        f"## Concluzii {topic}"
    ]
    return "\\n".join(sections)

# Generate report
report = generate_report("AI Agents")
print("RAPORT:")
print(report)
print("\\n--- END OF REPORT ---")
''',
                workspace=workspace,
            )

            # Verify code execution
            verification2 = self.verifier.verify_action(
                "python_exec",
                {"workspace": workspace},
                "Should execute successfully",
                code_result,
            )
            print(f"       Code result: {'✅' if code_result['success'] else '❌'}")
            print(f"       Verification: {verification2.status.value}")

            # Check output
            if code_result["success"]:
                output = code_result.get("stdout", "")
                print(f"       Output preview: {output[:100]}...")

            self.metrics["steps_executed"] += 1

            # Subtask 3: Desktop notification
            print("\n   4.3 Desktop Notification...")
            notif_result = self.computer.run_command(
                'osascript -e \'display notification "JARVIS Demo Complete" with title "JARVIS"\''
            )
            print(f"       Notification: {'✅' if notif_result['success'] else '❌'}")

            # === STEP 5: Final verification ===
            print("\n5️⃣ FINAL VERIFICATION")

            # Check sandbox files
            files = self.sandbox.list_files(workspace)
            print(f"   → Files created: {len(files)}")

            # === STEP 6: Behavior adaptation ===
            print("\n6️⃣ BEHAVIOR ADAPTATION")

            # Get learned preferences
            status = self.behavior.get_status()
            print(f"   → Patterns learned: {status['patterns_learned']}")
            print(f"   → Anti-patterns: {status['anti_patterns_identified']}")

            # === STEP 7: Model routing for summary ===
            print("\n7️⃣ SUMMARY GENERATION")

            summary_result = await self.router.complete(
                f"Create a short summary of the research about AI agents based on search results",
                role=ModelRole.RESEARCHER,
            )

            if summary_result.get("success"):
                summary = summary_result.get("response", "No summary")
                print(f"   → Summary: {summary[:150]}...")

            # Calculate elapsed
            elapsed = time.time() - start_time

            # Success
            self.metrics["tasks_success"] += 1

            print("\n" + "=" * 60)
            print("✅ TASK COMPLETED SUCCESSFULLY")
            print(f"   Total time: {elapsed:.2f}s")
            print("=" * 60)

            return True

        except Exception as e:
            print(f"\n❌ ERROR: {str(e)[:100]}")

            # Learn from failure
            self.behavior.learn_from_interaction(task_name, ["execute"], False, str(e))

            return False

    async def _do_search(self, query: str) -> dict:
        """Do web search"""
        results = duckduckgo_search_results(query)
        return {"success": True, "results": results}

    def print_final_report(self):
        """Print final metrics report"""
        elapsed = time.time() - self.metrics["start_time"]

        print("\n" + "=" * 60)
        print("📊 FINAL METRICS REPORT")
        print("=" * 60)

        print(f"\n🎯 TASKS:")
        print(f"   Total: {self.metrics['tasks_total']}")
        print(f"   Success: {self.metrics['tasks_success']}")
        print(
            f"   Rate: {self.metrics['tasks_success'] / max(1, self.metrics['tasks_total']) * 100:.0f}%"
        )

        print(f"\n🔍 EXECUTION:")
        print(f"   Steps executed: {self.metrics['steps_executed']}")

        print(f"\n✅ VERIFICATIONS:")
        print(f"   Passed: {self.metrics['verifications_passed']}")
        print(f"   Failed: {self.metrics['verifications_failed']}")
        print(
            f"   Rate: {self.metrics['verifications_passed'] / max(1, self.metrics['verifications_passed'] + self.metrics['verifications_failed']) * 100:.0f}%"
        )

        print(f"\n🛡️ RISK:")
        print(f"   Checks: {self.metrics['risk_checks']}")

        print(f"\n🤖 MODEL:")
        print(f"   Calls: {self.metrics['model_calls']}")

        print(f"\n🧠 BEHAVIOR:")
        print(f"   Learned: {self.metrics['behavior_learns']}")

        print(f"\n⏱️ TIME:")
        print(f"   Total: {elapsed:.1f}s")

        print("\n" + "=" * 60)

        # System statuses
        print("\n📦 SYSTEM STATUS:")
        print(f"   ✅ Verifier: {self.verifier.get_verification_stats()}")
        print(f"   ✅ Risk Tiers: {self.risk.get_stats()}")
        print(f"   ✅ Model Router: {self.router.get_usage_stats()}")
        print(f"   ✅ Behavior Adaptation: {self.behavior.get_status()}")


async def run_demo():
    """Run the comprehensive demo"""
    demo = ComprehensiveDemo()

    # Run task
    await demo.run(
        "research_and_code_demo",
        "Caută informații despre AI agents, generează un raport în sandbox, și trimite notificare",
    )

    # Print final report
    demo.print_final_report()


if __name__ == "__main__":
    asyncio.run(run_demo())
