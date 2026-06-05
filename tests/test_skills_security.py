"""Tests for skill file access security."""

import os
from pathlib import Path

import pytest

from nexus.skills.security import is_path_within_directory, validate_resource_path

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


def test_is_path_within_directory():
    skill_dir = FIXTURES / "code-review"
    resource = skill_dir / "references" / "checklist.md"
    assert is_path_within_directory(resource, skill_dir)


def test_path_traversal_blocked(tmp_path: Path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "safe.txt").write_text("ok")
    with pytest.raises(ValueError, match="escapes"):
        validate_resource_path(skill_dir, Path("../outside.txt"))


def test_symlink_escape_blocked(tmp_path: Path):
    if os.name == "nt":
        pytest.skip("Symlink test unreliable on Windows")
    skill_dir = tmp_path / "skill"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    skill_dir.mkdir()
    link = skill_dir / "references"
    link.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="Symlink"):
        validate_resource_path(skill_dir, Path("references/outside.txt"))

