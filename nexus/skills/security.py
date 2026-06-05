"""Security checks for skill file access."""

from __future__ import annotations

from pathlib import Path


def is_path_within_directory(path: Path, directory: Path) -> bool:
    """Return True if resolved *path* is inside resolved *directory*."""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def has_symlink_in_path(path: Path, directory: Path) -> bool:
    """Detect symlinks in the portion of *path* below *directory* (without following)."""
    directory = directory.resolve()
    try:
        rel_parts = path.relative_to(directory).parts
    except ValueError:
        return True

    current = directory
    for part in rel_parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def validate_resource_path(skill_dir: Path, resource_path: Path) -> Path:
    """Resolve and validate a resource path within a skill directory.

    Raises:
        ValueError: If the path escapes the skill directory or uses symlinks.
    """
    skill_dir = skill_dir.resolve()
    candidate = skill_dir / resource_path

    if has_symlink_in_path(candidate, skill_dir):
        raise ValueError(f"Symlink detected in resource path: {resource_path}")

    resolved = candidate.resolve()

    if not is_path_within_directory(resolved, skill_dir):
        raise ValueError(f"Resource path escapes skill directory: {resource_path}")

    if not resolved.is_file():
        raise ValueError(f"Resource not found: {resource_path}")

    return resolved


def safe_read_text(path: Path, *, max_bytes: int = 512_000) -> str:
    """Read a text file with a size cap."""
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"Resource too large ({size} bytes, max {max_bytes})")
    return path.read_text(encoding="utf-8", errors="replace")
