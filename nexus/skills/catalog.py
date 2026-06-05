"""Build skill catalog blocks for system prompt injection."""

from __future__ import annotations

from html import escape as xml_escape

from nexus.skills.models import FileSkill


def build_skills_catalog(skills: list[FileSkill]) -> str:
    """Build an XML-escaped skill catalog for progressive disclosure."""
    if not skills:
        return ""

    lines = [
        "## Available Skills",
        "",
        "The following skills are available. Use the `skills.load_skill` tool to load "
        "full instructions when a task matches a skill's description. Use "
        "`skills.read_skill_resource` to read supplementary files on demand.",
        "",
        "<skills>",
    ]
    for skill in skills:
        name = xml_escape(skill.frontmatter.name)
        desc = xml_escape(skill.frontmatter.description)
        lines.append(f'  <skill name="{name}" description="{desc}" />')
    lines.append("</skills>")
    return "\n".join(lines)


def build_explicit_skills_block(skills: list[FileSkill]) -> str:
    """Build a system prompt block with full skill bodies for explicit activation."""
    if not skills:
        return ""

    lines = ["## Active Skills", ""]
    for skill in skills:
        lines.append(skill.format_explicit_block())
    return "\n".join(lines)
