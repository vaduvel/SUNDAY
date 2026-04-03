"""Async Trigger Graph — Lava/neuromorphic-inspired sparse async maintenance.

Background brain work (memory consolidation, skill scoring, log compaction)
runs OFF the hot path, triggered by events — not on a fixed timer.

Upgrade of core/kairos_engine.py: event-driven instead of every-5-minutes polling.

Inspired by: Intel Lava (neuromorphic asynchronous graph execution)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# ── Trigger conditions ────────────────────────────────────────────

class TriggerCondition(str):
    pass

MISSION_COMPLETE   = TriggerCondition("mission_complete")
ANOMALY_DETECTED   = TriggerCondition("anomaly_detected")
MEMORY_THRESHOLD   = TriggerCondition("memory_threshold")
IDLE_TIMEOUT       = TriggerCondition("idle_timeout")
SKILL_PROMOTED     = TriggerCondition("skill_promoted")
ERROR_BURST        = TriggerCondition("error_burst")
PERIODIC_COMPACT   = TriggerCondition("periodic_compact")


# ── Graph node (a maintenance task) ──────────────────────────────

@dataclass
class TriggerNode:
    name: str
    triggers: list[TriggerCondition]
    handler: Callable[..., Awaitable[None]]
    cooldown_sec: float = 30.0      # min seconds between runs
    max_duration_sec: float = 60.0  # timeout for handler
    last_run: float = 0.0
    run_count: int = 0
    error_count: int = 0

    def is_ready(self, event: TriggerCondition) -> bool:
        if event not in self.triggers:
            return False
        return (time.time() - self.last_run) >= self.cooldown_sec

    async def run(self, context: dict[str, Any]) -> None:
        try:
            self.last_run = time.time()
            self.run_count += 1
            await asyncio.wait_for(
                self.handler(context),
                timeout=self.max_duration_sec,
            )
            logger.debug(f"[AsyncTriggerGraph] {self.name} completed (run #{self.run_count})")
        except asyncio.TimeoutError:
            self.error_count += 1
            logger.warning(f"[AsyncTriggerGraph] {self.name} timed out after {self.max_duration_sec}s")
        except Exception as exc:
            self.error_count += 1
            logger.warning(f"[AsyncTriggerGraph] {self.name} error: {exc}")


# ── Main class ───────────────────────────────────────────────────

class AsyncTriggerGraph:
    """
    Event-driven sparse background maintenance graph.

    Registers maintenance tasks (nodes) with trigger conditions.
    When an event fires, only nodes subscribed to that event run —
    and only if their cooldown has elapsed.

    Usage:
        graph = AsyncTriggerGraph()

        @graph.register([MISSION_COMPLETE], cooldown_sec=10)
        async def consolidate_memory(ctx):
            await memory.consolidate()

        # fire an event (non-blocking)
        graph.fire(MISSION_COMPLETE, {"mission_id": "xyz"})

        # or await completion
        await graph.fire_and_wait(MISSION_COMPLETE, {"mission_id": "xyz"})
    """

    def __init__(self):
        self.nodes: list[TriggerNode] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._loop_task: asyncio.Task | None = None
        self._running = False
        self._idle_deadline: float = 0.0
        self._idle_timeout_sec: float = 120.0   # fire IDLE after 2min of no events

    # ── registration ─────────────────────────────────────────────

    def register(
        self,
        triggers: list[TriggerCondition],
        cooldown_sec: float = 30.0,
        max_duration_sec: float = 60.0,
    ):
        """Decorator to register an async handler."""
        def decorator(fn: Callable[..., Awaitable[None]]) -> Callable:
            node = TriggerNode(
                name=fn.__name__,
                triggers=triggers,
                handler=fn,
                cooldown_sec=cooldown_sec,
                max_duration_sec=max_duration_sec,
            )
            self.nodes.append(node)
            logger.debug(f"[AsyncTriggerGraph] Registered: {fn.__name__} → {triggers}")
            return fn
        return decorator

    def add_node(self, node: TriggerNode) -> None:
        self.nodes.append(node)

    # ── firing ───────────────────────────────────────────────────

    def fire(self, event: TriggerCondition, context: dict[str, Any] | None = None) -> None:
        """Non-blocking fire — queues event for background processing."""
        self._idle_deadline = time.time() + self._idle_timeout_sec
        try:
            self._queue.put_nowait((event, context or {}))
        except asyncio.QueueFull:
            logger.warning(f"[AsyncTriggerGraph] Queue full, dropping event: {event}")

    async def fire_and_wait(
        self,
        event: TriggerCondition,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Fire and await all triggered nodes."""
        ctx = context or {}
        tasks = []
        for node in self.nodes:
            if node.is_ready(event):
                tasks.append(asyncio.create_task(node.run(ctx)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background event loop."""
        if self._running:
            return
        self._running = True
        self._idle_deadline = time.time() + self._idle_timeout_sec
        self._loop_task = asyncio.create_task(self._loop())
        logger.info("[AsyncTriggerGraph] Started")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("[AsyncTriggerGraph] Stopped")

    # ── internal loop ────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                # wait for event with timeout for idle detection
                try:
                    event, context = await asyncio.wait_for(
                        self._queue.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    # check idle
                    if time.time() >= self._idle_deadline:
                        await self._dispatch(IDLE_TIMEOUT, {})
                        self._idle_deadline = time.time() + self._idle_timeout_sec
                    continue

                await self._dispatch(event, context)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[AsyncTriggerGraph] Loop error: {exc}")
                await asyncio.sleep(1)

    async def _dispatch(
        self, event: TriggerCondition, context: dict[str, Any]
    ) -> None:
        """Run all nodes subscribed to this event (concurrently)."""
        ready_nodes = [n for n in self.nodes if n.is_ready(event)]
        if not ready_nodes:
            return

        logger.debug(
            f"[AsyncTriggerGraph] Dispatching {event} → "
            f"{[n.name for n in ready_nodes]}"
        )
        tasks = [asyncio.create_task(node.run(context)) for node in ready_nodes]
        await asyncio.gather(*tasks, return_exceptions=True)

    # ── stats ────────────────────────────────────────────────────

    def stats(self) -> list[dict]:
        return [
            {
                "name": n.name,
                "triggers": list(n.triggers),
                "run_count": n.run_count,
                "error_count": n.error_count,
                "last_run": n.last_run,
                "cooldown_sec": n.cooldown_sec,
            }
            for n in self.nodes
        ]
