"""Phase 1: RAG/memory config, skill sections, parallel vote."""

from collections import Counter

from nexus.config.agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.memory import MemoryConfig
from nexus.memory.provider import MemoryProvider, MemoryProviderProtocol
from nexus.rag.config import RAGConfig
from nexus.skills.models import FileSkill, SkillFrontmatter, parse_skill_sections


def _agent(name: str, **kw) -> AgentConfig:
    return AgentConfig(
        name=name,
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
        persona=AgentPersonaConfig(role=name, goal="answer"),
        **kw,
    )


def test_agent_config_rag_defaults_none():
    cfg = _agent("a")
    assert cfg.rag is None


def test_agent_config_rag_optional():
    cfg = _agent("a", rag=RAGConfig(provider="in_memory", collection="docs"))
    assert cfg.rag is not None
    assert cfg.rag.provider == "in_memory"
    assert cfg.rag.chunker.strategy == "fixed"
    assert cfg.rag.retrieval.hybrid is False


def test_memory_config_provider_defaults():
    mem = MemoryConfig(enabled=True)
    assert mem.provider is None
    assert mem.provider_class is None
    assert mem.provider_config == {}
    assert mem.require_approval is False


def test_memory_provider_protocol_alias():
    assert MemoryProviderProtocol is MemoryProvider


def test_parse_skill_sections():
    content = "# Title\n\n## Checklist\n- a\n\n## Security\nOWASP\n"
    sections = parse_skill_sections(content)
    assert "checklist" in sections
    assert "security" in sections
    assert "OWASP" in sections["security"]
    assert "- a" in sections["checklist"]


def test_skill_format_load_response_section():
    skill = FileSkill(
        frontmatter=SkillFrontmatter(name="code-review", description="d"),
        content="# Code Review\n\n## Checklist\n- bugs\n\n## Security\nOWASP top 10\n",
        directory=".",
    )
    full = skill.format_load_response()
    assert "Checklist" in full and "Security" in full
    sec = skill.format_load_response(section="security")
    assert "OWASP" in sec
    assert "bugs" not in sec
    missing = skill.format_load_response(section="style")
    assert "Error" in missing
    assert "checklist" in missing.lower()


def test_vote_plurality():
    responses = [("a", "yes"), ("b", "yes"), ("c", "no")]
    counts = Counter(resp for _, resp in responses)
    winner, _ = counts.most_common(1)[0]
    assert winner == "yes"


def test_agent_group_vote_strategy_accepted():
    group = AgentGroupConfig(
        name="panel",
        pattern="parallel",
        members=[_agent("alpha"), _agent("beta")],
        aggregation_strategy="vote",
    )
    assert group.aggregation_strategy == "vote"
