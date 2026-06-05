"""Voice pipelines: cascaded (STT->LLM->TTS) and speech-to-speech."""

from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline

__all__ = ["CascadedVoicePipeline"]
