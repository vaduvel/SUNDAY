"""🤖 JARVIS Auto Agents System
Inspired by PraisonAI: AutoAgents that automatically create and manage AI agents
based on high-level instructions.

Features:
- Auto Agent Creation: Generate agents from high-level task descriptions
- Self-Reflection: Agents can review and improve their own outputs
- Multi-Agent Collaboration: Multiple agents work together
- Hierarchical Process: Manager agent coordinates workers
- Workflow Process: Conditional task execution
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time
import json

logger = logging.getLogger(__name__)


class ProcessType(Enum):
    """Types of multi-agent processes."""

    SEQUENTIAL = "sequential"  # One after another
    HIERARCHICAL = "hierarchical"  # Manager coordinates workers
    WORKFLOW = "workflow"  # Conditional execution
    PARALLEL = "parallel"  # Multiple at once
    EVALUATOR_OPTIMIZER = "evaluator_optimizer"  # Generate + evaluate loop


class AgentRole(Enum):
    """Roles in multi-agent system."""

    MANAGER = "manager"  # Coordinates others
    WORKER = "worker"  # Executes tasks
    RESEARCHER = "researcher"  # Gathers information
    REVIEWER = "reviewer"  # Evaluates outputs
    CREATOR = "creator"  # Creates content


@dataclass
class AgentSpec:
    """Specification for an auto-created agent."""

    name: str
    role: AgentRole
    backstory: str
    goal: str
    instructions: str
    tools: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)


@dataclass
class TaskSpec:
    """Specification for a task."""

    description: str
    expected_output: str
    agent_name: str  # Which agent handles this
    depends_on: List[str] = field(default_factory=list)


@dataclass
class AgentExecution:
    """Result of agent execution."""

    agent_name: str
    output: Any
    success: bool
    error: Optional[str] = None
    execution_time: float = 0.0


class AutoAgent:
    """An automatically created agent that can execute tasks."""

    def __init__(self, spec: AgentSpec, executor: Callable):
        self.spec = spec
        self.executor = executor  # Function that runs LLM calls
        self.execution_history: List[AgentExecution] = []

    async def execute(
        self, task: str, context: Dict[str, Any] = None
    ) -> AgentExecution:
        """Execute a task with this agent."""
        start_time = time.time()

        # Build system prompt from spec
        system_prompt = f"""You are {self.spec.name}.

ROLE: {self.spec.role.value.upper()}
BACKSTORY: {self.spec.backstory}
GOAL: {self.spec.goal}

INSTRUCTIONS: {self.spec.instructions}

CONSTRAINTS:
{chr(10).join(f"- {c}" for c in self.spec.constraints)}

CONTEXT: {json.dumps(context) if context else "No additional context"}
"""

        try:
            output = await self.executor(system_prompt, task)
            execution = AgentExecution(
                agent_name=self.spec.name,
                output=output,
                success=True,
                execution_time=time.time() - start_time,
            )
        except Exception as e:
            execution = AgentExecution(
                agent_name=self.spec.name,
                output=None,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )

        self.execution_history.append(execution)
        return execution

    def reflect(self, task: str, output: str) -> str:
        """Self-reflect on the output and suggest improvements."""
        reflection_prompt = f"""Reflect on your task and output:

Task: {task}
Your Output: {output}

Questions to answer:
1. Did you achieve the goal?
2. What could be improved?
3. What would you do differently next time?

Provide a brief reflection (1-2 sentences).
"""
        return reflection_prompt  # This would be passed to executor in practice


class AutoAgents:
    """System that automatically creates and manages multiple agents."""

    def __init__(self, executor: Callable, max_agents: int = 5):
        self.executor = executor
        self.max_agents = max_agents
        self.agents: Dict[str, AutoAgent] = {}
        self.process_type = ProcessType.SEQUENTIAL

    def create_from_yaml(self, yaml_spec: Dict[str, Any]) -> List[AgentSpec]:
        """Create agents from YAML-like specification (like PraisonAI playbook)."""
        agents = []

        for role_name, role_spec in yaml_spec.get("roles", {}).items():
            # Determine role type
            role_type = AgentRole.WORKER
            if "manager" in role_name.lower():
                role_type = AgentRole.MANAGER
            elif "research" in role_name.lower():
                role_type = AgentRole.RESEARCHER
            elif "review" in role_name.lower():
                role_type = AgentRole.REVIEWER

            spec = AgentSpec(
                name=role_name,
                role=role_type,
                backstory=role_spec.get("backstory", ""),
                goal=role_spec.get("goal", ""),
                instructions=role_spec.get("instructions", ""),
                tools=role_spec.get("tools", []),
                constraints=role_spec.get("constraints", []),
            )
            agents.append(spec)

        return agents

    def create_from_description(self, task_description: str) -> List[AgentSpec]:
        """Automatically create agents based on task description."""
        task_lower = task_description.lower()

        agents = []

        # Research + Create + Review is a common pattern
        if any(w in task_lower for w in ["research", "find", "search", "analyze"]):
            agents.append(
                AgentSpec(
                    name="Researcher",
                    role=AgentRole.RESEARCHER,
                    backstory="Expert at gathering and analyzing information from various sources.",
                    goal="Find relevant information and extract key insights.",
                    instructions="Search thoroughly, verify sources, and compile findings.",
                    tools=["web_search", "file_read", "memory_search"],
                )
            )

        if any(
            w in task_lower for w in ["create", "build", "write", "generate", "make"]
        ):
            agents.append(
                AgentSpec(
                    name="Creator",
                    role=AgentRole.CREATOR,
                    backstory="Creative specialist skilled at producing high-quality content.",
                    goal="Create original content based on requirements.",
                    instructions="Generate original, well-structured content that meets specifications.",
                    tools=["file_write", "code_execute"],
                )
            )

        if any(w in task_lower for w in ["review", "check", "validate", "improve"]):
            agents.append(
                AgentSpec(
                    name="Reviewer",
                    role=AgentRole.REVIEWER,
                    backstory="Quality assurance expert focused on accuracy and completeness.",
                    goal="Review outputs and suggest improvements.",
                    instructions="Check for accuracy, completeness, and quality. Provide constructive feedback.",
                    tools=["file_read", "analysis"],
                )
            )

        # If complex task, add manager
        if len(agents) > 1:
            agents.insert(
                0,
                AgentSpec(
                    name="Manager",
                    role=AgentRole.MANAGER,
                    backstory="Experienced coordinator who orchestrates complex multi-agent workflows.",
                    goal="Coordinate agent activities to achieve the overall task efficiently.",
                    instructions="Assign tasks to agents, review their outputs, and ensure smooth collaboration.",
                    tools=["task_planning", "coordination"],
                ),
            )

        return agents[: self.max_agents]

    async def execute_sequential(self, tasks: List[TaskSpec]) -> List[AgentExecution]:
        """Execute tasks sequentially."""
        results = []
        context = {}

        for task in tasks:
            # Wait for dependencies
            for dep in task.depends_on:
                if dep in context:
                    context[dep] = context[dep]

            agent = self.agents.get(task.agent_name)
            if not agent:
                logger.warning(f"Agent {task.agent_name} not found, skipping task")
                continue

            result = await agent.execute(task.description, context)
            results.append(result)

            if result.success:
                context[task.description[:50]] = result.output

        return results

    async def execute_hierarchical(self, tasks: List[TaskSpec]) -> List[AgentExecution]:
        """Execute with manager coordinating workers."""
        results = []

        # Find manager
        manager = self.agents.get("Manager")
        if not manager:
            # Use first agent as coordinator
            manager = next((a for a in self.agents.values()), None)

        if not manager:
            return []

        # Manager coordinates task distribution
        context = {"tasks": [t.description for t in tasks], "results": []}

        for task in tasks:
            worker = self.agents.get(task.agent_name)
            if not worker:
                continue

            result = await worker.execute(task.description, context)
            results.append(result)

            if result.success:
                context["results"].append(
                    {"task": task.description, "output": result.output}
                )

        return results

    async def execute_parallel(self, tasks: List[TaskSpec]) -> List[AgentExecution]:
        """Execute independent tasks in parallel."""

        async def run_task(task: TaskSpec):
            agent = self.agents.get(task.agent_name)
            if not agent:
                return AgentExecution(
                    agent_name=task.agent_name,
                    output=None,
                    success=False,
                    error="Agent not found",
                )
            return await agent.execute(task.description)

        results = await asyncio.gather(*[run_task(t) for t in tasks])
        return list(results)

    async def execute_evaluator_optimizer(
        self, task: str, max_iterations: int = 3
    ) -> AgentExecution:
        """Execute generator-evaluator loop until acceptable output."""
        generator = self.agents.get("Creator") or next(
            (a for a in self.agents.values()), None
        )
        evaluator = self.agents.get("Reviewer") or next(
            (a for a in self.agents.values()), None
        )

        if not generator:
            return AgentExecution(
                agent_name="EvaluatorOptimizer",
                output=None,
                success=False,
                error="No agents available",
            )

        last_output = None
        last_feedback = "Start generation"

        for i in range(max_iterations):
            # Generate
            gen_result = await generator.execute(task, {"feedback": last_feedback})

            if not gen_result.success:
                return gen_result

            last_output = gen_result.output

            # Evaluate
            if evaluator:
                eval_result = await evaluator.execute(
                    f"Evaluate this output:\n{last_output}", {"task": task}
                )

                if eval_result.success:
                    # Check if acceptable
                    if (
                        "accept" in eval_result.output.lower()
                        or "good" in eval_result.output.lower()
                    ):
                        return AgentExecution(
                            agent_name="EvaluatorOptimizer",
                            output=last_output,
                            success=True,
                            execution_time=gen_result.execution_time
                            + eval_result.execution_time,
                        )

                    last_feedback = eval_result.output
            else:
                # No evaluator, just return first output
                return gen_result

        return AgentExecution(
            agent_name="EvaluatorOptimizer",
            output=last_output,
            success=False,
            error=f"Max iterations ({max_iterations}) reached without acceptance",
        )

    async def execute(
        self, tasks: List[TaskSpec], process_type: ProcessType = None
    ) -> List[AgentExecution]:
        """Execute tasks based on process type."""
        process_type = process_type or self.process_type

        if process_type == ProcessType.SEQUENTIAL:
            return await self.execute_sequential(tasks)
        elif process_type == ProcessType.HIERARCHICAL:
            return await self.execute_hierarchical(tasks)
        elif process_type == ProcessType.PARALLEL:
            return await self.execute_parallel(tasks)
        elif process_type == ProcessType.EVALUATOR_OPTIMIZER:
            return (
                [await self.execute_evaluator_optimizer(tasks[0].description)]
                if tasks
                else []
            )
        else:
            return await self.execute_sequential(tasks)

    def add_agent(self, spec: AgentSpec):
        """Manually add an agent."""
        agent = AutoAgent(spec, self.executor)
        self.agents[spec.name] = agent

    def get_agent(self, name: str) -> Optional[AutoAgent]:
        """Get agent by name."""
        return self.agents.get(name)


class AutoAgentsManager:
    """High-level manager for AutoAgents with LLM integration."""

    def __init__(self, llm_executor: Callable):
        self.llm_executor = llm_executor
        self.auto_agents: Optional[AutoAgents] = None

    async def create_agents(self, topic: str, roles: List[str] = None) -> AutoAgents:
        """Create agents for a topic."""
        auto_agents = AutoAgents(self._wrap_executor, max_agents=5)

        if roles:
            # Create from specified roles
            for role in roles:
                role_lower = role.lower()
                role_type = AgentRole.WORKER
                if "manager" in role_lower:
                    role_type = AgentRole.MANAGER
                elif "research" in role_lower:
                    role_type = AgentRole.RESEARCHER
                elif "review" in role_lower:
                    role_type = AgentRole.REVIEWER
                elif "create" in role_lower:
                    role_type = AgentRole.CREATOR
                spec = AgentSpec(
                    name=role,
                    role=role_type,
                    backstory=f"Expert in {topic}",
                    goal=f"Handle {role} tasks related to {topic}",
                    instructions=f"You are responsible for {role} work.",
                )
                auto_agents.add_agent(spec)
        else:
            # Auto-create from topic
            specs = auto_agents.create_from_description(f"Work on {topic}")
            for spec in specs:
                auto_agents.add_agent(spec)

        self.auto_agents = auto_agents
        return auto_agents

    async def _wrap_executor(self, system_prompt: str, user_prompt: str) -> str:
        """Wrap LLM executor for AutoAgent."""
        return await self.llm_executor(system_prompt, user_prompt)

    async def execute_task(
        self, task: str, tasks: List[TaskSpec] = None, process: ProcessType = None
    ) -> Dict[str, Any]:
        """Execute a task with auto-agents."""
        if not self.auto_agents:
            await self.create_agents(task)

        if not tasks:
            # Auto-create tasks from main task
            specs = self.auto_agents.create_from_description(task)
            # For now, assume single task
            tasks = [
                TaskSpec(
                    description=task,
                    expected_output="Complete task output",
                    agent_name=specs[0].name if specs else "Creator",
                )
            ]

        results = await self.auto_agents.execute(
            tasks, process or ProcessType.SEQUENTIAL
        )

        return {
            "success": all(r.success for r in results),
            "results": [
                {
                    "agent": r.agent_name,
                    "output": r.output,
                    "success": r.success,
                    "error": r.error,
                }
                for r in results
            ],
        }

    def get_status(self) -> Dict[str, Any]:
        """Get auto-agents status."""
        if not self.auto_agents:
            return {"status": "Not initialized"}

        return {
            "status": "Active",
            "num_agents": len(self.auto_agents.agents),
            "process_type": self.auto_agents.process_type.value,
            "agents": list(self.auto_agents.agents.keys()),
        }


# Example usage
if __name__ == "__main__":
    import asyncio

    async def test():
        # Mock LLM executor
        async def mock_executor(system: str, user: str) -> str:
            await asyncio.sleep(0.1)
            return f"Processed: {user[:50]}"

        manager = AutoAgentsManager(mock_executor)

        # Auto-create agents from task
        await manager.create_agents("Create a report about AI")

        print(f"Status: {manager.get_status()}")

        # Execute task
        result = await manager.execute_task(
            "Research AI trends and create a summary report"
        )

        print(f"Result: {result}")

    asyncio.run(test())
