"""
Speech-to-Text (STT) providers.

Provides speech recognition capabilities for the AI Interviewer.
Supports local Whisper, faster-whisper, and cloud Groq Whisper backends.

The unified factory (get_stt_provider / get_stt_provider_async) reads
config/models.yaml to decide which backend to use and which model /
device / compute_type to load.  All consumers should use the unified
factory instead of the provider-specific ones.
"""
import logging
from typing import Optional

from src.providers.stt.base import (
    BaseSTTProvider,
    STTProvider,
    WhisperModel,
    TranscriptionResult,
    TranscriptionSegment,
)

try:
    from src.providers.stt.whisper_provider import (
        WhisperSTTProvider,
        get_whisper_provider,
        get_whisper_provider_async,
    )
except ImportError:
    WhisperSTTProvider = None  # type: ignore[assignment,misc]
    get_whisper_provider = None  # type: ignore[assignment]
    get_whisper_provider_async = None  # type: ignore[assignment]
    logging.getLogger(__name__).info(
        "OpenAI Whisper not installed — only faster-whisper backend available"
    )

from src.providers.stt.faster_whisper_provider import (
    FasterWhisperSTTProvider,
    get_faster_whisper_provider,
    get_faster_whisper_provider_async,
)

logger = logging.getLogger(__name__)

# Singleton managed by the unified factory
_stt_provider = None


def get_stt_provider():
    """
    Get or create the STT provider singleton, configured from models.yaml.

    Reads ``providers.stt`` from config/models.yaml:
      - provider  : "faster-whisper" | "whisper"
      - model     : e.g. "large-v3"
      - device    : e.g. "cuda", "cpu", or None (auto)
      - compute_type: e.g. "int8", "float16"
      - language  : e.g. "en" or "auto"

    Returns the appropriate provider instance (singleton).
    """
    global _stt_provider
    if _stt_provider is not None:
        return _stt_provider

    # Read config
    try:
        from src.core.config import load_model_config
        config = load_model_config()
        stt_cfg = config.get("providers", {}).get("stt", {})
    except Exception as e:
        logger.warning(f"Failed to load models.yaml, using defaults: {e}")
        stt_cfg = {}

    provider_name = stt_cfg.get("provider", "faster-whisper")
    model_name = stt_cfg.get("model", "base")
    device = stt_cfg.get("device", None)
    compute_type = stt_cfg.get("compute_type", "float16")
    language = stt_cfg.get("language", "en")

    # Normalise "auto" language to None (let Whisper auto-detect)
    if language and language.lower() == "auto":
        language = None

    logger.info(
        f"STT config: provider={provider_name}, model={model_name}, "
        f"device={device}, compute_type={compute_type}, language={language}"
    )

    if provider_name == "faster-whisper":
        _stt_provider = FasterWhisperSTTProvider(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
            language=language,
        )
    elif provider_name == "groq-whisper":
        from src.core.config import get_settings as _get_settings
        _settings = _get_settings()
        from src.providers.stt.groq_whisper_provider import GroqWhisperSTTProvider
        _stt_provider = GroqWhisperSTTProvider(
            model_name=model_name or "whisper-large-v3-turbo",
            api_key=_settings.groq_api_key,
            api_url=_settings.groq_api_url,
            language=language,
        )
    elif WhisperSTTProvider is not None:
        # Original Whisper
        _stt_provider = WhisperSTTProvider(
            model_name=model_name,
            device=device,
            language=language,
        )
    else:
        raise ImportError(
            "STT provider set to 'whisper' but the openai-whisper package "
            "is not installed. Install it with: pip install openai-whisper  "
            "Or switch to 'faster-whisper' in config/models.yaml."
        )

    return _stt_provider


async def get_stt_provider_async():
    """Async version of get_stt_provider."""
    return get_stt_provider()


__all__ = [
    # Base classes (shared by all providers)
    "BaseSTTProvider",
    "STTProvider",
    "WhisperModel",
    "TranscriptionResult",
    "TranscriptionSegment",
    # Original Whisper
    "WhisperSTTProvider",
    "get_whisper_provider",
    "get_whisper_provider_async",
    # Faster Whisper (recommended)
    "FasterWhisperSTTProvider",
    "get_faster_whisper_provider",
    "get_faster_whisper_provider_async",
    # Unified config-aware factory (preferred)
    "get_stt_provider",
    "get_stt_provider_async",
]
