"""Tests for skill directory discovery."""

from pathlib import Path

from nexus.skills.discovery import discover_skills_in_path, discover_skills_from_paths

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


def test_discover_skills_in_path():
    skills = discover_skills_in_path(FIXTURES)
    names = {s.name for s in skills}
    assert names == {"code-review", "commit-messages"}


def test_discover_empty_directory(tmp_path: Path):
    assert discover_skills_in_path(tmp_path) == []


def test_discover_nonexistent_path(tmp_path: Path):
    assert discover_skills_in_path(tmp_path / "missing") == []


def test_discover_from_multiple_paths():
    skills = discover_skills_from_paths([FIXTURES])
    assert len(skills) == 2
