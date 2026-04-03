"""📚 JARVIS Skill Library
Inspired by seb1n/awesome-ai-agent-skills: 70+ universal, self-contained skills
that make any AI agent better at real-world tasks.

Each skill is a complete, ready-to-use instruction set.

V3 upgrade: skills now have a lane (champion/candidate/deprecated),
source (seeded/human/learned), and versioning aligned with DB_SCHEMA.
Only champion skills are active. Candidate skills await eval before promotion.
"""

import json
import logging
import re
import shutil
import time
import uuid
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# V3 skill status values (aligned with DB_SCHEMA skills table)
SKILL_STATUS_CHAMPION   = "champion"
SKILL_STATUS_CANDIDATE  = "candidate"
SKILL_STATUS_DEPRECATED = "deprecated"

# Who created/introduced the skill
SKILL_SOURCE_SEEDED  = "seeded"    # built-in defaults
SKILL_SOURCE_HUMAN   = "human"     # human-authored, imported from disk
SKILL_SOURCE_LEARNED = "learned"   # proposed by Jarvis via improvement proposal


@dataclass
class Skill:
    """A single skill with instructions."""

    id: str
    name: str
    description: str
    content: str  # The actual skill prompt
    category: str
    tags: List[str]
    verified: bool = False
    version: str = "1.0.0"
    source: str = SKILL_SOURCE_SEEDED
    path: Optional[str] = None
    # V3 fields
    status: str = SKILL_STATUS_CHAMPION    # champion | candidate | deprecated
    candidate_id: str = ""                 # links to CandidateLane entry when candidate
    promoted_at: float = 0.0              # timestamp of last promotion
    deprecated_at: float = 0.0            # timestamp of deprecation


class SkillLibrary:
    """Library of reusable skills for JARVIS.

    V3: skills live in one of three lanes:
      - champion:   active, used by Jarvis in production
      - candidate:  proposed change, awaiting eval + promotion gate
      - deprecated: retired, not used

    Only champion skills are returned by get_skill() and search_skills()
    by default (pass include_candidate=True to see candidates).
    """

    def __init__(self, skills_dir: str = None):
        self.skills_dir = Path(skills_dir or ".jarvis/skill_library")
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._status_file = self.skills_dir / "_skill_status.json"
        self.skills: Dict[str, Skill] = {}
        self._load_default_skills()
        self._load_disk_skills()
        self._apply_persisted_status()

    def _load_default_skills(self):
        """Load default skill set."""
        # Core skills that every agent needs
        default_skills = [
            Skill(
                id="code-review",
                name="Code Review",
                description="Review code for bugs, performance, and style issues",
                content="""# Code Review Skill

When reviewing code, follow this systematic approach:

## 1. Correctness
- Check for syntax errors and obvious bugs
- Verify logic flows correctly
- Check edge cases and error handling

## 2. Performance
- Look for inefficient loops or algorithms
- Check for unnecessary computations
- Verify appropriate data structures used

## 3. Security
- Check for injection vulnerabilities
- Verify proper input validation
- Look for hardcoded secrets

## 4. Style
- Verify naming conventions followed
- Check proper documentation
- Ensure consistent formatting

## 5. Testing
- Suggest test cases for edge cases
- Check for adequate coverage
- Verify error conditions tested

Provide feedback in this format:
- **Critical**: Issues that must be fixed
- **Warning**: Issues that should be addressed
- **Suggestion**: Improvements to consider
""",
                category="development",
                tags=["code", "review", "quality", "security"],
                verified=True,
                source=SKILL_SOURCE_SEEDED,
            ),
            Skill(
                id="debug-fix",
                name="Debug & Fix",
                description="Debug errors and provide fixes",
                content="""# Debug & Fix Skill

When debugging, follow this systematic approach:

## 1. Understand the Error
- Read the full error message
- Identify the error type (syntax, runtime, logic)
- Locate the exact line/function

## 2. Reproduce
- Create minimal reproduction case
- Verify the error occurs consistently
- Note the environment/context

## 3. Analyze
- Check stack trace for call chain
- Examine variable values at failure point
- Identify the root cause, not just symptoms

## 4. Fix
- Implement the minimal fix
- Explain why this fixes the issue
- Check for similar issues elsewhere

## 5. Verify
- Confirm the fix works
- Run existing tests
- Check for regressions
""",
                category="development",
                tags=["debug", "fix", "error", "testing"],
                verified=True,
            ),
            Skill(
                id="file-operations",
                name="File Operations",
                description="Safe file read/write operations",
                content="""# File Operations Skill

For file operations, always follow these best practices:

## Before Reading
- Check if file exists with os.path.exists()
- Verify file permissions
- Handle encoding explicitly (utf-8)

## Before Writing
- Create parent directories with os.makedirs(..., exist_ok=True)
- Use 'w' mode for write, 'a' for append
- Consider atomic writes (write to temp, then rename)
- Handle permission errors gracefully

## After Operations
- Close files properly (or use context managers)
- Verify write success
- Log operations for debugging

## Common Patterns
```python
# Safe read
if os.path.exists(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

# Safe write
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
```
""",
                category="infrastructure",
                tags=["file", "io", "filesystem", "safety"],
                verified=True,
            ),
            Skill(
                id="api-design",
                name="API Design",
                description="Design clean and usable APIs",
                content="""# API Design Skill

When designing APIs, follow these principles:

## RESTful Conventions
- Use nouns for resources (/users, /files)
- Use HTTP verbs appropriately (GET, POST, PUT, DELETE)
- Use plural nouns for collections
- Use proper status codes (200, 201, 400, 404, 500)

## Error Handling
- Return consistent error format
- Include helpful error messages
- Use appropriate status codes
- Log errors server-side

## Versioning
- Version APIs (/v1/, /v2/)
- Support backward compatibility
- Deprecate gracefully

## Documentation
- Document all endpoints
- Provide example requests/responses
- Explain authentication
- Document rate limits

## Security
- Authenticate and authorize properly
- Validate all inputs
- Sanitize outputs
- Use HTTPS
""",
                category="development",
                tags=["api", "rest", "design", "architecture"],
                verified=True,
            ),
            Skill(
                id="documentation",
                name="Technical Documentation",
                description="Write clear technical documentation",
                content="""# Technical Documentation Skill

When writing technical docs:

## Structure
- Start with overview/purpose
- Use clear headings
- Progress from simple to complex
- Include table of contents for long docs

## Code Examples
- Show complete, runnable examples
- Include comments explaining key parts
- Show both correct and incorrect usage
- Keep examples up-to-date

## API Docs
- Document all parameters
- Explain return values
- Show example requests/responses
- Document errors and exceptions

## Audience
- Adjust for technical level
- Define prerequisites
- Avoid unexplained jargon
- Define acronyms on first use

## Maintenance
- Version your docs
- Note when content was last updated
- Provide way to report issues
- Keep docs near code
""",
                category="development",
                tags=["documentation", "docs", "writing", "api"],
                verified=True,
            ),
            Skill(
                id="testing",
                name="Comprehensive Testing",
                description="Write effective tests",
                content="""# Testing Skill

When writing tests:

## Test Structure
- Use AAA pattern (Arrange, Act, Assert)
- One assertion per test when possible
- Name tests descriptively (test_<what>_<expected>)
- Keep tests independent

## Coverage
- Test happy path
- Test edge cases
- Test error conditions
- Test boundary values

## Mocking
- Mock external dependencies
- Don't mock internals unnecessarily
- Use real objects when appropriate
- Verify mock interactions

## Best Practices
- Keep tests fast
- Make tests deterministic
- Clean up after tests
- Use test fixtures appropriately

## Types of Tests
- Unit: Test individual functions/classes
- Integration: Test component interactions
- E2E: Test full user workflows
- Performance: Test speed/scalability
""",
                category="development",
                tags=["testing", "quality", "unittest", "coverage"],
                verified=True,
            ),
            Skill(
                id="git-workflow",
                name="Git Workflow",
                description="Proper Git usage and workflow",
                content=""""Git Workflow Skill

## Branching
- Use feature branches (feature/, bugfix/)
- Keep branches small and focused
- Delete merged branches
- Use meaningful branch names

## Commits
- Write meaningful commit messages
- Commit often with logical units
- Use imperative mood ("Add feature" not "Added")
- First line: summary (<50 chars), then blank, then details

## Merging
- Rebase local work before pushing
- Use pull requests for review
- Squash commits when merging
- Resolve conflicts carefully

## Common Commands
```bash
# Create feature branch
git checkout -b feature/my-feature

# Keep up to date
git fetch origin
git rebase origin/main

# Interactive rebase to clean commits
git rebase -i HEAD~3

# Stash work
git stash
git stash pop
```
""",
                category="infrastructure",
                tags=["git", "version-control", "workflow", "collaboration"],
                verified=True,
            ),
            Skill(
                id="refactoring",
                name="Code Refactoring",
                description="Improve code without changing behavior",
                content="""# Refactoring Skill

## When to Refactor
- Code smells: duplicated code, long functions, tight coupling
- Before adding new features
- After tests pass (ensure no regression)

## Safe Refactoring
1. Ensure tests exist and pass
2. Make one change at a time
3. Run tests after each change
4. Commit working states

## Common Techniques
- Extract Method: Split large functions
- Rename: Better names for clarity
- Inline: Remove unnecessary indirection
- Move: Better location for code
- Replace Conditional: Use polymorphism

## Code Smells to Fix
- Duplicated code → Extract to shared function
- Long function → Split into smaller ones
- Many parameters → Use objects
- Magic numbers → Named constants
- God class → Split responsibilities

## After Refactoring
- Run full test suite
- Review changes
- Update documentation
- Commit with clear message
""",
                category="development",
                tags=["refactoring", "code-quality", "cleanup", "maintenance"],
                verified=True,
            ),
            Skill(
                id="security-audit",
                name="Security Audit",
                description="Find and fix security vulnerabilities",
                content="""# Security Audit Skill

## Common Vulnerabilities
- Injection (SQL, XSS, Command)
- Broken authentication
- Sensitive data exposure
- XXE, SSRF, deserialization

## Audit Process
1. Map attack surface
2. Identify entry points
3. Trace data flow
4. Test edge cases
5. Verify defenses

## Prevention
- Input validation (whitelist when possible)
- Output encoding
- Parameterized queries
- Proper authentication
- Encrypt sensitive data

## Tools
- Static analysis (bandit, semgrep)
- Dependency scanning (Snyk, Dependabot)
- Secret scanning (git-secrets)

## Report Format
- Severity (Critical/High/Medium/Low)
- Description
- Proof of concept
- Impact
- Remediation
""",
                category="security",
                tags=["security", "audit", "vulnerability", "owasp"],
                verified=True,
            ),
            Skill(
                id="performance-optimization",
                name="Performance Optimization",
                description="Optimize code for speed and efficiency",
                content="""# Performance Optimization Skill

## Profiling First
- Measure before optimizing
- Find the bottleneck
- Don't guess - use profilers

## Common Optimizations
- Use appropriate data structures
- Cache frequently accessed data
- Batch database operations
- Lazy load when possible
- Use generators for large data

## Python Specific
- Use built-ins when possible
- List comprehensions vs loops
- Caching with @lru_cache
- String concatenation with join
- Use json for JSON

## Database
- Add appropriate indexes
- Avoid SELECT *
- Use pagination
- Batch inserts
- Use connection pooling

## Monitoring
- Track response times
- Set up alerts
- Log slow queries
- Measure cache hit rates
""",
                category="development",
                tags=["performance", "optimization", "profiling", "efficiency"],
                verified=True,
            ),
        ]

        for skill in default_skills:
            self.skills[skill.id] = skill

        logger.info(f"Loaded {len(default_skills)} default skills")

    def _load_disk_skills(self):
        """Load skills stored as SKILL.md directories."""
        loaded = 0
        for skill_path in sorted(self.skills_dir.rglob("SKILL.md")):
            skill = self._load_skill_from_markdown(skill_path)
            if not skill:
                continue
            self.skills[skill.id] = skill
            loaded += 1

        if loaded:
            logger.info("Loaded %s filesystem skills from %s", loaded, self.skills_dir)

    def _apply_persisted_status(self) -> None:
        """Load persisted status overrides (champion/candidate/deprecated) from disk."""
        if not self._status_file.exists():
            return
        try:
            data: dict = json.loads(self._status_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for skill_id, meta in data.items():
            s = self.skills.get(skill_id)
            if not s:
                continue
            s.status = meta.get("status", s.status)
            s.candidate_id = meta.get("candidate_id", s.candidate_id)
            s.promoted_at = meta.get("promoted_at", s.promoted_at)
            s.deprecated_at = meta.get("deprecated_at", s.deprecated_at)

    def _save_status(self) -> None:
        """Persist status overrides for skills whose status is non-default."""
        data = {}
        for skill_id, s in self.skills.items():
            if s.status != SKILL_STATUS_CHAMPION or s.candidate_id or s.deprecated_at:
                data[skill_id] = {
                    "status": s.status,
                    "candidate_id": s.candidate_id,
                    "promoted_at": s.promoted_at,
                    "deprecated_at": s.deprecated_at,
                }
        try:
            self._status_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ── V3 lane management ────────────────────────────────────────

    def propose_candidate(
        self,
        skill: "Skill",
        candidate_id: str = "",
        source: str = SKILL_SOURCE_LEARNED,
    ) -> "Skill":
        """
        Add a new skill as a candidate (not yet active).

        The skill is stored under a temp id suffixed with ':candidate'.
        Only after promote() does it replace/register as champion.
        """
        skill.status = SKILL_STATUS_CANDIDATE
        skill.source = source
        skill.candidate_id = candidate_id or str(uuid.uuid4())
        cand_id = f"{skill.id}:candidate"
        self.skills[cand_id] = skill
        self._save_status()
        return skill

    def promote_skill(self, skill_id: str, approved_by: str = "system") -> "Skill":
        """
        Promote a candidate skill to champion, replacing the old champion.

        If skill_id ends with ':candidate', the base id replaces the existing champion.
        """
        cand_key = skill_id if skill_id in self.skills else f"{skill_id}:candidate"
        s = self.skills.get(cand_key)
        if not s:
            raise ValueError(f"Skill '{skill_id}' not found")
        if s.status != SKILL_STATUS_CANDIDATE:
            raise ValueError(
                f"Skill '{skill_id}' is not a candidate (status={s.status})"
            )
        # Deprecate existing champion if any
        base_id = skill_id.replace(":candidate", "")
        old = self.skills.get(base_id)
        if old and old.status == SKILL_STATUS_CHAMPION:
            old.status = SKILL_STATUS_DEPRECATED
            old.deprecated_at = time.time()

        s.status = SKILL_STATUS_CHAMPION
        s.promoted_at = time.time()
        s.version = self._bump_version(s.version)
        self.skills[base_id] = s
        if cand_key != base_id:
            del self.skills[cand_key]
        self._save_status()
        logger.info("Skill '%s' promoted to champion by %s (v%s)", base_id, approved_by, s.version)
        return s

    def deprecate_skill(self, skill_id: str, reason: str = "") -> "Skill":
        """Retire a champion skill — it remains in the registry but is not used."""
        s = self.skills.get(skill_id)
        if not s:
            raise ValueError(f"Skill '{skill_id}' not found")
        s.status = SKILL_STATUS_DEPRECATED
        s.deprecated_at = time.time()
        self._save_status()
        logger.info("Skill '%s' deprecated. Reason: %s", skill_id, reason or "none")
        return s

    def list_by_status(self, status: str) -> List["Skill"]:
        """Return all skills with the given status."""
        return [s for s in self.skills.values() if s.status == status]

    @staticmethod
    def _bump_version(version: str) -> str:
        """Increment the patch component of a semver string."""
        try:
            parts = version.split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            return ".".join(parts)
        except (ValueError, IndexError):
            return version + ".1"

    def _load_skill_from_markdown(self, skill_path: Path) -> Optional[Skill]:
        """Parse a filesystem SKILL.md into a Skill record."""
        try:
            content = skill_path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.warning("Failed to read skill file %s: %s", skill_path, exc)
            return None

        if not content:
            return None

        relative = skill_path.relative_to(self.skills_dir)
        skill_id = skill_path.parent.name
        title = self._extract_title(content) or skill_id.replace("-", " ").title()
        description = self._extract_description(content) or f"Skill from {relative.parent}"
        category = self._derive_category(relative)
        tags = self._derive_tags(relative, content)
        source = self._derive_source(relative)

        return Skill(
            id=skill_id,
            name=title,
            description=description,
            content=content,
            category=category,
            tags=tags,
            verified=True,
            version="external",
            source=source,
            status=SKILL_STATUS_CHAMPION,
            path=str(skill_path),
        )

    def _extract_title(self, content: str) -> str:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return ""

    def _extract_description(self, content: str) -> str:
        lines = [line.strip() for line in content.splitlines()]
        for index, line in enumerate(lines):
            if line.startswith("#"):
                for candidate in lines[index + 1 :]:
                    if candidate and not candidate.startswith("#"):
                        return candidate
        return ""

    def _derive_category(self, relative_path: Path) -> str:
        parts = list(relative_path.parts)
        if len(parts) >= 4 and parts[0] == "packs":
            return parts[2]
        if len(parts) >= 2:
            return parts[0]
        return "imported"

    def _derive_source(self, relative_path: Path) -> str:
        parts = list(relative_path.parts)
        if len(parts) >= 3 and parts[0] == "packs":
            return parts[1]
        return SKILL_SOURCE_HUMAN

    def _derive_tags(self, relative_path: Path, content: str) -> List[str]:
        parts = [part for part in relative_path.parts[:-1] if part not in {"packs"}]
        tags = {part.replace("-", " ") for part in parts}
        tags.update(re.findall(r"`([^`]+)`", content[:1000]))
        return sorted(tag.replace(" ", "-").lower() for tag in tags if tag)

    def get_skill(self, skill_id: str, include_candidate: bool = False) -> Optional[Skill]:
        """Get a skill by ID. Returns None for deprecated/candidate unless include_candidate=True."""
        s = self.skills.get(skill_id)
        if s is None:
            return None
        if s.status == SKILL_STATUS_DEPRECATED:
            return None
        if s.status == SKILL_STATUS_CANDIDATE and not include_candidate:
            return None
        return s

    def get_skills_by_category(self, category: str, include_candidate: bool = False) -> List[Skill]:
        """Get all skills in a category (champion only by default)."""
        return [
            s for s in self.skills.values()
            if s.category == category
            and (s.status == SKILL_STATUS_CHAMPION or (include_candidate and s.status == SKILL_STATUS_CANDIDATE))
        ]

    def search_skills(self, query: str, include_candidate: bool = False) -> List[Skill]:
        """Search champion skills by name, description, or tags."""
        query_lower = query.lower()
        results = []
        allowed = {SKILL_STATUS_CHAMPION}
        if include_candidate:
            allowed.add(SKILL_STATUS_CANDIDATE)

        for skill in self.skills.values():
            if skill.status not in allowed:
                continue
            if (
                query_lower in skill.name.lower()
                or query_lower in skill.description.lower()
                or query_lower in skill.content.lower()
                or any(query_lower in tag.lower() for tag in skill.tags)
            ):
                results.append(skill)

        return results

    def get_all_categories(self) -> List[str]:
        """Get all skill categories (champion skills only)."""
        return list(set(
            s.category for s in self.skills.values()
            if s.status == SKILL_STATUS_CHAMPION
        ))

    def add_skill(self, skill: Skill):
        """Add a new skill to the library."""
        self.skills[skill.id] = skill

    def import_skill_pack(
        self, source_dir: str, pack_name: str = "imported", overwrite: bool = True
    ) -> Dict[str, Any]:
        """Import an external SKILL.md directory tree into the library."""
        src = Path(source_dir).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(f"Skill pack source not found: {src}")

        destination = self.skills_dir / "packs" / pack_name
        destination.mkdir(parents=True, exist_ok=True)

        imported = 0
        for skill_md in src.rglob("SKILL.md"):
            relative_dir = skill_md.parent.relative_to(src)
            target_dir = destination / relative_dir
            if target_dir.exists() and overwrite:
                shutil.rmtree(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_md, target_dir / "SKILL.md")
            imported += 1

        self._load_disk_skills()
        return {
            "pack_name": pack_name,
            "source_dir": str(src),
            "destination": str(destination),
            "imported_skills": imported,
            "total_skills": len(self.skills),
        }

    def list_skills(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List skills with V3 metadata. Filter by status if provided."""
        skills = self.skills.values()
        if status:
            skills = [s for s in skills if s.status == status]
        return [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "tags": s.tags,
                "verified": s.verified,
                "version": s.version,
                "source": s.source,
                "status": s.status,
                "candidate_id": s.candidate_id,
                "promoted_at": s.promoted_at,
                "deprecated_at": s.deprecated_at,
                "path": s.path,
            }
            for s in skills
        ]

    def status_summary(self) -> Dict[str, int]:
        """Return count of skills by status."""
        counts: Dict[str, int] = {}
        for s in self.skills.values():
            counts[s.status] = counts.get(s.status, 0) + 1
        return counts


# Integration with Self-Evolving Skills
def get_skill_for_task(task: str, library: SkillLibrary) -> Optional[str]:
    """Map a task to the best skill from library."""
    task_lower = task.lower()

    mappings = {
        "review": "code-review",
        "debug": "debug-fix",
        "fix": "debug-fix",
        "file": "file-operations",
        "write": "file-operations",
        "api": "api-design",
        "document": "documentation",
        "test": "testing",
        "git": "git-workflow",
        "refactor": "refactoring",
        "security": "security-audit",
        "vulnerability": "security-audit",
        "performance": "performance-optimization",
        "optimize": "performance-optimization",
    }

    for key, skill_id in mappings.items():
        if key in task_lower:
            return skill_id

    return None


if __name__ == "__main__":
    library = SkillLibrary()
    print(f"Categories: {library.get_all_categories()}")

    # Test search
    results = library.search_skills("testing")
    print(f"Found {len(results)} skills: {[s.name for s in results]}")

    # Test category
    dev_skills = library.get_skills_by_category("development")
    print(f"Dev skills: {[s.name for s in dev_skills]}")
