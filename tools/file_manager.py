"""Simple file tools for Architect and Chronos."""

from pathlib import Path


def read_text_file(path: str) -> str:
    """Read UTF-8 file content."""
    target = Path(path)
    if not target.exists():
        return f"File not found: {path}"
    return target.read_text(encoding="utf-8")


def write_text_file(path: str, content: str) -> str:
    """Write UTF-8 content to a file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Saved: {path}"
