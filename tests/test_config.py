"""Tests for configuration parsing and defaults."""

from pydantic import ValidationError
import pytest

from nexus.config import (
    AgentConfig,
    AgentPersonaConfig,
    LLMProviderConfig,
    RuntimeContextSummarizerConfig,
    ServerCompactorConfig,
    SessionStorageConfig,
)


def test_llm_provider_config_validation():
    """Test that LLMProviderConfig validates required fields and types."""
    # Valid config with explicit key
    config = LLMProviderConfig(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test-key",
    )
    assert config.provider == "openai"
    assert config.model == "gpt-4o"
    assert config.api_key.get_secret_value() == "sk-test-key"

    # api_key defaults to empty string — design intentional so litellm/env-based
    # providers can be used without an explicit key in code.
    config_no_key = LLMProviderConfig(provider="openai", model="gpt-4o")
    assert config_no_key.get_api_key() == ""


def test_agent_config_defaults():
    """Test that AgentConfig initializes defaults correctly."""
    llm_config = LLMProviderConfig(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test-key",
    )
    agent = AgentConfig(
        name="test-agent",
        llm=llm_config,
    )
    assert agent.name == "test-agent"
    assert agent.persona.role == "Assistant"
    assert agent.turns.max_turns == 10
    assert agent.rcs.enabled is False
    assert agent.storage is None
    assert agent.trace_enabled is False
    assert agent.trace_sink == "stdout"


def test_rcs_config_validation():
    """Test RCS configuration values and defaults."""
    rcs = RuntimeContextSummarizerConfig(enabled=True)
    assert rcs.enabled is True
    assert rcs.tc_tag_format == "[TC{n}]"
    assert rcs.fallback_compactor.enabled is False
    
    # Check custom tags
    rcs_custom = RuntimeContextSummarizerConfig(
        enabled=True,
        tc_tag_format="<TC_TAG_{n}>",
    )
    assert rcs_custom.tc_tag_format == "<TC_TAG_{n}>"
