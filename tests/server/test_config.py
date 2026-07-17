"""Tests for media server configuration."""

from nexus.server.config import ModelServerSpec, ServersConfig


def test_model_server_spec_endpoint():
    spec = ModelServerSpec(kind="stt", engine="mock", port=50051)
    assert spec.endpoint == "127.0.0.1:50051"


def test_servers_config_get():
    cfg = ServersConfig(
        servers={
            "stt_main": ModelServerSpec(kind="stt", engine="mock", port=50051),
        }
    )
    assert cfg.get("stt_main").engine == "mock"


def test_servers_config_unknown_raises():
    cfg = ServersConfig()
    try:
        cfg.get("missing")
        assert False, "expected KeyError"
    except KeyError as exc:
        assert "missing" in str(exc)
