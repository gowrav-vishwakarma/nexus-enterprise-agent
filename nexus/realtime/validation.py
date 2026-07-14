"""Startup validation for voice agent language configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

from nexus.realtime.config import RealtimeAgentConfig
from nexus.realtime.languages import LANGUAGES
from nexus.server.config import ModelServerSpec
from nexus.server.engines.base import EngineKind, available
from nexus.server.registry import ServerRegistry

logger = logging.getLogger(__name__)

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class LanguageValidationIssue:
    severity: Severity
    code: str
    message: str


def _norm(code: str) -> str:
    return code.lower().split("-")[0]


def _static_engine_languages(kind: EngineKind, engine_id: str) -> frozenset[str]:
    for meta in available(kind):
        if meta.id == engine_id:
            return frozenset(_norm(lang) for lang in meta.languages)
    return frozenset()


def _server_spec(
    servers: dict[str, ModelServerSpec] | None,
    server_ref: str | None,
) -> ModelServerSpec | None:
    if not servers or not server_ref:
        return None
    return servers.get(server_ref)


def _check_server_ref(
    issues: list[LanguageValidationIssue],
    *,
    role: str,
    provider: str,
    server_ref: str | None,
    servers: dict[str, ModelServerSpec] | None,
) -> None:
    if provider != "nexus_server":
        return
    if not server_ref:
        issues.append(
            LanguageValidationIssue(
                "error",
                f"{role}_missing_server_ref",
                f"{role} provider is nexus_server but server_ref is unset",
            )
        )
        return
    if servers is not None and server_ref not in servers:
        issues.append(
            LanguageValidationIssue(
                "error",
                f"{role}_unknown_server_ref",
                f"{role} server_ref {server_ref!r} not found in manifest servers:",
            )
        )


def _check_langs_vs_engine(
    issues: list[LanguageValidationIssue],
    *,
    role: str,
    allowed: frozenset[str],
    engine_langs: frozenset[str],
    skip_codes: frozenset[str] = frozenset(),
) -> None:
    if not engine_langs:
        return
    for lang in sorted(allowed):
        if lang in skip_codes:
            continue
        if lang not in engine_langs:
            issues.append(
                LanguageValidationIssue(
                    "warning",
                    f"{role.lower()}_lang_unsupported",
                    f"Language {lang!r} is allowed but {role} engine supports "
                    f"{', '.join(sorted(engine_langs)) or '(none)'}",
                )
            )


def validate_voice_languages_static(
    rt_config: RealtimeAgentConfig,
    *,
    servers: dict[str, ModelServerSpec] | None = None,
) -> list[LanguageValidationIssue]:
    """Validate language config using manifest + static EngineMeta (no gRPC)."""
    issues: list[LanguageValidationIssue] = []
    langs = rt_config.effective_languages()
    allowed = frozenset(_norm(code) for code in langs.allowed)
    default = _norm(langs.default or rt_config.effective_stt().language or "hi")
    stt = rt_config.effective_stt()
    tts = rt_config.effective_tts()
    lid = rt_config.effective_lid()

    for code in allowed:
        if code not in LANGUAGES:
            issues.append(
                LanguageValidationIssue(
                    "error",
                    "unknown_language",
                    f"Unknown language code {code!r} in languages.allowed",
                )
            )

    for label, code in (
        ("languages.default", default),
        ("stt.language", _norm(stt.language)),
    ):
        if code not in allowed:
            issues.append(
                LanguageValidationIssue(
                    "warning",
                    "fallback_not_allowed",
                    f"{label}={code!r} is not in languages.allowed",
                )
            )

    if lid and _norm(lid.fallback_language) not in allowed:
        issues.append(
            LanguageValidationIssue(
                "warning",
                "lid_fallback_not_allowed",
                f"lid.fallback_language={lid.fallback_language!r} is not in languages.allowed",
            )
        )

    if "en" in allowed and lid is None:
        issues.append(
            LanguageValidationIssue(
                "warning",
                "en_requires_lid",
                "English in languages.allowed requires lid (or a Whisper/faster_whisper STT "
                "instead of Indic-Conformer)",
            )
        )

    _check_server_ref(issues, role="stt", provider=stt.provider, server_ref=stt.server_ref, servers=servers)
    _check_server_ref(issues, role="tts", provider=tts.provider, server_ref=tts.server_ref, servers=servers)
    if lid:
        _check_server_ref(
            issues, role="lid", provider=lid.provider, server_ref=lid.server_ref, servers=servers
        )

    stt_spec = _server_spec(servers, stt.server_ref)
    tts_spec = _server_spec(servers, tts.server_ref)
    lid_spec = _server_spec(servers, lid.server_ref) if lid else None

    stt_engine = stt_spec.engine if stt_spec else None
    tts_engine = tts_spec.engine if tts_spec else None
    lid_engine = lid_spec.engine if lid_spec else None

    stt_langs = _static_engine_languages("stt", stt_engine) if stt_engine else frozenset()
    tts_langs = _static_engine_languages("tts", tts_engine) if tts_engine else frozenset()
    lid_langs = _static_engine_languages("lid", lid_engine) if lid_engine else frozenset()

    stt_skip = frozenset({"en"}) if lid is not None and stt_engine == "conformer" else frozenset()
    _check_langs_vs_engine(
        issues, role="STT", allowed=allowed, engine_langs=stt_langs, skip_codes=stt_skip
    )
    _check_langs_vs_engine(issues, role="TTS", allowed=allowed, engine_langs=tts_langs)
    if lid:
        _check_langs_vs_engine(issues, role="LID", allowed=allowed, engine_langs=lid_langs)

    if "en" in allowed and lid is not None and stt_engine == "conformer":
        lid_ref = lid.server_ref or "(mock)"
        issues.append(
            LanguageValidationIssue(
                "warning",
                "en_lid_ok",
                f"English in languages.allowed requires lid — OK ({lid_ref} configured)",
            )
        )

    issues.extend(_validate_initial_response(rt_config))
    return issues


def _validate_initial_response(rt_config: RealtimeAgentConfig) -> list[LanguageValidationIssue]:
    """Validate connect-time initial_response config."""
    issues: list[LanguageValidationIssue] = []
    ir = rt_config.effective_initial_response()
    if ir.mode == "none":
        return issues

    if ir.mode == "proactive" and not ir.via_llm and not ir.text:
        issues.append(
            LanguageValidationIssue(
                "error",
                "initial_response_missing_text",
                "initial_response mode proactive with via_llm: false requires text",
            )
        )

    if ir.mode == "ivr":
        if rt_config.duplex != "half":
            issues.append(
                LanguageValidationIssue(
                    "warning",
                    "initial_response_ivr_not_half_duplex",
                    "initial_response mode ivr works best with duplex: half",
                )
            )
        if ir.via_llm and "ivr_menu" not in rt_config.agent.tool_plugins:
            issues.append(
                LanguageValidationIssue(
                    "warning",
                    "initial_response_ivr_no_plugin",
                    "initial_response mode ivr with via_llm: true requires ivr_menu tool plugin",
                )
            )
        if not ir.via_llm and not ir.ivr_script and not ir.text:
            issues.append(
                LanguageValidationIssue(
                    "error",
                    "initial_response_missing_script",
                    "initial_response mode ivr with via_llm: false requires ivr_script or text",
                )
            )

    return issues


async def _live_engine_languages(
    server_registry: ServerRegistry,
    server_ref: str,
) -> frozenset[str] | None:
    try:
        meta = await server_registry.fetch_meta(server_ref)
        return frozenset(_norm(lang) for lang in meta.languages)
    except Exception as exc:
        logger.debug("Live Meta fetch failed for %s: %s", server_ref, exc)
        return None


async def validate_voice_languages(
    rt_config: RealtimeAgentConfig,
    *,
    servers: dict[str, ModelServerSpec] | None = None,
    server_registry: ServerRegistry | None = None,
) -> list[LanguageValidationIssue]:
    """Validate language config with optional live gRPC Meta when servers are up."""
    issues = validate_voice_languages_static(rt_config, servers=servers)
    if server_registry is None:
        return issues

    langs = rt_config.effective_languages()
    allowed = frozenset(_norm(code) for code in langs.allowed)
    stt = rt_config.effective_stt()
    tts = rt_config.effective_tts()
    lid = rt_config.effective_lid()

    live_checks: list[tuple[str, str | None, frozenset[str]]] = []
    if stt.server_ref:
        live = await _live_engine_languages(server_registry, stt.server_ref)
        if live is not None:
            live_checks.append(("STT", stt.server_ref, live))
    if tts.server_ref:
        live = await _live_engine_languages(server_registry, tts.server_ref)
        if live is not None:
            live_checks.append(("TTS", tts.server_ref, live))
    if lid and lid.server_ref:
        live = await _live_engine_languages(server_registry, lid.server_ref)
        if live is not None:
            live_checks.append(("LID", lid.server_ref, live))

    stt_spec = _server_spec(servers, stt.server_ref)
    stt_skip = frozenset({"en"}) if lid is not None and stt_spec and stt_spec.engine == "conformer" else frozenset()

    for role, server_ref, engine_langs in live_checks:
        for lang in sorted(allowed):
            if lang in stt_skip and role == "STT":
                continue
            if lang not in engine_langs:
                issues.append(
                    LanguageValidationIssue(
                        "warning",
                        f"{role.lower()}_lang_unsupported_live",
                        f"Language {lang!r} is allowed but live Meta for {server_ref!r} "
                        f"reports {', '.join(sorted(engine_langs)) or '(none)'}",
                    )
                )

    return issues


def _strict_enabled(strict: bool | None) -> bool:
    if strict is not None:
        return strict
    return os.environ.get("NEXUS_VOICE_STRICT_LANG", "").strip() in ("1", "true", "yes")


def log_validation_issues(
    issues: list[LanguageValidationIssue],
    *,
    rt_config: RealtimeAgentConfig | None = None,
    servers: dict[str, ModelServerSpec] | None = None,
    strict: bool | None = None,
) -> None:
    """Log validation issues; raise on errors when strict mode is enabled."""
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning" and i.code != "en_lid_ok"]

    for issue in issues:
        if issue.severity == "error":
            logger.error("%s", issue.message)
        elif issue.code == "en_lid_ok":
            logger.info("%s", issue.message)
        else:
            logger.warning("%s", issue.message)

    if rt_config is not None and not errors and not warnings:
        langs = rt_config.effective_languages()
        stt = rt_config.effective_stt()
        tts = rt_config.effective_tts()
        lid = rt_config.effective_lid()
        stt_engine = _server_spec(servers, stt.server_ref).engine if servers and stt.server_ref else "?"
        tts_engine = _server_spec(servers, tts.server_ref).engine if servers and tts.server_ref else "?"
        lid_engine = (
            _server_spec(servers, lid.server_ref).engine if servers and lid and lid.server_ref else None
        )
        logger.info(
            "Language stack OK — allowed=[%s] stt=%s tts=%s lid=%s",
            ",".join(langs.allowed),
            stt_engine,
            tts_engine,
            lid_engine or "(none)",
        )

    if _strict_enabled(strict) and errors:
        detail = "; ".join(i.message for i in errors)
        raise RuntimeError(f"Voice language validation failed: {detail}")


async def run_startup_language_validation(
    rt_config: RealtimeAgentConfig,
    *,
    servers: dict[str, ModelServerSpec] | None = None,
    server_registry: ServerRegistry | None = None,
    strict: bool | None = None,
) -> list[LanguageValidationIssue]:
    """Run full validation (static + live Meta) and log results."""
    issues = await validate_voice_languages(
        rt_config,
        servers=servers,
        server_registry=server_registry,
    )
    log_validation_issues(issues, rt_config=rt_config, servers=servers, strict=strict)
    return issues
