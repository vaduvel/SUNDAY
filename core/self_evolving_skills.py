"""🧬 JARVIS Self-Evolving Skills Engine
Inspired by OpenSpace: Skills that learn and improve automatically.

Three Evolution Modes:
- FIX: Repair broken/outdated instructions in-place
- DERIVED: Create enhanced versions from parent skills
- CAPTURED: Extract novel reusable patterns from successful executions

Three Triggers:
- Post-Execution Analysis: After every task
- Tool Degradation: When tool success rates drop
- Metric Monitor: Periodically scan skill health
"""

import os
import sqlite3
import json
import hashlib
import time
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class SkillRecord:
    """A skill that can evolve over time."""

    id: str
    name: str
    description: str
    content: str  # The actual skill content (markdown/SKILL.md style)
    version: int = 1
    parent_id: Optional[str] = None
    evolution_type: str = "CAPTURED"  # FIX, DERIVED, CAPTURED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    success_count: int = 0
    failure_count: int = 0
    applied_count: int = 0
    fallback_count: int = 0
    tags: List[str] = field(default_factory=list)
    quality_score: float = 0.5  # 0-1, calculated from success/failure
    family_id: Optional[str] = None
    lifecycle_state: str = "ACTIVE"  # ACTIVE, CANDIDATE, PROBATION, SUPERSEDED, ROLLED_BACK
    baseline_score: float = 0.0
    last_eval_score: float = 0.0
    promoted_at: Optional[str] = None
    rollback_reason: Optional[str] = None
    proposal_id: Optional[str] = None
    last_gate_decision: Optional[str] = None


@dataclass
class EvolutionSuggestion:
    """A suggested skill evolution."""

    skill_id: str
    evolution_type: str  # FIX, DERIVED, CAPTURED
    reason: str
    evidence: Dict[str, Any]  # Execution data that triggered this


class SkillStore:
    """SQLite-backed skill persistence with version DAG."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        """Initialize skill database schema."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                content TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                parent_id TEXT,
                evolution_type TEXT DEFAULT 'CAPTURED',
                created_at TEXT,
                last_used TEXT,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                applied_count INTEGER DEFAULT 0,
                fallback_count INTEGER DEFAULT 0,
                tags TEXT,
                quality_score REAL DEFAULT 0.5,
                family_id TEXT,
                lifecycle_state TEXT DEFAULT 'ACTIVE',
                baseline_score REAL DEFAULT 0.0,
                last_eval_score REAL DEFAULT 0.0,
                promoted_at TEXT,
                rollback_reason TEXT,
                proposal_id TEXT,
                last_gate_decision TEXT
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_lineage (
                child_id TEXT,
                parent_id TEXT,
                evolution_type TEXT,
                PRIMARY KEY (child_id, parent_id)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id TEXT,
                task_input TEXT,
                task_output TEXT,
                success BOOLEAN,
                execution_time REAL,
                timestamp TEXT,
                FOREIGN KEY (skill_id) REFERENCES skills(id)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id TEXT,
                suite_name TEXT,
                candidate_score REAL,
                baseline_score REAL,
                improved BOOLEAN,
                summary_json TEXT,
                created_at TEXT,
                FOREIGN KEY (skill_id) REFERENCES skills(id)
            )
        """)

        self._ensure_column("skills", "family_id", "TEXT")
        self._ensure_column("skills", "lifecycle_state", "TEXT DEFAULT 'ACTIVE'")
        self._ensure_column("skills", "baseline_score", "REAL DEFAULT 0.0")
        self._ensure_column("skills", "last_eval_score", "REAL DEFAULT 0.0")
        self._ensure_column("skills", "promoted_at", "TEXT")
        self._ensure_column("skills", "rollback_reason", "TEXT")
        self._ensure_column("skills", "proposal_id", "TEXT")
        self._ensure_column("skills", "last_gate_decision", "TEXT")

        # Index for fast search
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_skills_tags ON skills(tags)")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_skills_family_state ON skills(family_id, lifecycle_state)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_evaluations_skill ON skill_evaluations(skill_id)"
        )

        self.conn.execute(
            """
            UPDATE skills
            SET family_id = COALESCE(family_id, parent_id, id),
                lifecycle_state = COALESCE(lifecycle_state, 'ACTIVE'),
                baseline_score = COALESCE(baseline_score, quality_score, 0.0),
                last_eval_score = COALESCE(last_eval_score, baseline_score, quality_score, 0.0),
                proposal_id = COALESCE(proposal_id, NULL),
                last_gate_decision = COALESCE(last_gate_decision, NULL)
        """
        )

        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        """Best-effort schema migration for older local databases."""
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def save_skill(self, skill: SkillRecord):
        """Save or update a skill."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO skills 
            (id, name, description, content, version, parent_id, evolution_type,
             created_at, last_used, success_count, failure_count, applied_count,
             fallback_count, tags, quality_score, family_id, lifecycle_state,
             baseline_score, last_eval_score, promoted_at, rollback_reason, proposal_id, last_gate_decision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                skill.id,
                skill.name,
                skill.description,
                skill.content,
                skill.version,
                skill.parent_id,
                skill.evolution_type,
                skill.created_at,
                skill.last_used,
                skill.success_count,
                skill.failure_count,
                skill.applied_count,
                skill.fallback_count,
                json.dumps(skill.tags),
                skill.quality_score,
                skill.family_id or skill.parent_id or skill.id,
                skill.lifecycle_state,
                skill.baseline_score,
                skill.last_eval_score,
                skill.promoted_at,
                skill.rollback_reason,
                skill.proposal_id,
                skill.last_gate_decision,
            ),
        )

        if skill.parent_id:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO skill_lineage (child_id, parent_id, evolution_type)
                VALUES (?, ?, ?)
            """,
                (skill.id, skill.parent_id, skill.evolution_type),
            )

        self.conn.commit()

    def get_skill(self, skill_id: str) -> Optional[SkillRecord]:
        """Get a skill by ID."""
        row = self.conn.execute(
            "SELECT * FROM skills WHERE id = ?", (skill_id,)
        ).fetchone()

        if not row:
            return None

        return SkillRecord(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            content=row["content"],
            version=row["version"],
            parent_id=row["parent_id"],
            evolution_type=row["evolution_type"],
            created_at=row["created_at"],
            last_used=row["last_used"],
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            applied_count=row["applied_count"],
            fallback_count=row["fallback_count"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            quality_score=row["quality_score"],
            family_id=row["family_id"],
            lifecycle_state=row["lifecycle_state"] or "ACTIVE",
            baseline_score=row["baseline_score"] or 0.0,
            last_eval_score=row["last_eval_score"] or 0.0,
            promoted_at=row["promoted_at"],
            rollback_reason=row["rollback_reason"],
            proposal_id=row["proposal_id"],
            last_gate_decision=row["last_gate_decision"],
        )

    def search_skills(
        self, query: str, limit: int = 10, include_inactive: bool = False
    ) -> List[SkillRecord]:
        """Search skills by name/description/tags."""
        if include_inactive:
            rows = self.conn.execute(
                """
                SELECT * FROM skills
                WHERE name LIKE ? OR description LIKE ? OR tags LIKE ?
                ORDER BY quality_score DESC
                LIMIT ?
            """,
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            )
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM skills
                WHERE (name LIKE ? OR description LIKE ? OR tags LIKE ?)
                  AND lifecycle_state IN ('ACTIVE', 'PROBATION')
                ORDER BY quality_score DESC
                LIMIT ?
            """,
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            )

        return [self._row_to_skill(r) for r in rows]

    def get_all_skills(self, include_inactive: bool = False) -> List[SkillRecord]:
        """Get all skills."""
        if include_inactive:
            rows = self.conn.execute("SELECT * FROM skills ORDER BY quality_score DESC")
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM skills
                WHERE lifecycle_state IN ('ACTIVE', 'PROBATION')
                ORDER BY quality_score DESC
            """
            )
        return [self._row_to_skill(r) for r in rows]

    def _row_to_skill(self, row) -> SkillRecord:
        return SkillRecord(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            content=row["content"],
            version=row["version"],
            parent_id=row["parent_id"],
            evolution_type=row["evolution_type"],
            created_at=row["created_at"],
            last_used=row["last_used"],
            success_count=row["success_count"],
            failure_count=row["failure_count"],
            applied_count=row["applied_count"],
            fallback_count=row["fallback_count"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            quality_score=row["quality_score"],
            family_id=row["family_id"],
            lifecycle_state=row["lifecycle_state"] or "ACTIVE",
            baseline_score=row["baseline_score"] or 0.0,
            last_eval_score=row["last_eval_score"] or 0.0,
            promoted_at=row["promoted_at"],
            rollback_reason=row["rollback_reason"],
            proposal_id=row["proposal_id"],
            last_gate_decision=row["last_gate_decision"],
        )

    def log_execution(
        self,
        skill_id: str,
        task_input: str,
        task_output: str,
        success: bool,
        execution_time: float,
    ):
        """Log skill execution for analysis."""
        self.conn.execute(
            """
            INSERT INTO execution_history 
            (skill_id, task_input, task_output, success, execution_time, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                skill_id,
                task_input,
                task_output,
                success,
                execution_time,
                datetime.now().isoformat(),
            ),
        )

        # Update skill stats
        if success:
            self.conn.execute(
                """
                UPDATE skills SET 
                    success_count = success_count + 1,
                    last_used = ?,
                    quality_score = CASE 
                        WHEN failure_count + success_count > 0 
                        THEN CAST(success_count AS REAL) / (success_count + failure_count)
                        ELSE 0.5 END
                WHERE id = ?
            """,
                (datetime.now().isoformat(), skill_id),
            )
        else:
            self.conn.execute(
                """
                UPDATE skills SET 
                    failure_count = failure_count + 1,
                    last_used = ?,
                    quality_score = CASE 
                        WHEN failure_count + success_count > 0 
                        THEN CAST(success_count AS REAL) / (success_count + failure_count)
                        ELSE 0.5 END
                WHERE id = ?
            """,
                (datetime.now().isoformat(), skill_id),
            )

        self.conn.commit()

    def get_lineage(self, skill_id: str) -> List[SkillRecord]:
        """Get all parent versions of a skill."""
        lineage = []
        current_id = skill_id

        while current_id:
            skill = self.get_skill(current_id)
            if skill:
                lineage.append(skill)
                current_id = skill.parent_id
            else:
                break

        return lineage

    def get_family_skills(
        self, family_id: str, include_inactive: bool = True
    ) -> List[SkillRecord]:
        """Return all skills that belong to the same promotion family."""
        if include_inactive:
            rows = self.conn.execute(
                "SELECT * FROM skills WHERE family_id = ? ORDER BY created_at DESC",
                (family_id,),
            )
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM skills
                WHERE family_id = ? AND lifecycle_state IN ('ACTIVE', 'PROBATION')
                ORDER BY created_at DESC
            """,
                (family_id,),
            )
        return [self._row_to_skill(row) for row in rows]

    def get_champion_skill(self, family_id: str) -> Optional[SkillRecord]:
        """Return the currently active skill in a family."""
        row = self.conn.execute(
            """
            SELECT * FROM skills
            WHERE family_id = ? AND lifecycle_state = 'ACTIVE'
            ORDER BY COALESCE(promoted_at, created_at) DESC
            LIMIT 1
        """,
            (family_id,),
        ).fetchone()
        return self._row_to_skill(row) if row else None

    def update_skill_state(
        self,
        skill_id: str,
        lifecycle_state: str,
        *,
        baseline_score: Optional[float] = None,
        last_eval_score: Optional[float] = None,
        promoted_at: Optional[str] = None,
        rollback_reason: Optional[str] = None,
    ) -> None:
        """Update lifecycle metadata without reserializing the whole skill."""
        self.conn.execute(
            """
            UPDATE skills
            SET lifecycle_state = ?,
                baseline_score = COALESCE(?, baseline_score),
                last_eval_score = COALESCE(?, last_eval_score),
                promoted_at = COALESCE(?, promoted_at),
                rollback_reason = COALESCE(?, rollback_reason)
            WHERE id = ?
        """,
            (
                lifecycle_state,
                baseline_score,
                last_eval_score,
                promoted_at,
                rollback_reason,
                skill_id,
            ),
        )
        self.conn.commit()

    def record_evaluation(
        self,
        skill_id: str,
        suite_name: str,
        candidate_score: float,
        baseline_score: float,
        improved: bool,
        summary: Dict[str, Any],
    ) -> None:
        """Persist candidate-vs-baseline evaluation history."""
        self.conn.execute(
            """
            INSERT INTO skill_evaluations
            (skill_id, suite_name, candidate_score, baseline_score, improved, summary_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                skill_id,
                suite_name,
                candidate_score,
                baseline_score,
                int(improved),
                json.dumps(summary, ensure_ascii=False),
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()

    def get_latest_evaluation(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """Return the most recent benchmark/eval record for a skill."""
        row = self.conn.execute(
            """
            SELECT suite_name, candidate_score, baseline_score, improved, summary_json, created_at
            FROM skill_evaluations
            WHERE skill_id = ?
            ORDER BY id DESC
            LIMIT 1
        """,
            (skill_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "suite_name": row["suite_name"],
            "candidate_score": row["candidate_score"],
            "baseline_score": row["baseline_score"],
            "improved": bool(row["improved"]),
            "summary": json.loads(row["summary_json"]) if row["summary_json"] else {},
            "created_at": row["created_at"],
        }


class SkillEvolver:
    """Handles skill evolution (FIX/DERIVED/CAPTURED)."""

    def __init__(self, store: SkillStore):
        self.store = store

    def suggest_evolution(
        self, skill_id: str, execution_data: Dict
    ) -> Optional[EvolutionSuggestion]:
        """Analyze execution and suggest evolution."""
        skill = self.store.get_skill(skill_id)
        if not skill:
            return None

        # Check if skill failed
        if execution_data.get("success") is False:
            return EvolutionSuggestion(
                skill_id=skill_id,
                evolution_type="FIX",
                reason="Skill execution failed - needs repair",
                evidence=execution_data,
            )

        # Check if skill had to use fallbacks
        if execution_data.get("used_fallback", False):
            return EvolutionSuggestion(
                skill_id=skill_id,
                evolution_type="DERIVED",
                reason="Skill used fallbacks - create enhanced version",
                evidence=execution_data,
            )

        # Check if execution was very successful (potential for capture)
        if execution_data.get("success") and execution_data.get("novel_pattern"):
            return EvolutionSuggestion(
                skill_id=skill_id,
                evolution_type="CAPTURED",
                reason="Novel execution pattern - extract as new skill",
                evidence=execution_data,
            )

        return None

    async def evolve_skill(self, suggestion: EvolutionSuggestion) -> Optional[SkillRecord]:
        """Execute skill evolution based on suggestion (async — calls LLM for rewrites)."""
        parent = self.store.get_skill(suggestion.skill_id)
        if not parent:
            return None

        if suggestion.evolution_type == "FIX":
            new_content = await self._fix_skill_content(parent.content, suggestion.evidence)
            new_skill = SkillRecord(
                id=hashlib.md5(f"{parent.id}_fix_{time.time()}".encode()).hexdigest(),
                name=parent.name,
                description=f"FIX v{parent.version + 1}: {suggestion.reason}",
                content=new_content,
                version=parent.version + 1,
                parent_id=parent.id,
                evolution_type="FIX",
                tags=parent.tags.copy(),
                family_id=parent.family_id or parent.id,
                lifecycle_state="CANDIDATE",
                baseline_score=parent.last_eval_score or parent.baseline_score or parent.quality_score,
            )

        elif suggestion.evolution_type == "DERIVED":
            new_content = await self._derive_skill_content(parent.content, suggestion.evidence)
            new_skill = SkillRecord(
                id=hashlib.md5(
                    f"{parent.id}_derived_{time.time()}".encode()
                ).hexdigest(),
                name=f"{parent.name} (Enhanced)",
                description=f"Derived from {parent.name}: {suggestion.reason}",
                content=new_content,
                version=1,
                parent_id=parent.id,
                evolution_type="DERIVED",
                tags=parent.tags + ["derived"],
                family_id=parent.family_id or parent.id,
                lifecycle_state="CANDIDATE",
                baseline_score=parent.last_eval_score or parent.baseline_score or parent.quality_score,
            )

        else:  # CAPTURED
            new_skill = SkillRecord(
                id=hashlib.md5(f"captured_{time.time()}".encode()).hexdigest(),
                name=suggestion.evidence.get("pattern_name", "Captured Skill"),
                description=suggestion.evidence.get(
                    "pattern_description", "Extracted from execution"
                ),
                content=suggestion.evidence.get("pattern_content", ""),
                version=1,
                parent_id=None,
                evolution_type="CAPTURED",
                tags=suggestion.evidence.get("tags", ["captured"]),
                family_id=None,
                lifecycle_state="CANDIDATE",
            )

        self.store.save_skill(new_skill)
        return new_skill

    async def _fix_skill_content(self, content: str, evidence: Dict) -> str:
        """LLM-powered rewrite of broken skill content."""
        error = evidence.get("error", "")
        fix_hint = evidence.get("fix_suggestion", "")
        try:
            from core.brain import call_brain, CHEAP_MODEL

            prompt = (
                f"Ești un expert în optimizarea skill-urilor pentru agenți AI.\n\n"
                f"Skill-ul următor a eșuat cu eroarea: {error}\n"
                f"{('Sugestie: ' + fix_hint) if fix_hint else ''}\n\n"
                f"CONȚINUT SKILL ACTUAL:\n{content}\n\n"
                "SARCINA: Rescrie skill-ul pentru a preveni această eroare. "
                "Păstrează structura markdown. Returnează DOAR conținutul nou al skill-ului."
            )
            result = await call_brain(
                [{"role": "user", "content": prompt}],
                model=CHEAP_MODEL,
                profile="precise",
            )
            if result and "ERROR" not in result and len(result) > 50:
                return result
        except Exception as e:
            logger.warning(f"LLM fix failed, fallback to append: {e}")
        # Fallback
        return f"{content}\n\n<!-- FIX: {error[:300]} -->\n{fix_hint}"

    async def _derive_skill_content(self, content: str, evidence: Dict) -> str:
        """LLM-powered enhancement of skill content."""
        enhancement_context = evidence.get("enhancement", "")
        try:
            from core.brain import call_brain, CHEAP_MODEL

            prompt = (
                "Ești un expert în optimizarea skill-urilor pentru agenți AI.\n\n"
                "Skill-ul următor a necesitat fallback-uri suplimentare:\n"
                f"CONȚINUT SKILL ACTUAL:\n{content}\n\n"
                f"Context suplimentar: {enhancement_context}\n\n"
                "SARCINA: Creează o versiune îmbunătățită care să gestioneze mai bine "
                "edge cases și să nu necesite fallback-uri. Returnează DOAR conținutul nou."
            )
            result = await call_brain(
                [{"role": "user", "content": prompt}],
                model=CHEAP_MODEL,
                profile="balanced",
            )
            if result and "ERROR" not in result and len(result) > 50:
                return result
        except Exception as e:
            logger.warning(f"LLM derive failed, fallback to append: {e}")
        # Fallback
        return f"{content}\n\n<!-- DERIVED: {enhancement_context[:300]} -->"


class SkillRanker:
    """Hybrid ranking: BM25 + embedding + LLM selection."""

    def __init__(self, store: SkillStore):
        self.store = store

    def rank_skills(self, query: str, limit: int = 5) -> List[SkillRecord]:
        """Rank skills by relevance."""
        # Simple BM25-like scoring
        query_terms = query.lower().split()
        skills = self.store.get_all_skills()

        scored = []
        for skill in skills:
            score = 0

            # Name match (highest weight)
            for term in query_terms:
                if term in skill.name.lower():
                    score += 10

            # Description match
            for term in query_terms:
                if term in skill.description.lower():
                    score += 5

            # Tag match
            for term in query_terms:
                if any(term in tag.lower() for tag in skill.tags):
                    score += 3

            # Quality score bonus
            score += skill.quality_score * 2

            # Usage frequency bonus
            score += min(skill.applied_count / 10, 5)

            scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]


class SelfEvolvingSkills:
    """Main class: Self-Evolving Skills Engine for JARVIS."""

    def __init__(self, skills_dir: str = ".jarvis/skills"):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        db_path = str(self.skills_dir / "skills.db")
        self.store = SkillStore(db_path)
        self.evolver = SkillEvolver(self.store)
        self.ranker = SkillRanker(self.store)

        from core.evals_engine import EvalsEngine
        from core.improvement_proposals import get_proposals
        from core.promotion_gate import get_promotion_gate

        self.evals = EvalsEngine(str(self.skills_dir / "evals"))
        self.proposals = get_proposals(str(self.skills_dir / "improvement_proposals"))
        self.promotion_gate = get_promotion_gate(str(self.skills_dir / "promotion_gate"))

        # Load built-in skills
        self._load_builtin_skills()

        logger.info(f"🧬 Self-Evolving Skills Engine initialized at {self.skills_dir}")

    def _load_builtin_skills(self):
        """Load initial skill set if empty."""
        if self.store.get_all_skills():
            return  # Already has skills

        # Create base skills
        base_skills = [
            SkillRecord(
                id="code-review",
                name="Code Review",
                description="Review code for bugs, performance, and style issues",
                content="""# Code Review Skill

When asked to review code:
1. Check for syntax errors and bugs
2. Look for performance issues
3. Verify style consistency
4. Suggest improvements
5. Check security vulnerabilities
""",
                tags=["code", "review", "quality"],
                family_id="code-review",
                baseline_score=0.5,
                last_eval_score=0.5,
            ),
            SkillRecord(
                id="debug-fix",
                name="Debug & Fix",
                description="Debug errors and suggest fixes",
                content="""# Debug & Fix Skill

When debugging:
1. Analyze error messages
2. Check stack traces
3. Reproduce the issue
4. Identify root cause
5. Provide fix with explanation
""",
                tags=["debug", "fix", "error"],
                family_id="debug-fix",
                baseline_score=0.5,
                last_eval_score=0.5,
            ),
            SkillRecord(
                id="file-operations",
                name="File Operations",
                description="Read, write, and manage files",
                content="""# File Operations Skill

For file operations:
1. Check file exists before reading
2. Use proper encoding
3. Create directories as needed
4. Handle permissions gracefully
5. Verify write success
""",
                tags=["file", "io", "filesystem"],
                family_id="file-operations",
                baseline_score=0.5,
                last_eval_score=0.5,
            ),
        ]

        for skill in base_skills:
            self.store.save_skill(skill)

        logger.info(f"Loaded {len(base_skills)} built-in skills")

    async def find_skill(self, task: str) -> Optional[SkillRecord]:
        """Find best matching skill for a task."""
        skills = self.ranker.rank_skills(task)
        return skills[0] if skills else None

    @staticmethod
    def _score_eval_summary(summary: Dict[str, Any]) -> float:
        """Reduce a benchmark suite to a promotion-friendly score."""
        success = float(summary.get("success_rate", 0.0))
        verification = float(summary.get("verification_rate", 0.0))
        hallucination_penalty = float(summary.get("hallucinated_success_rate", 0.0))
        retries_penalty = min(float(summary.get("avg_retries", 0.0)) / 3.0, 1.0)
        replans_penalty = min(float(summary.get("avg_replans", 0.0)) / 3.0, 1.0)
        duration_penalty = min(float(summary.get("median_duration_sec", 0.0)) / 600.0, 1.0)
        cost_penalty = min(float(summary.get("avg_cost_estimate", 0.0)), 1.0)

        score = (
            success * 0.35
            + verification * 0.3
            + (1.0 - hallucination_penalty) * 0.15
            + (1.0 - retries_penalty) * 0.08
            + (1.0 - replans_penalty) * 0.07
            + (1.0 - duration_penalty) * 0.03
            + (1.0 - cost_penalty) * 0.02
        )
        return round(max(0.0, min(score, 1.0)), 4)

    def _resolve_eval_summary(
        self,
        skill: SkillRecord,
        eval_suite: Any,
        eval_engine: Any | None = None,
    ) -> tuple[Dict[str, Any], str]:
        """Accept a suite name, case list, or prebuilt summary."""
        if isinstance(eval_suite, dict) and "success_rate" in eval_suite:
            return eval_suite, str(eval_suite.get("suite_name", f"skill:{skill.id}"))

        if eval_engine is None:
            from core.evals_engine import EvalsEngine

            eval_engine = EvalsEngine(str(self.skills_dir / "evals"))

        if isinstance(eval_suite, str):
            return eval_engine.run_eval_suite(eval_suite), eval_suite

        if isinstance(eval_suite, list):
            suite_name = f"skill:{skill.id}"
            cases = []
            for index, case in enumerate(eval_suite):
                normalized = dict(case)
                normalized.setdefault("id", f"{skill.id}:{index}")
                normalized.setdefault("suite", suite_name)
                cases.append(normalized)
            return eval_engine.run_eval_suite(suite_name, cases), suite_name

        raise TypeError("eval_suite must be a suite name, list of cases, or eval summary")

    @staticmethod
    def _infer_eval_category(mission: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Infer the closest eval category for post-mission governance."""
        ctx = context or {}
        mission_type = str(ctx.get("mission_type", "")).lower()
        text = f"{mission_type} {mission}".lower()
        if any(token in text for token in ("browser", "web", "site", "page")):
            return "web"
        if any(token in text for token in ("desktop", "app ", "finder", "safari", "screen")):
            return "desktop"
        if any(token in text for token in ("code", "python", "typescript", "bug", "repo")):
            return "coding"
        return "general"

    def _build_post_mission_eval_suite(
        self,
        mission: str,
        result: str,
        quality_score: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Create a deterministic mini-suite from a completed mission."""
        ctx = context or {}
        mission_id = str(ctx.get("mission_id", "post_mission"))
        category = self._infer_eval_category(mission, ctx)
        failure_codes = list(ctx.get("failure_codes", []))
        metrics = ctx.get("metrics", {}) or {}
        rates = metrics.get("rates", {}) if isinstance(metrics, dict) else {}
        verification_rate = float(rates.get("verification_rate", 1.0 if quality_score >= 8 else 0.0))
        duration_sec = float(metrics.get("duration_sec", 30.0) if isinstance(metrics, dict) else 30.0)
        critical_failures = {
            code
            for code in failure_codes
            if code in {"RISK_POLICY_BLOCK", "VERIFICATION_FAIL", "HALLUCINATED_SUCCESS", "RECOVERY_FAIL", "UI_GROUNDING_FAIL"}
        }
        summary_text = str(result or "")
        base_success = quality_score >= 8 and not critical_failures
        base_verified = verification_rate >= 0.95 and not critical_failures

        return [
            {
                "id": f"{mission_id}:primary",
                "category": category,
                "success": base_success,
                "verified": base_verified,
                "duration_sec": duration_sec,
                "retries": int(metrics.get("retries", 0) if isinstance(metrics, dict) else 0),
                "replans": int(metrics.get("replans", 0) if isinstance(metrics, dict) else 0),
                "failure_codes": failure_codes,
                "hallucinated_success_count": 1 if "HALLUCINATED_SUCCESS" in critical_failures else 0,
            },
            {
                "id": f"{mission_id}:quality",
                "category": category,
                "success": quality_score >= 7,
                "verified": quality_score >= 8 and verification_rate >= 0.8,
                "duration_sec": max(5.0, duration_sec * 0.85),
                "retries": int(metrics.get("retries", 0) if isinstance(metrics, dict) else 0),
                "replans": int(metrics.get("replans", 0) if isinstance(metrics, dict) else 0),
                "failure_codes": [] if quality_score >= 8 else failure_codes[:1],
                "hallucinated_success_count": 0,
                "notes": summary_text[:160],
            },
        ]

    def _ensure_skill_proposal(
        self,
        skill: SkillRecord,
        evaluation: Dict[str, Any],
    ) -> Optional[str]:
        """Create or refresh a proposal record for a governed candidate skill."""
        if skill.lifecycle_state not in {"CANDIDATE", "PROBATION"}:
            return skill.proposal_id

        from core.improvement_proposals import ProposalStatus, RiskLevel, TargetType

        top_failures = evaluation.get("summary", {}).get("failure_modes", {}).get(
            "top_failure_modes",
            [],
        )
        evidence = [f"{code}: {count}" for code, count in top_failures[:5]]
        rationale = (
            f"Candidate score={evaluation.get('candidate_score', 0.0):.3f}, "
            f"baseline={evaluation.get('baseline_score', 0.0):.3f}, "
            f"recommended={evaluation.get('recommended_action', 'hold')}"
        )

        proposal = self.proposals.get(skill.proposal_id) if skill.proposal_id else None
        if proposal is None:
            proposal = self.proposals.propose(
                source_run_id=evaluation.get("suite_name", f"skill:{skill.id}"),
                target_type=TargetType.SKILL,
                summary=f"Evaluate skill candidate {skill.name}",
                rationale=rationale,
                evidence=evidence,
                patch={
                    "skill_id": skill.id,
                    "family_id": skill.family_id or skill.id,
                    "content": skill.content,
                    "version": skill.version,
                    "lifecycle_state": skill.lifecycle_state,
                },
                expected_gain=max(
                    0.0,
                    float(evaluation.get("candidate_score", 0.0))
                    - float(evaluation.get("baseline_score", 0.0)),
                ),
                risk_level=RiskLevel.LOW,
            )
            self.proposals.queue_for_eval(proposal.proposal_id, evaluation.get("suite_name", ""))
        elif proposal.status in {ProposalStatus.DRAFTED, ProposalStatus.ON_HOLD}:
            self.proposals.queue_for_eval(proposal.proposal_id, evaluation.get("suite_name", ""))

        skill.proposal_id = proposal.proposal_id
        self.store.save_skill(skill)
        return proposal.proposal_id

    def run_skill_promotion_gate(
        self,
        skill_id: str,
        eval_suite: Any,
        eval_engine: Any | None = None,
        approved_by: str = "system",
    ) -> Dict[str, Any]:
        """Evaluate a skill candidate through regression harness + promotion gate."""
        skill = self.store.get_skill(skill_id)
        if not skill:
            raise KeyError(f"Unknown skill: {skill_id}")

        eval_engine = eval_engine or self.evals
        evaluation = self.evaluate_skill_candidate(skill_id, eval_suite, eval_engine=eval_engine)
        skill = self.store.get_skill(skill_id) or skill
        proposal_id = self._ensure_skill_proposal(skill, evaluation)
        if proposal_id:
            self.proposals.mark_eval_running(proposal_id)

        summary = eval_engine.run_regression_harness(
            evaluation["suite_name"],
            evaluation["summary"].get("results"),
        )
        evaluation["summary"] = summary
        candidate_evidence = eval_engine.build_promotion_evidence(summary)

        family_id = skill.family_id or skill.id
        champion = self.store.get_champion_skill(family_id)
        champion_eval = (
            self.store.get_latest_evaluation(champion.id)
            if champion and champion.id != skill.id
            else None
        )
        if champion_eval and champion_eval.get("summary"):
            champion_summary = eval_engine.run_regression_harness(
                champion_eval.get("suite_name", f"champion:{champion.id}"),
                champion_eval["summary"].get("results"),
            )
            champion_evidence = eval_engine.build_promotion_evidence(champion_summary)
        else:
            from core.promotion_gate import EvalEvidence

            champion_evidence = EvalEvidence(
                eval_run_id=f"baseline:{family_id}",
                success_rate=float(skill.baseline_score or 0.5),
                verification_rate=float(skill.baseline_score or 0.5),
                replay_reproducibility=float(skill.baseline_score or 0.5),
            )

        gate = self.promotion_gate.evaluate(
            candidate_config_id=skill.id,
            champion_config_id=champion.id if champion else family_id,
            candidate=candidate_evidence,
            champion=champion_evidence,
            approved_by=approved_by,
        )

        skill.last_gate_decision = gate.decision.value
        self.store.save_skill(skill)

        score = float(evaluation.get("candidate_score", 0.0))
        passed_gate = gate.decision.value == "promote"
        if proposal_id:
            self.proposals.record_eval_result(proposal_id, score=score, passed=passed_gate)

        if gate.decision.value == "promote":
            promotion = self.promote_skill_if_better(skill.id, evaluation=evaluation)
            if proposal_id:
                self.proposals.mark_promoted(proposal_id, candidate_config_id=skill.id)
            return {
                "decision": gate.decision.value,
                "gate": gate.as_dict(),
                "evaluation": evaluation,
                "promotion": promotion,
            }

        if gate.decision.value == "hold":
            hold = self.promote_skill_if_better(skill.id, evaluation=evaluation)
            if proposal_id:
                self.proposals.mark_on_hold(proposal_id, gate.reason)
            return {
                "decision": gate.decision.value,
                "gate": gate.as_dict(),
                "evaluation": evaluation,
                "promotion": hold,
            }

        rollback = self.rollback_skill(skill.id, gate.reason)
        if proposal_id:
            self.proposals.reject(proposal_id, gate.reason)
        return {
            "decision": gate.decision.value,
            "gate": gate.as_dict(),
            "evaluation": evaluation,
            "promotion": rollback,
        }

    def human_approve_proposal(
        self,
        proposal_id: str,
        *,
        approved_by: str = "human-operator",
        reason: str = "Human approved via governance UI",
    ) -> Dict[str, Any]:
        """Force-promote a governed skill proposal through the existing promotion gate."""
        proposal = self.proposals.get(proposal_id)
        if not proposal:
            raise KeyError(f"Unknown proposal: {proposal_id}")

        skill_id = ""
        if isinstance(proposal.patch, dict):
            skill_id = str(proposal.patch.get("skill_id") or "")
        if not skill_id:
            skill_id = str(proposal.candidate_config_id or "")
        if not skill_id:
            raise ValueError("Human approval is only supported for governed skill proposals.")

        skill = self.store.get_skill(skill_id)
        if not skill:
            raise KeyError(f"Unknown skill candidate for proposal {proposal_id}: {skill_id}")

        family_id = skill.family_id or skill.id
        champion = self.store.get_champion_skill(family_id)
        champion_id = champion.id if champion else family_id
        gate = self.promotion_gate.human_approve(
            candidate_config_id=skill.id,
            champion_config_id=champion_id,
            approved_by=approved_by,
            reason=reason,
        )

        score = float(
            proposal.eval_score
            if proposal.eval_score is not None
            else skill.last_eval_score or skill.baseline_score or skill.quality_score
        )

        if champion and champion.id != skill.id:
            self.store.update_skill_state(champion.id, "SUPERSEDED")

        self.store.update_skill_state(
            skill.id,
            "ACTIVE",
            baseline_score=skill.baseline_score or skill.quality_score,
            last_eval_score=score,
            promoted_at=datetime.now().isoformat(),
            rollback_reason=None,
        )

        refreshed = self.store.get_skill(skill.id) or skill
        refreshed.proposal_id = proposal_id
        refreshed.last_gate_decision = gate.decision.value
        self.store.save_skill(refreshed)

        self.proposals.record_eval_result(proposal_id, score=score, passed=True)
        promoted_proposal = self.proposals.mark_promoted(
            proposal_id,
            candidate_config_id=skill.id,
        )

        return {
            "decision": gate.decision.value,
            "gate": gate.as_dict(),
            "proposal": promoted_proposal.as_dict(),
            "skill_id": refreshed.id,
            "skill_name": refreshed.name,
            "family_id": family_id,
        }

    async def execute_with_skill(self, task: str, executor_func) -> Dict[str, Any]:
        """Execute task with skill tracking and potential evolution."""
        # Find best skill
        skill = await self.find_skill(task)

        start_time = time.time()
        result = {"success": False, "used_skill": None, "skill_id": None}

        if skill:
            result["used_skill"] = skill.name
            result["skill_id"] = skill.id

            # Execute with skill context
            try:
                output = await executor_func(skill.content)
                execution_time = time.time() - start_time

                result["success"] = True
                result["output"] = output

                # Log execution
                self.store.log_execution(
                    skill.id, task, str(output), True, execution_time
                )

                # Check for evolution
                await self._check_evolution(
                    skill.id, {"success": True, "execution_time": execution_time}
                )

            except Exception as e:
                execution_time = time.time() - start_time
                result["error"] = str(e)

                # Log failed execution
                self.store.log_execution(skill.id, task, str(e), False, execution_time)

                # Check for evolution (FIX)
                await self._check_evolution(
                    skill.id, {"success": False, "error": str(e)}
                )
        else:
            # No skill found, execute directly
            try:
                result["output"] = await executor_func(None)
                result["success"] = True
            except Exception as e:
                result["error"] = str(e)

        return result

    async def _check_evolution(self, skill_id: str, execution_data: Dict):
        """Check if evolution is needed after execution."""
        suggestion = self.evolver.suggest_evolution(skill_id, execution_data)

        if suggestion:
            logger.info(
                f"🧬 Evolution suggested: {suggestion.evolution_type} for {skill_id}"
            )
            new_skill = await self.evolver.evolve_skill(suggestion)
            if new_skill:
                logger.info(
                    "✨ Evolved new skill candidate: %s (%s)",
                    new_skill.name,
                    new_skill.evolution_type,
                )

    def evaluate_skill_candidate(
        self,
        skill_id: str,
        eval_suite: Any,
        eval_engine: Any | None = None,
    ) -> Dict[str, Any]:
        """Run a micro-benchmark for a skill candidate against its family champion."""
        skill = self.store.get_skill(skill_id)
        if not skill:
            raise KeyError(f"Unknown skill: {skill_id}")

        summary, suite_name = self._resolve_eval_summary(skill, eval_suite, eval_engine)
        family_id = skill.family_id or skill.id
        champion = self.store.get_champion_skill(family_id)
        champion_eval = (
            self.store.get_latest_evaluation(champion.id)
            if champion and champion.id != skill.id
            else None
        )
        baseline_summary = champion_eval["summary"] if champion_eval else None
        baseline_score = (
            self._score_eval_summary(baseline_summary)
            if baseline_summary
            else champion.last_eval_score
            if champion and champion.id != skill.id
            else skill.baseline_score or skill.quality_score
        )
        candidate_score = self._score_eval_summary(summary)

        comparison = (
            eval_engine.compare_against_baseline(summary, baseline_summary)
            if baseline_summary and eval_engine is not None
            else {
                "improved": candidate_score >= baseline_score + 0.02,
                "deltas": {"score": round(candidate_score - baseline_score, 4)},
            }
        )
        improved = bool(comparison.get("improved", False))
        recommended_action = (
            "promote"
            if improved
            else "probation"
            if candidate_score >= baseline_score - 0.03
            else "rollback"
        )

        skill.last_eval_score = candidate_score
        skill.baseline_score = baseline_score
        self.store.save_skill(skill)
        self.store.record_evaluation(
            skill_id=skill.id,
            suite_name=suite_name,
            candidate_score=candidate_score,
            baseline_score=baseline_score,
            improved=improved,
            summary=summary,
        )

        return {
            "skill_id": skill.id,
            "family_id": family_id,
            "suite_name": suite_name,
            "candidate_score": candidate_score,
            "baseline_score": baseline_score,
            "comparison": comparison,
            "improved": improved,
            "recommended_action": recommended_action,
            "summary": summary,
            "champion_skill_id": champion.id if champion else None,
        }

    def promote_skill_if_better(
        self,
        skill_id: str,
        score: float | None = None,
        evaluation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Promote a candidate when the benchmark beats the current family champion."""
        skill = self.store.get_skill(skill_id)
        if not skill:
            raise KeyError(f"Unknown skill: {skill_id}")

        family_id = skill.family_id or skill.id
        champion = self.store.get_champion_skill(family_id)
        latest = evaluation or self.store.get_latest_evaluation(skill_id) or {}
        candidate_score = float(score if score is not None else latest.get("candidate_score", 0.0))
        baseline_score = float(
            latest.get(
                "baseline_score",
                champion.last_eval_score if champion else skill.baseline_score,
            )
            or 0.0
        )
        improved = bool(
            latest.get("improved", candidate_score >= baseline_score + 0.02)
        )

        if improved:
            if champion and champion.id != skill.id:
                self.store.update_skill_state(champion.id, "SUPERSEDED")
            self.store.update_skill_state(
                skill.id,
                "ACTIVE",
                baseline_score=candidate_score,
                last_eval_score=candidate_score,
                promoted_at=datetime.now().isoformat(),
                rollback_reason=None,
            )
            promoted = self.store.get_skill(skill.id)
            return {
                "promoted": True,
                "probation": False,
                "rolled_back": False,
                "skill_id": skill.id,
                "family_id": family_id,
                "active_skill_id": promoted.id if promoted else skill.id,
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
            }

        if candidate_score >= baseline_score - 0.03:
            self.store.update_skill_state(
                skill.id,
                "PROBATION",
                baseline_score=baseline_score,
                last_eval_score=candidate_score,
            )
            return {
                "promoted": False,
                "probation": True,
                "rolled_back": False,
                "skill_id": skill.id,
                "family_id": family_id,
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
            }

        rollback = self.rollback_skill(
            skill.id,
            reason=f"Candidate underperformed baseline ({candidate_score:.3f} < {baseline_score:.3f})",
        )
        rollback.update(
            {
                "promoted": False,
                "probation": False,
                "candidate_score": candidate_score,
                "baseline_score": baseline_score,
            }
        )
        return rollback

    def rollback_skill(self, skill_id: str, reason: str) -> Dict[str, Any]:
        """Rollback a candidate or active skill and restore the previous champion if available."""
        skill = self.store.get_skill(skill_id)
        if not skill:
            raise KeyError(f"Unknown skill: {skill_id}")

        family_id = skill.family_id or skill.id
        family_members = self.store.get_family_skills(family_id, include_inactive=True)
        previous = next(
            (
                member
                for member in family_members
                if member.id != skill.id and member.lifecycle_state == "SUPERSEDED"
            ),
            None,
        )
        if skill.lifecycle_state == "ACTIVE" and previous:
            self.store.update_skill_state(previous.id, "ACTIVE", rollback_reason=None)

        self.store.update_skill_state(
            skill.id,
            "ROLLED_BACK",
            rollback_reason=reason,
        )
        return {
            "rolled_back": True,
            "skill_id": skill.id,
            "family_id": family_id,
            "restored_skill_id": previous.id if previous else None,
            "reason": reason,
        }

    def get_skill_status(self) -> Dict[str, Any]:
        """Get skills health metrics."""
        active_skills = self.store.get_all_skills()
        all_skills = self.store.get_all_skills(include_inactive=True)
        lifecycle_counts: Dict[str, int] = {}
        for skill in all_skills:
            lifecycle_counts[skill.lifecycle_state] = (
                lifecycle_counts.get(skill.lifecycle_state, 0) + 1
            )

        return {
            "total_skills": len(all_skills),
            "active_skills": len(active_skills),
            "avg_quality": sum(s.quality_score for s in all_skills) / max(len(all_skills), 1),
            "total_successes": sum(s.success_count for s in all_skills),
            "total_failures": sum(s.failure_count for s in all_skills),
            "lifecycle_counts": lifecycle_counts,
            "proposal_summary": self.proposals.summary(),
            "promotion_history": self.promotion_gate.history(5),
            "recent_proposals": self.proposals.recent(5),
            "skills": [
                {
                    "name": s.name,
                    "skill_id": s.id,
                    "quality": s.quality_score,
                    "state": s.lifecycle_state,
                    "baseline_score": s.baseline_score,
                    "last_eval_score": s.last_eval_score,
                    "proposal_id": s.proposal_id,
                    "last_gate_decision": s.last_gate_decision,
                    "success_rate": s.success_count
                    / max(s.success_count + s.failure_count, 1),
                }
                for s in all_skills[:10]
            ],
        }

    def add_skill(
        self,
        name: str,
        description: str,
        content: str,
        tags: List[str],
        *,
        parent_id: Optional[str] = None,
        lifecycle_state: str = "ACTIVE",
        family_id: Optional[str] = None,
    ) -> SkillRecord:
        """Manually add a new skill."""
        parent = self.store.get_skill(parent_id) if parent_id else None
        skill = SkillRecord(
            id=hashlib.md5(f"{name}_{time.time()}".encode()).hexdigest(),
            name=name,
            description=description,
            content=content,
            tags=tags,
            parent_id=parent_id,
            family_id=family_id or (parent.family_id if parent else None),
            lifecycle_state=lifecycle_state,
            baseline_score=parent.last_eval_score if parent else 0.5,
            last_eval_score=parent.last_eval_score if parent else 0.5,
        )
        self.store.save_skill(skill)
        return skill

    async def analyze_mission_for_skills(
        self, mission: str, result: str, quality_score: int
    ) -> Optional[SkillRecord]:
        """Ask LLM if this mission produced a novel reusable skill pattern (CAPTURED mode)."""
        try:
            from core.brain import call_brain, CHEAP_MODEL

            prompt = (
                "Analizezi o misiune AI completată.\n"
                f"MISIUNE: {mission[:500]}\n"
                f"REZULTAT (primele 600 chars): {result[:600]}\n"
                f"SCOR CALITATE: {quality_score}/10\n\n"
                "SARCINA: Dacă această misiune a demonstrat un pattern REUTILIZABIL și VALOROS "
                "(nu specific doar acestei misiuni), extrage-l ca un skill nou.\n\n"
                "Răspunde EXCLUSIV în JSON valid:\n"
                '{"has_novel_pattern": true/false, '
                '"skill_name": "Nume skill 3-5 cuvinte", '
                '"skill_description": "Descriere 1 rand", '
                '"skill_content": "# Titlu\\n\\nInstructiuni complete markdown...", '
                '"tags": ["tag1", "tag2"]}\n\n'
                'Dacă nu există pattern reutilizabil, răspunde: {"has_novel_pattern": false}'
            )
            response = await call_brain(
                [{"role": "user", "content": prompt}],
                model=CHEAP_MODEL,
                profile="precise",
            )
            if not response or "ERROR" in response:
                return None

            import re

            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                return None
            data = json.loads(json_match.group())
            if data.get("has_novel_pattern") and data.get("skill_name"):
                skill = self.add_skill(
                    name=data["skill_name"],
                    description=data.get("skill_description", ""),
                    content=data.get("skill_content", ""),
                    tags=data.get("tags", ["captured"]),
                )
                logger.info(f"✨ [CAPTURED] New skill extracted: {skill.name}")
                return skill
        except Exception as e:
            logger.warning(f"[analyze_mission_for_skills] {e}")
        return None

    async def post_mission_hook(
        self,
        mission: str,
        result: str,
        quality_score: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """OpenSpace pattern: automatically called after every mission.

        - score < 6  → FIX evolution on best matching skill
        - score >= 8 → try to CAPTURE a novel skill from this mission
        """
        ctx = context or {}
        report: Dict[str, Any] = {
            "quality_score": quality_score,
            "mission_id": ctx.get("mission_id"),
            "action": "observe",
            "status": "noop",
            "candidate_skill_id": None,
            "candidate_skill_name": None,
            "matched_skill_id": None,
            "matched_skill_name": None,
            "proposal_id": None,
            "gate_decision": None,
            "gate_reason": None,
            "eval_suite_name": None,
        }
        try:
            if quality_score < 6:
                # Find the most relevant skill and trigger FIX
                skills = self.ranker.rank_skills(mission, limit=1)
                if skills:
                    skill = skills[0]
                    report["action"] = "fix"
                    report["matched_skill_id"] = skill.id
                    report["matched_skill_name"] = skill.name
                    suggestion = self.evolver.suggest_evolution(
                        skill.id,
                        {
                            "success": False,
                            "error": f"Mission quality score: {quality_score}/10",
                            "fix_suggestion": (
                                f"Improve skill for mission type context: {mission[:150]}"
                            ),
                        },
                    )
                    if suggestion:
                        evolved = await self.evolver.evolve_skill(suggestion)
                        if evolved:
                            report["candidate_skill_id"] = evolved.id
                            report["candidate_skill_name"] = evolved.name
                            eval_suite = self._build_post_mission_eval_suite(
                                mission,
                                result,
                                quality_score,
                                context=ctx,
                            )
                            gate_result = self.run_skill_promotion_gate(
                                evolved.id,
                                eval_suite,
                                approved_by="post-mission-hook",
                            )
                            updated = self.store.get_skill(evolved.id) or evolved
                            report["proposal_id"] = updated.proposal_id
                            report["gate_decision"] = gate_result.get("decision")
                            report["gate_reason"] = gate_result.get("gate", {}).get("reason")
                            report["eval_suite_name"] = gate_result.get("evaluation", {}).get("suite_name")
                            report["status"] = "gated"
                            report["gate"] = gate_result.get("gate")
                            report["promotion"] = gate_result.get("promotion")
                            logger.info(
                                f"🧬 [POST-MISSION FIX] {skill.name} → {evolved.name}"
                            )
            elif quality_score >= 8:
                # High-quality mission — try to capture novel pattern
                report["action"] = "capture"
                captured = await self.analyze_mission_for_skills(mission, result, quality_score)
                if captured:
                    report["candidate_skill_id"] = captured.id
                    report["candidate_skill_name"] = captured.name
                    eval_suite = self._build_post_mission_eval_suite(
                        mission,
                        result,
                        quality_score,
                        context=ctx,
                    )
                    gate_result = self.run_skill_promotion_gate(
                        captured.id,
                        eval_suite,
                        approved_by="post-mission-hook",
                    )
                    updated = self.store.get_skill(captured.id) or captured
                    report["proposal_id"] = updated.proposal_id
                    report["gate_decision"] = gate_result.get("decision")
                    report["gate_reason"] = gate_result.get("gate", {}).get("reason")
                    report["eval_suite_name"] = gate_result.get("evaluation", {}).get("suite_name")
                    report["status"] = "gated"
                    report["gate"] = gate_result.get("gate")
                    report["promotion"] = gate_result.get("promotion")
        except Exception as e:
            report["status"] = "error"
            report["error"] = str(e)
            logger.warning(f"[post_mission_hook] {e}")
        return report

    def evolve_manually(
        self, skill_id: str, new_content: str, evolution_type: str
    ) -> Optional[SkillRecord]:
        """Manually trigger evolution for a skill."""
        parent = self.store.get_skill(skill_id)
        if not parent:
            return None

        new_skill = SkillRecord(
            id=hashlib.md5(f"{evolution_type}_{time.time()}".encode()).hexdigest(),
            name=f"{parent.name} (Manual {evolution_type})",
            description=f"Manual evolution of {parent.name}",
            content=new_content,
            version=parent.version + 1 if evolution_type == "FIX" else 1,
            parent_id=parent.id,
            evolution_type=evolution_type,
            tags=parent.tags.copy(),
            family_id=parent.family_id or parent.id,
            lifecycle_state="CANDIDATE",
            baseline_score=parent.last_eval_score or parent.baseline_score or parent.quality_score,
        )

        self.store.save_skill(new_skill)
        return new_skill


# Standalone usage
if __name__ == "__main__":
    import asyncio

    async def test():
        engine = SelfEvolvingSkills()

        # Test skill finding
        skill = await engine.find_skill("review code for bugs")
        print(f"Found skill: {skill.name if skill else 'None'}")

        # Test execution
        async def executor(content):
            await asyncio.sleep(0.1)
            return "Code reviewed successfully"

        result = await engine.execute_with_skill("review this code", executor)
        print(f"Result: {result}")

        # Get status
        status = engine.get_skill_status()
        print(f"Status: {status}")

    asyncio.run(test())
