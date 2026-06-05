"""Tests for SkillsConfig defaults."""

import os

from nexus.skills.config import SkillsConfig


def test_global_paths_defaults_to_nexus_skills_root(monkeypatch, tmp_path):
    custom = tmp_path / "custom-skills"
    monkeypatch.setenv("NEXUS_SKILLS_ROOT", str(custom))
    config = SkillsConfig()
    assert config.global_paths == [str(custom)]
