"""Structured episodic memory for J.A.R.V.I.S."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EpisodeRecord:
    """A structured mission episode."""

    episode_id: str
    mission_id: str
    task: str
    mission_type: str
    status: str
    learning: str
    failures: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    strategy: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    error: Optional[str] = None
    recorded_at: str = field(default_factory=lambda: datetime.now().isoformat())


class EpisodicMemory:
    """Records outcomes and replays failure/strategy patterns."""

    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self.logs_file = os.path.join(vault_path, "🧠_POST_MORTEM_LOGS.md")
        self.episodes_file = os.path.join(vault_path, "episodic_memory.jsonl")
        self._ensure_logs_exist()

    def _ensure_logs_exist(self) -> None:
        os.makedirs(self.vault_path, exist_ok=True)
        if not os.path.exists(self.logs_file):
            with open(self.logs_file, "w", encoding="utf-8") as handle:
                handle.write("# 🧠 J.A.R.V.I.S. Post-Mortem & Lessons Learned\n")
                handle.write(
                    "A record of every mission's outcome to avoid technical regressions.\n\n"
                )
        if not os.path.exists(self.episodes_file):
            with open(self.episodes_file, "w", encoding="utf-8"):
                pass

    def record_episode(
        self,
        mission: Dict[str, Any] | str,
        metrics: Optional[Dict[str, Any] | str] = None,
        failures: Optional[List[str] | str] = None,
        error: Optional[str] = None,
        status: Optional[str] = None,
        learning: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record either the new structured episode format or the legacy signature."""
        payload = self._normalize_episode_payload(
            mission=mission,
            metrics=metrics,
            failures=failures,
            error=error,
            status=status,
            learning=learning,
        )
        record = EpisodeRecord(**payload)

        logger.info("💾 [EPISODIC] Recording outcome for: %s", record.task[:60])
        with open(self.episodes_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

        self._append_markdown_record(record)
        return asdict(record)

    def find_similar_failures(
        self, task_ctx: Dict[str, Any], limit: int = 5
    ) -> List[Dict[str, Any]]:
        desired_failures = {
            str(code).lower()
            for code in (
                task_ctx.get("failures")
                or task_ctx.get("failure_codes")
                or task_ctx.get("recent_failures")
                or []
            )
        }
        mission_type = str(task_ctx.get("mission_type") or "").lower()
        keywords = self._keyword_set(task_ctx)
        matches: List[tuple[int, Dict[str, Any]]] = []

        for episode in self._load_episodes():
            score = 0
            episode_failures = {item.lower() for item in episode.get("failures", [])}
            if desired_failures and desired_failures & episode_failures:
                score += 5 * len(desired_failures & episode_failures)
            if mission_type and mission_type == str(episode.get("mission_type", "")).lower():
                score += 2
            overlap = keywords & self._keyword_set(episode)
            score += min(3, len(overlap))
            if score > 0 and episode_failures:
                item = dict(episode)
                item["match_score"] = score
                matches.append((score, item))

        matches.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in matches[:limit]]

    def get_best_known_strategy(self, task_ctx: Dict[str, Any]) -> Dict[str, Any] | None:
        mission_type = str(task_ctx.get("mission_type") or "").lower()
        keywords = self._keyword_set(task_ctx)
        candidates: List[tuple[float, Dict[str, Any]]] = []

        for episode in self._load_episodes():
            if str(episode.get("status", "")).upper() != "SUCCESS":
                continue
            score = 0.0
            if mission_type and mission_type == str(episode.get("mission_type", "")).lower():
                score += 2.0
            overlap = keywords & self._keyword_set(episode)
            score += float(min(3, len(overlap)))
            quality = float(episode.get("metrics", {}).get("quality_score") or 0.0)
            score += quality / 10.0
            if score <= 0:
                continue
            candidates.append((score, episode))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        score, best = candidates[0]
        return {
            "episode_id": best.get("episode_id"),
            "mission_id": best.get("mission_id"),
            "task": best.get("task"),
            "strategy": best.get("strategy") or best.get("learning"),
            "learning": best.get("learning"),
            "match_score": score,
        }

    def get_recent_learnings(self, limit: int = 5) -> str:
        episodes = self._load_episodes()
        learnings = [episode.get("learning", "") for episode in episodes if episode.get("learning")]
        return "\n".join(learnings[-limit:]) or "No previous patterns found."

    def _append_markdown_record(self, record: EpisodeRecord) -> None:
        status_emoji = "✅ SUCCESS" if record.status.upper() == "SUCCESS" else "🚨 FAILURE"
        entry = [
            f"## [{record.recorded_at}] {record.task[:80]}",
            f"- **Status**: {status_emoji}",
            f"- **Key Learning**: {record.learning}",
        ]
        if record.strategy:
            entry.append(f"- **Best Strategy**: {record.strategy}")
        if record.failures:
            entry.append(f"- **Failure Pattern**: {', '.join(record.failures)}")
        if record.error:
            entry.append(f"- **Principal Error**: `{record.error}`")
        entry.append("---")
        with open(self.logs_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(entry) + "\n")

    def _load_episodes(self) -> List[Dict[str, Any]]:
        episodes: List[Dict[str, Any]] = []
        if not os.path.exists(self.episodes_file):
            return episodes
        with open(self.episodes_file, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    episodes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return episodes

    def _keyword_set(self, payload: Dict[str, Any]) -> set[str]:
        pieces: List[str] = []
        for key, value in payload.items():
            if isinstance(value, str):
                pieces.extend(value.lower().split())
            elif isinstance(value, list):
                pieces.extend(str(item).lower() for item in value)
            elif isinstance(value, dict):
                pieces.extend(str(item).lower() for item in value.values())
        return {item.strip(".,:;()[]{}") for item in pieces if item}

    def _normalize_episode_payload(
        self,
        mission: Dict[str, Any] | str,
        metrics: Optional[Dict[str, Any] | str],
        failures: Optional[List[str] | str],
        error: Optional[str],
        status: Optional[str],
        learning: Optional[str],
    ) -> Dict[str, Any]:
        import uuid

        if isinstance(mission, dict):
            task = str(mission.get("task") or mission.get("user_input") or mission.get("goal") or "Unknown mission")
            mission_id = str(mission.get("mission_id") or f"episode_{uuid.uuid4().hex[:8]}")
            mission_type = str(mission.get("mission_type") or "general")
            episode_status = str(mission.get("status") or status or "UNKNOWN")
            episode_learning = str(
                mission.get("learning")
                or learning
                or mission.get("strategy")
                or "No explicit learning recorded."
            )
            failure_list = list(mission.get("failures") or failures or [])
            metrics_dict = metrics if isinstance(metrics, dict) else dict(mission.get("metrics") or {})
            tags = list(mission.get("tags") or [])
            strategy = mission.get("strategy")
            error_value = error or mission.get("error")
        else:
            task = str(mission)
            mission_id = f"episode_{uuid.uuid4().hex[:8]}"
            mission_type = "general"
            episode_status = str(status or metrics or "UNKNOWN")
            episode_learning = str(learning or failures or "No explicit learning recorded.")
            failure_list = [error] if error else []
            metrics_dict = {}
            tags = []
            strategy = None
            error_value = error

        return {
            "episode_id": f"episode_{uuid.uuid4().hex[:8]}",
            "mission_id": mission_id,
            "task": task,
            "mission_type": mission_type,
            "status": episode_status,
            "learning": episode_learning,
            "failures": [str(item) for item in failure_list if item],
            "metrics": dict(metrics_dict or {}),
            "strategy": strategy,
            "tags": tags,
            "error": error_value,
        }


if __name__ == "__main__":
    memory = EpisodicMemory(vault_path=".")
    memory.record_episode(
        {"task": "Optimize XML generator", "status": "SUCCESS", "learning": "Prefer lxml."}
    )
    print(memory.get_recent_learnings(1))
