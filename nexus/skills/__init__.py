"""Agent Skills subsystem (agentskills.io compatible)."""

from nexus.skills.catalog import build_explicit_skills_block, build_skills_catalog
from nexus.skills.config import SkillsConfig
from nexus.skills.models import (
    FileSkill,
    SkillFrontmatter,
    SkillNotFoundError,
    SkillParseError,
    SkillResource,
    SkillScript,
)
from nexus.skills.paths import get_skills_root, global_skills_dir, tenant_skills_dir, user_skills_dir
from nexus.skills.plugin import SkillsPlugin, create_skills_plugin
from nexus.skills.registry import SkillsRegistry
from nexus.skills.sandbox import (
    DisabledSkillSandbox,
    SkillExecutionDisabledError,
    SkillSandboxAdapter,
    register_sandbox_adapter,
    resolve_sandbox,
)

__all__ = [
    "SkillsConfig",
    "SkillsRegistry",
    "SkillsPlugin",
    "create_skills_plugin",
    "FileSkill",
    "SkillFrontmatter",
    "SkillResource",
    "SkillScript",
    "SkillParseError",
    "SkillNotFoundError",
    "SkillSandboxAdapter",
    "SkillExecutionDisabledError",
    "DisabledSkillSandbox",
    "register_sandbox_adapter",
    "resolve_sandbox",
    "build_skills_catalog",
    "build_explicit_skills_block",
    "get_skills_root",
    "global_skills_dir",
    "tenant_skills_dir",
    "user_skills_dir",
]
