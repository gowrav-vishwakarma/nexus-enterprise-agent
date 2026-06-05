"""Tests for SKILL.md parsing and validation."""

from pathlib import Path

import pytest

from nexus.skills.models import SkillParseError
from nexus.skills.parser import parse_skill_md

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


def test_parse_valid_skill():
    skill = parse_skill_md(FIXTURES / "code-review")
    assert skill.name == "code-review"
    assert "Review code" in skill.frontmatter.description
    assert "Read the code carefully" in skill.content
    assert len(skill.resources) == 1
    assert skill.resources[0].name == "checklist"
    assert len(skill.scripts) == 1
    assert skill.scripts[0].name == "lint"


def test_parse_minimal_skill():
    skill = parse_skill_md(FIXTURES / "commit-messages")
    assert skill.name == "commit-messages"
    assert skill.resources == []
    assert skill.scripts == []


def test_name_must_match_directory(tmp_path: Path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: wrong-name\ndescription: A test skill for validation.\n---\n\nBody.\n"
    )
    with pytest.raises(SkillParseError, match="must match parent directory"):
        parse_skill_md(skill_dir)


def test_invalid_name_uppercase(tmp_path: Path):
    skill_dir = tmp_path / "Bad-Name"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Bad-Name\ndescription: A test skill for validation.\n---\n\nBody.\n"
    )
    with pytest.raises(SkillParseError):
        parse_skill_md(skill_dir)


def test_missing_frontmatter(tmp_path: Path):
    skill_dir = tmp_path / "no-frontmatter"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Just markdown\n")
    with pytest.raises(SkillParseError, match="frontmatter"):
        parse_skill_md(skill_dir)
