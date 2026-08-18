"""Tests for the skills tool plugin."""

from pathlib import Path

import pytest

from nexus.skills.config import SkillsConfig
from nexus.skills.plugin import create_skills_plugin
from nexus.skills.registry import SkillsRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


@pytest.fixture
def registry():
    return SkillsRegistry(SkillsConfig(enabled=True, global_paths=[str(FIXTURES)]))


@pytest.fixture
def plugin(registry):
    return create_skills_plugin(registry, SkillsConfig(enabled=True, global_paths=[str(FIXTURES)]))


def test_load_skill(plugin):
    result = plugin.load_skill("code-review")
    assert "Code Review Skill" in result
    assert "checklist" in result


def test_load_skill_section(plugin):
    result = plugin.load_skill("code-review", section="instructions")
    assert "Read the code carefully" in result
    assert "Examples" not in result or "section: instructions" in result.lower()


def test_load_skill_missing_section(plugin):
    result = plugin.load_skill("code-review", section="does-not-exist")
    assert "Error" in result


def test_load_skill_not_found(plugin):
    result = plugin.load_skill("missing")
    assert "Error" in result


def test_read_skill_resource(plugin):
    result = plugin.read_skill_resource("code-review", "checklist")
    assert "Error handling" in result


@pytest.mark.asyncio
async def test_run_skill_script_disabled(plugin):
    result = await plugin.run_skill_script("code-review", "lint")
    assert "disabled" in result.lower()
