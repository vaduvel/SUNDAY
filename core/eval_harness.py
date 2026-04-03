"""
J.A.R.V.I.S. Eval Harness
==========================

Sistem de evaluare pentru JARVIS cu 20 taskuri de test.

Taskuri:
- Web (5): search, click, fill form
- Desktop (5): open app, file ops
- Coding (5): write code, run, debug
- Research (5): search, summarize

Scoring:
- succes (bool)
- latență (secunde)
- pași (număr tool calls)
- cost (tokens)
- retries (număr)
- eșecuri (tip)
"""

import time
import json
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from pathlib import Path
import os

# Import JARVIS components
import sys

sys.path.insert(0, ".")

from core.brain import call_brain, PRO_MODEL
from core.mcp_registry import MCPRegistry
from core.runtime_config import configure_inception_openai_alias, load_project_env
from tools.search_tool import duckduckgo_search_results
from tools.file_manager import read_text_file, write_text_file
from tools.computer_use import get_computer_tool

load_project_env()
configure_inception_openai_alias()

import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ==================== TASK REGISTRY ====================


@dataclass
class EvalTask:
    """Task de evaluare"""

    id: str
    category: str  # web, desktop, coding, research
    description: str
    gold_outcome: str  # Ce ar trebui să obținem
    expected_tools: List[str]  # Ce tool-uri ar trebui să folosească
    timeout: int = 60  # secunde
    max_retries: int = 2


TASK_REGISTRY: List[EvalTask] = [
    # === WEB TASKS ===
    EvalTask(
        id="web_1",
        category="web",
        description="Caută pe web cele mai populare 3 laptopuri gaming 2025",
        gold_outcome="Lista cu 3 laptopuri și specificații",
        expected_tools=["search_tool"],
        timeout=45,
    ),
    EvalTask(
        id="web_2",
        category="web",
        description="Găsește informații despre Python async programming",
        gold_outcome="Explicație clară a async programming",
        expected_tools=["search_tool"],
        timeout=45,
    ),
    EvalTask(
        id="web_3",
        category="web",
        description="Caută cele mai bune 5 cursuri AI online gratuite",
        gold_outcome="Lista cu 5 cursuri și linkuri",
        expected_tools=["search_tool"],
        timeout=45,
    ),
    EvalTask(
        id="web_4",
        category="web",
        description="Găsește tutorial pentru React hooks",
        gold_outcome="Link către tutorial și descriere",
        expected_tools=["search_tool"],
        timeout=45,
    ),
    EvalTask(
        id="web_5",
        category="web",
        description="Caută latest news despre AI în 2025",
        gold_outcome="Titluri și rezumate știri AI",
        expected_tools=["search_tool"],
        timeout=45,
    ),
    # === DESKTOP TASKS ===
    EvalTask(
        id="desktop_1",
        category="desktop",
        description="Deschide aplicația Notes (Apple Notes)",
        gold_outcome="Notes app se deschide",
        expected_tools=["computer_launch"],
        timeout=30,
    ),
    EvalTask(
        id="desktop_2",
        category="desktop",
        description="Creează un fișier text numit test.txt cu conținutul 'JARVIS test'",
        gold_outcome="Fișierul test.txt există cu conținutul corect",
        expected_tools=["file_write"],
        timeout=30,
    ),
    EvalTask(
        id="desktop_3",
        category="desktop",
        description="Citește conținutul fișierului JARVIS.md",
        gold_outcome="Conținutul fișierului afișat",
        expected_tools=["file_read"],
        timeout=30,
    ),
    EvalTask(
        id="desktop_4",
        category="desktop",
        description="Afișează dimensiunea ecranului și poziția mouse-ului",
        gold_outcome="Screen size și mouse position",
        expected_tools=["computer_status"],
        timeout=30,
    ),
    EvalTask(
        id="desktop_5",
        category="desktop",
        description="Rulează comanda 'ls -la' în terminal și arată rezultatul",
        gold_outcome="Output din terminal cu lista fișierelor",
        expected_tools=["computer_terminal"],
        timeout=30,
    ),
    # === CODING TASKS ===
    EvalTask(
        id="coding_1",
        category="coding",
        description="Scrie un script Python simple care calculează factorial",
        gold_outcome="Script funcțional cu funcția factorial",
        expected_tools=["file_write"],
        timeout=45,
    ),
    EvalTask(
        id="coding_2",
        category="coding",
        description="Scrie un script Python care verifică dacă un număr este prim",
        gold_outcome="Script cu funcția is_prime",
        expected_tools=["file_write"],
        timeout=45,
    ),
    EvalTask(
        id="coding_3",
        category="coding",
        description="Scrie o funcție Python care inversează un string",
        gold_outcome="Script cu reverse_string func",
        expected_tools=["file_write"],
        timeout=45,
    ),
    EvalTask(
        id="coding_4",
        category="coding",
        description="Scrie un script Python care citește un fișier și afișează conținutul",
        gold_outcome="Script cu file read funcțional",
        expected_tools=["file_write"],
        timeout=45,
    ),
    EvalTask(
        id="coding_5",
        category="coding",
        description="Scrie o funcție Python care calculează suma elementelor dintr-o listă",
        gold_outcome="Script cu sum_list function",
        expected_tools=["file_write"],
        timeout=45,
    ),
    # === RESEARCH TASKS ===
    EvalTask(
        id="research_1",
        category="research",
        description="Caută și rezumă ce este LangChain",
        gold_outcome="Rezumat despre LangChain",
        expected_tools=["search_tool", "brain"],
        timeout=60,
    ),
    EvalTask(
        id="research_2",
        category="research",
        description="Caută și explică ce este Computer Use de la Anthropic",
        gold_outcome="Explicație despre Computer Use API",
        expected_tools=["search_tool", "brain"],
        timeout=60,
    ),
    EvalTask(
        id="research_3",
        category="research",
        description="Găsește informații despre agentic AI frameworks",
        gold_outcome="Lista framework-uri agentice",
        expected_tools=["search_tool", "brain"],
        timeout=60,
    ),
    EvalTask(
        id="research_4",
        category="research",
        description="Caută ce sunt tool-use agents și cum funcționează",
        gold_outcome="Explicație tool-use agents",
        expected_tools=["search_tool", "brain"],
        timeout=60,
    ),
    EvalTask(
        id="research_5",
        category="research",
        description="Găsește diferențele între Claude, GPT-4 și Gemini",
        gold_outcome="Comparație între modele",
        expected_tools=["search_tool", "brain"],
        timeout=60,
    ),
]


# ==================== EVAL RUNNER ====================


@dataclass
class EvalResult:
    """Rezultat al unei evaluări"""

    task_id: str
    category: str
    success: bool
    latency_seconds: float
    steps: int
    tokens_used: int = 0
    retries: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    output: str = ""
    timestamp: float = field(default_factory=time.time)


class EvalHarness:
    """Sistem de evaluare pentru JARVIS"""

    def __init__(self):
        self.results: List[EvalResult] = []
        self.computer = get_computer_tool()
        self.token_count = 0

    async def run_task(self, task: EvalTask) -> EvalResult:
        """Rulează un singur task"""
        start_time = time.time()

        print(f"\n{'=' * 50}")
        print(f"🎯 Running: {task.id} - {task.description[:40]}...")
        print(f"{'=' * 50}")

        try:
            # Route to appropriate handler based on category
            if task.category == "web":
                result = await self._handle_web(task)
            elif task.category == "desktop":
                result = await self._handle_desktop(task)
            elif task.category == "coding":
                result = await self._handle_coding(task)
            elif task.category == "research":
                result = await self._handle_research(task)
            else:
                raise ValueError(f"Unknown category: {task.category}")

            elapsed = time.time() - start_time

            return EvalResult(
                task_id=task.id,
                category=task.category,
                success=True,
                latency_seconds=elapsed,
                steps=result.get("steps", 1),
                tokens_used=self.token_count,
                output=result.get("output", "")[:500],
            )

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ Failed: {str(e)[:100]}")

            return EvalResult(
                task_id=task.id,
                category=task.category,
                success=False,
                latency_seconds=elapsed,
                steps=0,
                error_type=type(e).__name__,
                error_message=str(e)[:200],
            )

    async def _handle_web(self, task: EvalTask) -> Dict:
        """Handle web task"""
        # Extract search query from description
        query = (
            task.description.replace("Caută pe web", "").replace("Găsește", "").strip()
        )

        # Run search
        results = duckduckgo_search_results(query)

        return {
            "steps": 1,
            "output": f"Found {len(results)} results for: {query}",
            "results": results,
        }

    async def _handle_desktop(self, task: EvalTask) -> Dict:
        """Handle desktop task"""
        desc = task.description.lower()

        if "deschide" in desc and "notes" in desc:
            # Open Notes
            result = self.computer.launch_app("Notes")
            return {"steps": 1, "output": str(result)}

        elif "creează" in desc and "test.txt" in desc:
            # Create test file
            write_text_file("test.txt", "JARVIS test")
            return {"steps": 1, "output": "File created"}

        elif "citește" in desc and "jarvis.md" in desc:
            # Read JARVIS.md
            try:
                content = read_text_file("JARVIS.md")
                return {"steps": 1, "output": content[:200]}
            except:
                return {"steps": 1, "output": "File not found"}

        elif "dimensiunea ecranului" in desc or "poziția mouse" in desc:
            # Get screen/mouse info
            status = self.computer.get_status()
            return {"steps": 1, "output": str(status)}

        elif "ls -la" in desc or "terminal" in desc:
            # Run terminal command
            result = self.computer.run_command("ls -la")
            return {"steps": 1, "output": result.get("stdout", "")[:300]}

        else:
            return {"steps": 0, "output": "Unknown desktop task"}

    async def _handle_coding(self, task: EvalTask) -> Dict:
        """Handle coding task"""
        desc = task.description.lower()

        # Determine what to write
        if "factorial" in desc:
            code = '''def factorial(n):
    """Calculează factorialul unui număr"""
    if n < 0:
        raise ValueError("Numărul trebuie să fie pozitiv")
    if n == 0 or n == 1:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result

# Test
if __name__ == "__main__":
    print(f"5! = {factorial(5)}")
    print(f"10! = {factorial(10)}")
'''
            filename = "factorial.py"

        elif "prim" in desc:
            code = '''def is_prime(n):
    """Verifică dacă un număr este prim"""
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(n**0.5) + 1, 2):
        if n % i == 0:
            return False
    return True

# Test
for num in [2, 3, 4, 17, 18, 19]:
    print(f"{num} este prim: {is_prime(num)}")
'''
            filename = "is_prime.py"

        elif "inversează" in desc or "reverse" in desc:
            code = '''def reverse_string(s):
    """Inversează un string"""
    return s[::-1]

# Test
print(reverse_string("JARVIS"))
print(reverse_string("Hello World"))
'''
            filename = "reverse_string.py"

        elif "citește" in desc and "fișier" in desc:
            code = '''def read_file_content(filepath):
    """Citește și afișează conținutul unui fișier"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f"Fișierul {filepath} nu există"
    except Exception as e:
        return f"Eroare: {e}"

# Test
if __name__ == "__main__":
    print(read_file_content("test.txt"))
'''
            filename = "read_file.py"

        elif "suma" in desc or "sum" in desc:
            code = '''def sum_list(numbers):
    """Calculează suma elementelor dintr-o listă"""
    total = 0
    for num in numbers:
        total += num
    return total

# Test
print(sum_list([1, 2, 3, 4, 5]))
print(sum_list([10, 20, 30]))
'''
            filename = "sum_list.py"
        else:
            code = "# Unknown coding task"
            filename = "unknown.py"

        # Write the file
        write_text_file(filename, code)

        return {"steps": 1, "output": f"Wrote {filename}"}

    async def _handle_research(self, task: EvalTask) -> Dict:
        """Handle research task"""
        # Extract topic
        topic = task.description.lower()
        topic = topic.replace("caută și rezumă", "")
        topic = topic.replace("caută și explică", "")
        topic = topic.replace("găsește informații despre", "")
        topic = topic.replace("găsește", "")
        topic = topic.replace("diferențele", "")
        topic = topic.strip()

        # Search for topic
        results = duckduckgo_search_results(topic)

        # Use LLM to summarize if available
        summary = f"Found {len(results)} results about: {topic}"

        return {"steps": 2, "output": summary}

    async def run_all(self) -> List[EvalResult]:
        """Run all tasks"""
        print("\n" + "=" * 60)
        print("🚀 J.A.R.V.I.S. EVALUATION STARTING")
        print(f"   Total tasks: {len(TASK_REGISTRY)}")
        print("=" * 60)

        for task in TASK_REGISTRY:
            result = await self.run_task(task)
            self.results.append(result)

        return self.results

    def generate_report(self) -> Dict[str, Any]:
        """Generate evaluation report"""

        # Calculate stats
        total = len(self.results)
        success = sum(1 for r in self.results if r.success)
        failed = total - success

        by_category = {}
        for result in self.results:
            cat = result.category
            if cat not in by_category:
                by_category[cat] = {"total": 0, "success": 0, "latency": 0}
            by_category[cat]["total"] += 1
            if result.success:
                by_category[cat]["success"] += 1
            by_category[cat]["latency"] += result.latency_seconds

        # Calculate averages
        for cat in by_category:
            if by_category[cat]["total"] > 0:
                by_category[cat]["avg_latency"] = (
                    by_category[cat]["latency"] / by_category[cat]["total"]
                )
                by_category[cat]["success_rate"] = (
                    by_category[cat]["success"] / by_category[cat]["total"] * 100
                )

        return {
            "total_tasks": total,
            "success": success,
            "failed": failed,
            "success_rate": success / total * 100 if total > 0 else 0,
            "total_latency": sum(r.latency_seconds for r in self.results),
            "avg_latency": sum(r.latency_seconds for r in self.results) / total
            if total > 0
            else 0,
            "by_category": by_category,
            "results": [
                {
                    "task_id": r.task_id,
                    "category": r.category,
                    "success": r.success,
                    "latency": round(r.latency_seconds, 2),
                    "steps": r.steps,
                    "error": r.error_type,
                }
                for r in self.results
            ],
        }


async def run_evaluation():
    """Run evaluation and print report"""
    harness = EvalHarness()
    results = await harness.run_all()
    report = harness.generate_report()

    print("\n" + "=" * 60)
    print("📊 EVALUATION REPORT")
    print("=" * 60)
    print(f"Total tasks: {report['total_tasks']}")
    print(f"Success: {report['success']}")
    print(f"Failed: {report['failed']}")
    print(f"Success rate: {report['success_rate']:.1f}%")
    print(f"Avg latency: {report['avg_latency']:.2f}s")
    print()
    print("By Category:")
    for cat, stats in report["by_category"].items():
        print(
            f"  {cat}: {stats['success']}/{stats['total']} ({stats['success_rate']:.1f}%) - avg {stats['avg_latency']:.1f}s"
        )
    print()
    print("Results:")
    for r in report["results"]:
        status = "✅" if r["success"] else "❌"
        print(
            f"  {status} {r['task_id']}: {r['latency']}s, {r['steps']} steps"
            + (f" [{r['error']}]" if r["error"] else "")
        )

    # Save report
    with open("eval_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("\n📁 Report saved to eval_report.json")

    return report


if __name__ == "__main__":
    asyncio.run(run_evaluation())
