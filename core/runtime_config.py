"""Shared runtime configuration helpers for JARVIS surfaces.

These helpers keep chat, bridge, tools, and runtime modules aligned on:
- project root discovery
- .env loading
- provider alias setup
- vault path resolution
- CORS defaults
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List


def get_project_root(anchor: str | Path | None = None) -> Path:
    """Return the workspace root for the current JARVIS checkout."""
    if anchor is None:
        return Path(__file__).resolve().parent.parent

    path = Path(anchor).resolve()
    if path.is_file():
        return path.parent.parent if path.parent.name == "core" else path.parent
    return path


def load_project_env(project_root: str | Path | None = None) -> Path | None:
    """Load the local .env if python-dotenv is available."""
    root = get_project_root(project_root)
    env_path = root / ".env"
    if not env_path.exists():
        return None

    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
        return env_path
    except Exception:
        return None


def configure_inception_openai_alias(force: bool = False) -> bool:
    """Alias OpenAI-compatible env vars to Inception only when appropriate."""
    inception_key = os.getenv("INCEPTION_API_KEY", "").strip()
    if not inception_key:
        return False

    if force or not os.getenv("OPENAI_API_BASE"):
        os.environ["OPENAI_API_BASE"] = "https://api.inceptionlabs.ai/v1"

    if force or not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = inception_key

    return True


def resolve_obsidian_vault_path(project_root: str | Path | None = None) -> Path:
    """Resolve the best-known Obsidian/JARVIS vault path."""
    root = get_project_root(project_root)

    env_candidates = [
        os.getenv("JARVIS_VAULT_PATH"),
        os.getenv("JARVIS_OBSIDIAN_VAULT"),
        os.getenv("OBSIDIAN_VAULT_PATH"),
    ]
    candidates = [Path(item).expanduser() for item in env_candidates if item]
    candidates.extend(
        [
            Path.home() / "Documents" / "JARVIS",
            root / ".jarvis" / "vault",
            root / "memory" / "obsidian_vault",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Return the first explicit env path if present, otherwise the default workspace path.
    if env_candidates:
        return Path(env_candidates[0]).expanduser()
    return root / ".jarvis" / "vault"


def get_cors_origins() -> List[str]:
    """Return safe local-development CORS origins, overridable via env."""
    raw = os.getenv("JARVIS_CORS_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:8888",
        "http://127.0.0.1:8888",
    ]
