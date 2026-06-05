"""Tests for Nexus SaaS example LLM config factory."""

from pydantic import SecretStr

from examples.nexus_saas_api import (
    MOCK_TENANTS_DB,
    NexusTenantConfigFactory,
    PLAN_LIMITS,
    Plan,
    TenantRecord,
)


def test_build_llm_config_uses_env_when_base_url_set(monkeypatch):
    monkeypatch.setenv("NEXUS_LLM_PROVIDER", "litellm")
    monkeypatch.setenv("NEXUS_LLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("NEXUS_LLM_API_KEY", "proxy-key")
    monkeypatch.setenv("NEXUS_LLM_MODEL", "openai/qwen")

    tenant = TenantRecord(tenant_id="t1", name="Test Co", plan=Plan.PRO)
    limits = PLAN_LIMITS[Plan.PRO]
    config = NexusTenantConfigFactory.build_llm_config(tenant, limits)

    assert config.provider == "litellm"
    assert config.base_url == "http://litellm:4000"
    assert config.model == "openai/qwen"
    assert config.get_api_key() == "proxy-key"


def test_build_llm_config_env_wins_over_tenant_byok(monkeypatch):
    monkeypatch.setenv("NEXUS_LLM_PROVIDER", "litellm")
    monkeypatch.setenv("NEXUS_LLM_BASE_URL", "http://litellm:4000")
    monkeypatch.setenv("NEXUS_LLM_API_KEY", "proxy-key")
    monkeypatch.setenv("NEXUS_LLM_MODEL", "openai/qwen")

    tenant = TenantRecord(
        tenant_id="t2",
        name="BYOK Co",
        plan=Plan.PRO,
        openai_api_key=SecretStr("sk-tenant-openai"),
        preferred_model="gpt-4o",
    )
    limits = PLAN_LIMITS[Plan.PRO]
    config = NexusTenantConfigFactory.build_llm_config(tenant, limits)

    assert config.provider == "litellm"
    assert config.base_url == "http://litellm:4000"
    assert config.model == "openai/qwen"


def test_build_llm_config_falls_back_to_tenant_byok_without_env(monkeypatch):
    monkeypatch.delenv("NEXUS_LLM_BASE_URL", raising=False)

    tenant = TenantRecord(
        tenant_id="t3",
        name="BYOK Co",
        plan=Plan.PRO,
        openai_api_key=SecretStr("sk-tenant-openai"),
        preferred_model="gpt-4o",
    )
    limits = PLAN_LIMITS[Plan.PRO]
    config = NexusTenantConfigFactory.build_llm_config(tenant, limits)

    assert config.provider == "openai"
    assert config.base_url is None
    assert config.model == "gpt-4o"
    assert config.get_api_key() == "sk-tenant-openai"


def test_build_llm_config_platform_fallback_for_free_tenant(monkeypatch):
    monkeypatch.delenv("NEXUS_LLM_BASE_URL", raising=False)

    tenant = MOCK_TENANTS_DB["free_tenant_1"]
    limits = PLAN_LIMITS[tenant.plan]
    config = NexusTenantConfigFactory.build_llm_config(tenant, limits)

    assert config.provider == "openai"
    assert config.base_url is None
    assert config.model == limits.default_model
