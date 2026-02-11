"""
Text-to-Speech (TTS) providers.

Provides speech synthesis capabilities for the AI Interviewer.
Supports Coqui XTTS v2 (recommended), pyttsx3 (fallback), and
Groq cloud TTS (Orpheus).

The unified factory (get_tts_provider / get_tts_provider_async) reads
config/models.yaml to decide which backend to use and which model /
device / reference_audio to load.  All consumers should use the unified
factory instead of the provider-specific ones.
"""
import logging
from typing import Optional

from src.providers.tts.base import (
    BaseTTSProvider,
    TTSProvider,
    VoiceGender,
    VoiceInfo,
    SynthesisResult,
)
try:
    from src.providers.tts.pyttsx3_provider import (
        Pyttsx3TTSProvider,
        get_tts_provider as get_pyttsx3_provider,
        get_tts_provider_async as get_pyttsx3_provider_async,
    )
except ImportError:
    Pyttsx3TTSProvider = None  # type: ignore[assignment,misc]
    get_pyttsx3_provider = None  # type: ignore[assignment]
    get_pyttsx3_provider_async = None  # type: ignore[assignment]
    logging.getLogger(__name__).info(
        "pyttsx3 not installed — only Groq/Coqui TTS backends available"
    )

logger = logging.getLogger(__name__)

# Singleton managed by the unified factory
_tts_provider = None


def get_tts_provider():
    """
    Get or create the TTS provider singleton, configured from models.yaml.

    Reads ``providers.tts`` from config/models.yaml:
      - provider       : "coqui-xtts" | "pyttsx3"
      - model          : e.g. "tts_models/multilingual/multi-dataset/xtts_v2"
      - device         : "cuda", "cpu", or "auto"
      - reference_audio: path to WAV for voice cloning (XTTS only)

    Falls back to pyttsx3 if the selected provider fails to import or
    initialise.
    """
    global _tts_provider
    if _tts_provider is not None:
        return _tts_provider

    # Read config -------------------------------------------------------
    try:
        from src.core.config import load_model_config
        config = load_model_config()
        tts_cfg = config.get("providers", {}).get("tts", {})
    except Exception as e:
        logger.warning("Failed to load models.yaml, using defaults: %s", e)
        tts_cfg = {}

    provider_name = tts_cfg.get("provider", "pyttsx3")
    model_name = tts_cfg.get("model", None)
    device = tts_cfg.get("device", None)
    reference_audio = tts_cfg.get("reference_audio", None)
    speaker = tts_cfg.get("speaker", None)

    logger.info(
        "TTS config: provider=%s, model=%s, device=%s, "
        "reference_audio=%s, speaker=%s",
        provider_name,
        model_name or "(default)",
        device or "(auto)",
        reference_audio or "(none)",
        speaker or "(default)",
    )

    # Instantiate provider -----------------------------------------------
    if provider_name == "coqui-xtts":
        try:
            from src.providers.tts.coqui_xtts_provider import CoquiXTTSProvider

            kwargs = {"language": "en"}
            if model_name:
                kwargs["model_name"] = model_name
            if device:
                kwargs["device"] = device
            if reference_audio:
                kwargs["reference_audio"] = reference_audio
            if speaker:
                kwargs["speaker"] = speaker

            _tts_provider = CoquiXTTSProvider(**kwargs)
            logger.info("Using Coqui XTTS v2 TTS provider")
            return _tts_provider

        except ImportError:
            logger.warning(
                "Coqui TTS package not installed (pip install TTS). "
                "Falling back to pyttsx3."
            )
        except Exception as e:
            logger.warning(
                "Failed to initialise Coqui XTTS provider: %s. "
                "Falling back to pyttsx3.",
                e,
            )

    elif provider_name == "groq-orpheus" or provider_name == "groq-tts":
        try:
            from src.core.config import get_settings as _get_settings
            _settings = _get_settings()
            from src.providers.tts.groq_tts_provider import GroqTTSProvider

            _tts_provider = GroqTTSProvider(
                model=model_name or "canopylabs/orpheus-v1-english",
                voice=tts_cfg.get("voice", "troy"),
                api_key=_settings.groq_api_key,
                api_url=_settings.groq_api_url,
            )
            logger.info("Using Groq TTS provider")
            return _tts_provider

        except Exception as e:
            logger.warning(
                "Failed to initialise Groq TTS provider: %s. "
                "Falling back to pyttsx3.",
                e,
            )

    # Default / fallback: pyttsx3 ----------------------------------------
    if get_pyttsx3_provider is not None:
        logger.info("Using pyttsx3 TTS provider")
        _tts_provider = get_pyttsx3_provider()
        return _tts_provider

    raise RuntimeError(
        "No TTS provider available. Install pyttsx3 for local fallback, "
        "or configure groq-tts / coqui-xtts in config/models.yaml."
    )


async def get_tts_provider_async():
    """Async version of get_tts_provider."""
    return get_tts_provider()


__all__ = [
    # Base classes (shared by all providers)
    "BaseTTSProvider",
    "TTSProvider",
    "VoiceGender",
    "VoiceInfo",
    "SynthesisResult",
    # Provider classes
    "Pyttsx3TTSProvider",
    # Provider-specific factories (backward compat)
    "get_pyttsx3_provider",
    "get_pyttsx3_provider_async",
    # Unified config-aware factory (preferred)
    "get_tts_provider",
    "get_tts_provider_async",
]
