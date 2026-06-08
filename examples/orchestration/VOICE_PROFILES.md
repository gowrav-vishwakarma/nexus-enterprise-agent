# Indian voice profiles (provisional defaults)

Run benchmarks in `local-ai-stack/benchmarks/` before changing defaults.
Always `./stop-all.sh` in local-ai-stack before switching profiles (24 GB VRAM).

## Feature flags (env)

| Profile | Stack launcher | Manifest | Key env |
|---------|----------------|----------|---------|
| Cascade English | `run-cascade-oss.sh` | `voice_local.yaml` | `NEXUS_LLM_BASE_URL=http://localhost:11434/v1` |
| **Cascade Hindi** | `run-cascade-indic.sh` | `voice_local_indic.yaml` | `NEXUS_STT_LANGUAGE=hi`, `NEXUS_TTS_VOICE=Divya` |
| Cascade Hindi (Kokoro) | `run-cascade-indic-kokoro.sh` | `voice_local_indic_kokoro.yaml` | `NEXUS_STT_LANGUAGE=hi`, `NEXUS_TTS_VOICE=hf_alpha` |
| S2S Moshi | `run-s2s-moshi.sh` | `voice_s2s_local.yaml` | `NEXUS_S2S_PROVIDER=moshi` |
| S2S Human-1 | `run-s2s-human1.sh` | `voice_s2s_local.yaml` | `NEXUS_S2S_PROVIDER=human-1` |

## Defaults (from benchmark runs — see `local-ai-stack/benchmarks/RESULTS.md`)

- **English cascade:** `voice_local.yaml` — Whisper + Kokoro + Ollama.
- **Hindi cascade:** `voice_local_indic.yaml` — Indic-Conformer STT + Indic Parler TTS + Ollama (Qwen/Gemma/gpt-oss).
- **Hindi cascade (Kokoro):** `voice_local_indic_kokoro.yaml` — Indic-Conformer STT + Kokoro Hindi TTS + Ollama (lighter TTS alternative).
- **S2S:** experimental. Moshi is English-only. Use `human-1` for Hindi after `./stop-all.sh && ./run-s2s-human1.sh`.

Re-run benchmarks after changing models; update `RESULTS.md`.
