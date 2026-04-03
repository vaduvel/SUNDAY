"""Coordinator meta-agent mode built on top of AutoAgents."""

from __future__ import annotations

from typing import Any, Dict, List

from core.auto_agents import AgentRole, AgentSpec, AutoAgentsManager, ProcessType, TaskSpec
from core.ultraplan import UltraPlanner


class CoordinatorMode:
    """Meta-agent that decomposes work and coordinates role-based execution."""

    def __init__(self, auto_agents_manager: AutoAgentsManager, planner: UltraPlanner):
        self.auto_agents_manager = auto_agents_manager
        self.planner = planner

    async def prepare(self, task: str) -> Dict[str, Any]:
        """Create plan + role assignment without executing work."""
        plan = self.planner.build_plan(task)
        roles = self._select_roles(task)
        await self.auto_agents_manager.create_agents(task, roles)

        return {
            "mode": "coordinator",
            "plan": plan,
            "roles": roles,
            "task_specs": [self._task_spec_to_dict(spec) for spec in self._build_task_specs(task, roles)],
        }

    async def execute(self, task: str) -> Dict[str, Any]:
        """Run the coordinator workflow using hierarchical execution."""
        prep = await self.prepare(task)
        task_specs = self._build_task_specs(task, prep["roles"])
        execution = await self.auto_agents_manager.execute_task(
            task,
            tasks=task_specs,
            process=ProcessType.HIERARCHICAL,
        )
        execution["mode"] = "coordinator"
        execution["plan"] = prep["plan"]
        execution["roles"] = prep["roles"]
        execution["task_specs"] = prep["task_specs"]
        return execution

    def status(self) -> Dict[str, Any]:
        """Return current coordinator status."""
        return {
            "mode": "coordinator",
            "auto_agents": self.auto_agents_manager.get_status(),
        }

    def _select_roles(self, task: str) -> List[str]:
        task_lower = task.lower()
        roles = ["Manager"]
        if any(token in task_lower for token in ["research", "analyze", "impact", "detect"]):
            roles.append("Researcher")
        if any(token in task_lower for token in ["implement", "build", "wire", "import", "register"]):
            roles.append("Creator")
        roles.append("Reviewer")
        return list(dict.fromkeys(roles))

    def _build_task_specs(self, task: str, roles: List[str]) -> List[TaskSpec]:
        tasks: List[TaskSpec] = []

        if "Researcher" in roles:
            tasks.append(
                TaskSpec(
                    description=f"Inspect current implementation and identify integration points for: {task}",
                    expected_output="Evidence-backed architecture notes",
                    agent_name="Researcher",
                )
            )

        if "Creator" in roles:
            tasks.append(
                TaskSpec(
                    description=f"Implement the requested changes for: {task}",
                    expected_output="Concrete code or configuration updates",
                    agent_name="Creator",
                    depends_on=["Researcher"] if "Researcher" in roles else [],
                )
            )

        tasks.append(
            TaskSpec(
                description=f"Review execution quality, risks, and missing validation for: {task}",
                expected_output="Review summary with residual risks",
                agent_name="Reviewer",
                depends_on=["Creator"] if "Creator" in roles else [],
            )
        )
        return tasks

    def _task_spec_to_dict(self, spec: TaskSpec) -> Dict[str, Any]:
        return {
            "description": spec.description,
            "expected_output": spec.expected_output,
            "agent_name": spec.agent_name,
            "depends_on": spec.depends_on,
        }
