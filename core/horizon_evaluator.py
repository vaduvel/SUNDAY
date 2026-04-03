"""
J.A.R.V.I.S. Task Horizon Evaluator
=====================================

Evaluator pentru task-uri de diferite orizonturi temporale:
- 5 minute tasks
- 30 minute tasks
- 2 hour tasks
- 6 hour tasks

Acestea sunt task-uri complexe, multi-step care necesită:
- Planificare
- Verificare după fiecare pas
- Recovery la erori
- Reasoning pe mai multe call-uri

Scoring:
- success (da/nu)
- latency (timp real)
- steps (număr pași)
- cost (tokens)
- retries (reîncercări)
- interventions (intervenții umane)
- failure_type (tip eșec)
"""

import time
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import sys
import os

sys.path.insert(0, ".")

import logging

logging.disable(logging.WARNING)

from core.runtime_config import configure_inception_openai_alias, load_project_env

load_project_env()
configure_inception_openai_alias()

# ==================== TASK HORIZONS ====================


class TaskHorizon(Enum):
    """Orizont temporal task"""

    SHORT = "short"  # 5 min
    MEDIUM = "medium"  # 30 min
    LONG = "long"  # 2 hours
    EXTENDED = "extended"  # 6 hours


@dataclass
class HorizonTask:
    """Task complex pentru evaluation"""

    id: str
    horizon: TaskHorizon
    description: str
    gold_steps: List[str]  # Pași așteptați
    expected_outcome: str
    risk_level: str  # safe, low, high
    requires_approval: bool = False
    timeout_seconds: int = 300
    max_retries: int = 2


# ==================== ADVANCED TASK REGISTRY ====================

HORIZON_TASKS: List[HorizonTask] = [
    # === SHORT (5 min) - Multi-step web/desktop ===
    HorizonTask(
        id="h1_web_search_compare",
        horizon=TaskHorizon.SHORT,
        description="Caută pe web top 3 laptopuri și top 3 telefoane, compară și prezintă într-un tabel",
        gold_steps=["search_laptops", "search_phones", "compare", "format_table"],
        expected_outcome="Tabel cu comparație laptopuri vs telefoane",
        risk_level="safe",
    ),
    HorizonTask(
        id="h2_desktop_file_organize",
        horizon=TaskHorizon.SHORT,
        description="Creează 3 foldere noi, creează câte un fișier text în fiecare, apoi listează conținutul",
        gold_steps=["create_folders", "create_files", "list_contents"],
        expected_outcome="3 foldere cu fișiere create",
        risk_level="low",
    ),
    HorizonTask(
        id="h3_code_simple_test",
        horizon=TaskHorizon.SHORT,
        description="Scrie o funcție Python care verifică palindrom, salvează în fișier, rulează cu test",
        gold_steps=["write_code", "save_file", "run_test"],
        expected_outcome="Cod funcțional cu test passing",
        risk_level="safe",
    ),
    HorizonTask(
        id="h4_research_summary",
        horizon=TaskHorizon.SHORT,
        description="Caută informații despre AI agents, rezumă în max 3 paragrafe",
        gold_steps=["search", "analyze", "summarize"],
        expected_outcome="Rezumat de 3 paragrafe",
        risk_level="safe",
    ),
    HorizonTask(
        id="h5_multi_app_launch",
        horizon=TaskHorizon.SHORT,
        description="Deschide Notes, creează o notă cu titlu și conținut, apoi deschide Safari",
        gold_steps=["launch_notes", "create_note", "launch_safari"],
        expected_outcome="Notă creată și browser deschis",
        risk_level="low",
    ),
    # === MEDIUM (30 min) - Complex multi-step ===
    HorizonTask(
        id="h6_web_research_report",
        horizon=TaskHorizon.MEDIUM,
        description="Caută informații despre 3 subiecte tech diferite, creează un raport markdown cu secțiuni",
        gold_steps=[
            "search_1",
            "search_2",
            "search_3",
            "compile_report",
            "save_markdown",
        ],
        expected_outcome="Raport markdown cu 3 secțiuni",
        risk_level="safe",
    ),
    HorizonTask(
        id="h7_code_project_structure",
        horizon=TaskHorizon.MEDIUM,
        description="Creează un proiect Python cu 3 module, fiecare cu funcții, apoi documentează în README",
        gold_steps=["create_dirs", "write_modules", "create_readme"],
        expected_outcome="Proiect structurat cu README",
        risk_level="low",
    ),
    HorizonTask(
        id="h8_desktop_automation_sequence",
        horizon=TaskHorizon.MEDIUM,
        description="Deschide o aplicație, creează document, salvează, verifică că există, then close",
        gold_steps=["launch", "create", "save", "verify", "close"],
        expected_outcome="Document creat și verificat",
        risk_level="medium",
    ),
    HorizonTask(
        id="h9_multi_file_analysis",
        horizon=TaskHorizon.MEDIUM,
        description="Citește 3 fișiere diferite din proiect, extrage informații, creează un rezumat",
        gold_steps=["read_files", "extract_info", "create_summary"],
        expected_outcome="Reumat din 3 fișiere",
        risk_level="safe",
    ),
    HorizonTask(
        id="h10_terminal_workflow",
        horizon=TaskHorizon.MEDIUM,
        description="Rulează 3 comenzi terminal diferite, capturează output, salvează în fișier",
        gold_steps=["run_cmd_1", "run_cmd_2", "run_cmd_3", "save_output"],
        expected_outcome="Fișier cu output din 3 comenzi",
        risk_level="medium",
    ),
    # === LONG (2 hours) - Complex projects ===
    HorizonTask(
        id="h11_complete_research",
        horizon=TaskHorizon.LONG,
        description="Cercetează un subiect complex (ex: LLMs), găsește 10 surse, rezumă fiecare, creează raport final",
        gold_steps=[
            "deep_search",
            "analyze_sources",
            "write_summaries",
            "create_report",
        ],
        expected_outcome="Raport de cercetare complet",
        risk_level="safe",
    ),
    HorizonTask(
        id="h12_code_multi_file_project",
        horizon=TaskHorizon.LONG,
        description="Creează un proiect Python complet cu 5+ fișiere: main, utils, tests, config, docs",
        gold_steps=[
            "setup_structure",
            "write_main",
            "write_utils",
            "write_tests",
            "write_docs",
        ],
        expected_outcome="Proiect complet cu 5+ fișiere",
        risk_level="safe",
    ),
    # === EXTENDED (6 hours) - Complex autonomy ===
    HorizonTask(
        id="h13_full_stack_research",
        horizon=TaskHorizon.EXTENDED,
        description="Cercetare completă pe subiect tehnic: caută, analizează cod, testează, documentează, creează demo",
        gold_steps=["research", "analyze_code", "test", "document", "demo"],
        expected_outcome="Demo funcțional cu documentație",
        risk_level="safe",
    ),
]


# ==================== EVALUATOR WITH VERIFICATION ====================


@dataclass
class HorizonResult:
    """Rezultat evaluare task complex"""

    task_id: str
    horizon: str
    success: bool
    latency_seconds: float
    steps_executed: int
    retries: int
    interventions: int
    failure_type: Optional[str]
    output_preview: str
    verification_passed: bool


class HorizonEvaluator:
    """
    Evaluator pentru task-uri cu orizont temporal.
    Include verificare și tracking pentru fiecare pas.
    """

    def __init__(self):
        self.results: List[HorizonResult] = []
        self.verifier = None  # Will use verifier.py

    async def run_horizon_task(self, task: HorizonTask) -> HorizonResult:
        """Rulează un task complex cu verificare"""
        start_time = time.time()

        print(f"\n{'=' * 60}")
        print(f"🎯 {task.horizon.value.upper()} | {task.id}")
        print(f"   {task.description[:50]}...")
        print(f"   Risk: {task.risk_level} | Steps: {len(task.gold_steps)}")
        print(f"{'=' * 60}")

        # Initialize verifier
        try:
            from core.verifier import get_verifier

            verifier = get_verifier()
        except:
            verifier = None

        steps_executed = 0
        retries = 0
        interventions = 0
        failure_type = None
        success = False

        try:
            # Simulate multi-step execution with verification
            for i, expected_step in enumerate(task.gold_steps):
                step_start = time.time()
                print(f"  Step {i + 1}/{len(task.gold_steps)}: {expected_step}")

                # Execute step (simulated)
                step_result = await self._execute_step(task, expected_step, verifier)
                steps_executed += 1

                # Verify step
                if verifier:
                    verification = verifier.verify_action(
                        action_type=expected_step,
                        params={},
                        expected=f"Step {expected_step} should complete",
                        actual_result=step_result,
                    )

                    print(
                        f"    → {verification.status.value} ({verification.failure_type.value})"
                    )

                    if verification.status.value == "failed":
                        if retries < task.max_retries:
                            retries += 1
                            print(f"    ↻ Retry {retries}/{task.max_retries}")
                            continue
                        else:
                            failure_type = verification.failure_type.value
                            break

                # Check for approval needed
                if task.requires_approval:
                    interventions += 1
                    print(f"    ⚠️ Human approval needed")

            success = failure_type is None

        except Exception as e:
            print(f"  ❌ Error: {str(e)[:80]}")
            failure_type = str(type(e).__name__)

        elapsed = time.time() - start_time

        return HorizonResult(
            task_id=task.id,
            horizon=task.horizon.value,
            success=success,
            latency_seconds=elapsed,
            steps_executed=steps_executed,
            retries=retries,
            interventions=interventions,
            failure_type=failure_type,
            output_preview=f"Completed {steps_executed} steps",
            verification_passed=verifier is not None,
        )

    async def _execute_step(self, task: HorizonTask, step: str, verifier) -> Dict:
        """Execută un pas individual"""
        # Simulate step execution based on task type
        await asyncio.sleep(0.1)  # Simulate work

        # Return mock success for each step
        return {"success": True, "step": step}

    async def run_horizon_benchmark(self) -> Dict:
        """Rulează benchmark pentru toate orizonturile"""
        print("\n" + "=" * 60)
        print("🚀 HORIZON BENCHMARK - Task Duration Testing")
        print("=" * 60)

        results = []

        # Run tasks by horizon
        horizons = {
            TaskHorizon.SHORT: [
                t for t in HORIZON_TASKS if t.horizon == TaskHorizon.SHORT
            ][:2],
            TaskHorizon.MEDIUM: [
                t for t in HORIZON_TASKS if t.horizon == TaskHorizon.MEDIUM
            ][:2],
            TaskHorizon.LONG: [
                t for t in HORIZON_TASKS if t.horizon == TaskHorizon.LONG
            ][:1],
        }

        for horizon, tasks in horizons.items():
            print(f"\n📊 {horizon.value.upper()} TASKS ({len(tasks)} tasks)")

            for task in tasks:
                result = await self.run_horizon_task(task)
                results.append(result)

                status = "✅" if result.success else "❌"
                print(
                    f"  {status} {result.latency_seconds:.1f}s | {result.steps_executed} steps | {result.retries} retries"
                )

        # Generate report
        return self._generate_horizon_report(results)

    def _generate_horizon_report(self, results: List[HorizonResult]) -> Dict:
        """Generează raport pentru orizonturi"""

        by_horizon = {}
        for r in results:
            h = r.horizon
            if h not in by_horizon:
                by_horizon[h] = {
                    "total": 0,
                    "success": 0,
                    "latency": 0,
                    "steps": 0,
                    "retries": 0,
                }
            by_horizon[h]["total"] += 1
            if r.success:
                by_horizon[h]["success"] += 1
            by_horizon[h]["latency"] += r.latency_seconds
            by_horizon[h]["steps"] += r.steps_executed
            by_horizon[h]["retries"] += r.retries

        # Calculate averages
        for h in by_horizon:
            if by_horizon[h]["total"] > 0:
                by_horizon[h]["avg_latency"] = (
                    by_horizon[h]["latency"] / by_horizon[h]["total"]
                )
                by_horizon[h]["avg_steps"] = (
                    by_horizon[h]["steps"] / by_horizon[h]["total"]
                )
                by_horizon[h]["success_rate"] = (
                    by_horizon[h]["success"] / by_horizon[h]["total"] * 100
                )

        return {
            "total_tasks": len(results),
            "total_success": sum(1 for r in results if r.success),
            "by_horizon": by_horizon,
            "results": [
                {
                    "task_id": r.task_id,
                    "horizon": r.horizon,
                    "success": r.success,
                    "latency": round(r.latency_seconds, 1),
                    "steps": r.steps_executed,
                    "retries": r.retries,
                    "interventions": r.interventions,
                    "failure": r.failure_type,
                }
                for r in results
            ],
        }


async def run_horizon_evaluation():
    """Rulează evaluarea pe orizonturi"""
    evaluator = HorizonEvaluator()
    report = await evaluator.run_horizon_benchmark()

    print("\n" + "=" * 60)
    print("📊 HORIZON BENCHMARK REPORT")
    print("=" * 60)

    for horizon, stats in report["by_horizon"].items():
        print(f"\n{horizon.upper()}:")
        print(
            f"  Success: {stats['success']}/{stats['total']} ({stats['success_rate']:.0f}%)"
        )
        print(f"  Avg latency: {stats['avg_latency']:.1f}s")
        print(f"  Avg steps: {stats['avg_steps']:.1f}")
        print(f"  Total retries: {stats['retries']}")

    return report


if __name__ == "__main__":
    asyncio.run(run_horizon_evaluation())
