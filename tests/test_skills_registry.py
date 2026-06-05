"""Tests for SkillsRegistry."""

from pathlib import Path

from nexus.skills.config import SkillsConfig
from nexus.skills.models import SkillNotFoundError
from nexus.skills.registry import SkillsRegistry
from nexus.tools.context import RunContext

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


def test_discover_and_get_skill():
    registry = SkillsRegistry(SkillsConfig(enabled=True, global_paths=[str(FIXTURES)]))
    skill = registry.get_skill("code-review")
    assert skill.name == "code-review"


def test_enabled_skills_allowlist():
    registry = SkillsRegistry(
        SkillsConfig(
            enabled=True,
            global_paths=[str(FIXTURES)],
            enabled_skills=["commit-messages"],
        )
    )
    skills = registry.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "commit-messages"


def test_resolve_explicit_skills_from_config():
    registry = SkillsRegistry(
        SkillsConfig(
            enabled=True,
            global_paths=[str(FIXTURES)],
            explicit_skills=["code-review"],
        )
    )
    explicit = registry.resolve_explicit_skills()
    assert len(explicit) == 1
    assert explicit[0].name == "code-review"


def test_resolve_explicit_skills_from_run_context():
    registry = SkillsRegistry(
        SkillsConfig(enabled=True, global_paths=[str(FIXTURES)])
    )
    ctx = RunContext(metadata={"skills": ["commit-messages"]})
    explicit = registry.resolve_explicit_skills(ctx)
    assert len(explicit) == 1
    assert explicit[0].name == "commit-messages"


def test_skill_not_found():
    registry = SkillsRegistry(SkillsConfig(enabled=True, global_paths=[str(FIXTURES)]))
    try:
        registry.get_skill("nonexistent")
        assert False, "expected SkillNotFoundError"
    except SkillNotFoundError:
        pass


def test_tenant_skills_gated_off():
    registry = SkillsRegistry(
        SkillsConfig(
            enabled=True,
            global_paths=[str(FIXTURES)],
            allow_tenant_skills=False,
        )
    )
    ctx = RunContext(tenant_id="acme")
    paths = registry._resolve_source_paths(ctx)
    assert all(scope == "global" for _, scope in paths)
