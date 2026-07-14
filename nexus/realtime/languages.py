"""Indian-language routing for realtime voice agents.

Per-language TTS voice descriptions and spoken language-switch detection,
ported from ankpal-voice for per-turn LID + sticky LLM/TTS overrides.
"""

from __future__ import annotations

from dataclasses import dataclass


def _desc(speaker: str) -> str:
    return (
        f"{speaker} speaks in a clear, natural and expressive voice at a moderate "
        f"pace, in a very quiet environment with high audio quality."
    )


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    tts_description: str


LANGUAGES: dict[str, Language] = {
    "hi": Language("hi", "Hindi", _desc("Divya")),
    "en": Language("en", "English", _desc("Divya")),
    "ta": Language("ta", "Tamil", _desc("Jaya")),
    "te": Language("te", "Telugu", _desc("Prakash")),
    "bn": Language("bn", "Bengali", _desc("Aditi")),
    "mr": Language("mr", "Marathi", _desc("Sanjay")),
    "gu": Language("gu", "Gujarati", _desc("Neha")),
}

DEFAULT_LANGUAGE = "hi"

LANG_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "hi": ("hindi", "हिंदी", "हिन्दी"),
    "en": ("english", "इंग्लिश", "अंग्रेज़ी", "अंग्रेजी", "angrezi"),
    "gu": ("gujarati", "gujrati", "ગુજરાતી", "गुजराती", "gujju"),
    "ta": ("tamil", "தமிழ்", "तमिल", "தமிழ"),
    "te": ("telugu", "తెలుగు", "तेलुगु", "तेलुगू"),
    "bn": ("bengali", "bangla", "বাংলা", "बंगाली", "बांग्ला"),
    "mr": ("marathi", "मराठी", "मराठि"),
}

_SWITCH_INTENT_TOKENS: tuple[str, ...] = (
    "talk",
    "speak",
    "reply",
    "answer",
    "say",
    "language",
    "switch",
    "change",
    "बात",
    "बोल",
    "बोलो",
    "जवाब",
    "भाषा",
    "बदल",
    "बताओ",
    "करो",
)


def resolve(code: str | None) -> Language:
    """Return the Language record for a code, defaulting to Hindi."""
    if not code:
        return LANGUAGES[DEFAULT_LANGUAGE]
    return LANGUAGES.get(code.lower().split("-")[0], LANGUAGES[DEFAULT_LANGUAGE])


def tts_voice_for(code: str | None, default_voice: str | None = None) -> str:
    """Parler-style voice description for the given language code."""
    if default_voice and not code:
        return default_voice
    return resolve(code).tts_description


def detect_language_request(
    text: str | None,
    *,
    allowed: frozenset[str] | None = None,
) -> str | None:
    """Detect an explicit spoken language-switch request in transcript text."""
    if not text:
        return None
    lowered = text.lower()
    has_intent = any(tok in lowered for tok in _SWITCH_INTENT_TOKENS)
    if not has_intent:
        return None
    for code, aliases in LANG_NAME_ALIASES.items():
        if allowed is not None and code not in allowed:
            continue
        if any(alias in lowered for alias in aliases):
            return code
    return None
