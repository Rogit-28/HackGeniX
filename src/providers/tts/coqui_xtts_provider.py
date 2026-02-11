"""
Text-to-Speech provider using Coqui XTTS v2.

Uses the XTTS v2 model for high-quality, natural-sounding speech synthesis
with optional voice cloning from a reference audio sample.

Requires the `TTS` pip package (coqui-tts).  Model weights (~1.8 GB) are
downloaded automatically on first use and cached in the default HuggingFace
/ Coqui cache directory.
"""
import io
import logging
import tempfile
import asyncio
import wave
from pathlib import Path
from typing import Optional, Dict, Any, List

import numpy as np

from src.providers.tts.base import (
    BaseTTSProvider,
    VoiceInfo,
    SynthesisResult,
    VoiceGender,
)

logger = logging.getLogger(__name__)

# Default XTTS v2 model identifier used by the Coqui TTS library.
DEFAULT_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

# XTTS v2 outputs audio at 24 kHz.
XTTS_SAMPLE_RATE = 24000

# Default built-in speaker (one of 58 in the XTTS v2 model).  Used when no
# reference audio (speaker_wav) is provided for voice cloning.
DEFAULT_SPEAKER = "Claribel Dervla"


class CoquiXTTSProvider(BaseTTSProvider):
    """
    Text-to-Speech provider using Coqui XTTS v2.

    Features:
    - High-quality neural speech synthesis
    - Voice cloning from a short reference audio clip (~6-15 s)
    - Multilingual support (English, Spanish, French, German, …)
    - GPU or CPU inference (auto-detected, configurable)
    - Async-compatible via thread-pool offloading

    The provider is designed as a drop-in replacement for
    ``Pyttsx3TTSProvider`` — it exposes the same public interface
    (``synthesize``, ``get_provider_info``, ``get_voices``, …) so the
    rest of the application can remain unchanged.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: Optional[str] = None,
        reference_audio: Optional[str] = None,
        speaker_wav: Optional[str] = None,
        speaker: Optional[str] = None,
        language: str = "en",
    ):
        """
        Initialise the XTTS provider.

        Args:
            model_name: Coqui TTS model identifier.
            device: ``"cuda"``, ``"cpu"``, or ``None`` / ``"auto"`` for
                    automatic detection.
            reference_audio: Path to a WAV file (6-15 s) used for voice
                             cloning.  If ``None``, XTTS uses a built-in
                             speaker embedding instead.
            speaker_wav: Alias for *reference_audio* (takes precedence).
            speaker: Name of a built-in XTTS speaker to use when no
                     *speaker_wav* is provided (default: ``"Claribel Dervla"``).
            language: Language code for synthesis (default ``"en"``).
        """
        self.model_name = model_name
        self.language = language
        self._tts = None  # Lazy-loaded TTS model
        self._device: str = self._resolve_device(device)
        self._reference_audio: Optional[str] = speaker_wav or reference_audio
        self._speaker: str = speaker or DEFAULT_SPEAKER
        self._model_loaded = False

        # Validate reference audio path early (warn, don't crash).
        if self._reference_audio and not Path(self._reference_audio).is_file():
            logger.warning(
                "Reference audio file not found: %s  — XTTS will use its "
                "default speaker embedding instead.",
                self._reference_audio,
            )
            self._reference_audio = None

        logger.info(
            "CoquiXTTSProvider configured: model=%s, device=%s, "
            "reference_audio=%s, speaker=%s, language=%s",
            self.model_name,
            self._device,
            self._reference_audio or "(none)",
            self._speaker,
            self.language,
        )

    # ------------------------------------------------------------------
    # Device detection
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_device(device: Optional[str]) -> str:
        """Pick the best available device.

        If *device* is explicitly ``"cuda"`` but CUDA is not available,
        fall back to ``"cpu"`` with a warning rather than crashing later
        when ``TTS.to("cuda")`` is called.
        """
        cuda_available = False
        try:
            import torch
            cuda_available = torch.cuda.is_available()
        except ImportError:
            pass

        if device and device.lower() not in ("auto", "none"):
            requested = device.lower()
            if requested == "cuda" and not cuda_available:
                logger.warning(
                    "TTS config requests device='cuda' but CUDA is not "
                    "available (torch.cuda.is_available() = False). "
                    "Falling back to CPU.  Install CUDA PyTorch for GPU "
                    "acceleration: pip install torch --index-url "
                    "https://download.pytorch.org/whl/cu121"
                )
                return "cpu"
            return requested

        # Auto-detect
        return "cuda" if cuda_available else "cpu"

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def _load_model(self):
        """Load the TTS model (blocking — call from a thread)."""
        if self._tts is not None:
            return

        logger.info(
            "Loading Coqui XTTS model '%s' on %s (this may take 30-60 s "
            "on first run while weights are downloaded) …",
            self.model_name,
            self._device,
        )

        # Monkey-patch the TOS prompt so model download doesn't block on
        # interactive input.  XTTS v2 uses the CPML non-commercial license.
        # By using this provider the user implicitly agrees.
        try:
            from TTS.utils.manage import ModelManager

            _orig_ask_tos = ModelManager.ask_tos

            @staticmethod
            def _auto_accept_tos(model_full_path):
                """Auto-accept Coqui CPML license."""
                import os
                os.makedirs(model_full_path, exist_ok=True)
                tos_path = os.path.join(model_full_path, "tos_agreed.txt")
                with open(tos_path, "w", encoding="utf-8") as f:
                    f.write(
                        "I have read, understood and agreed to the "
                        "Terms and Conditions."
                    )
                logger.info(
                    "Auto-accepted Coqui CPML license (non-commercial)"
                )
                return True

            ModelManager.ask_tos = _auto_accept_tos
        except ImportError:
            pass

        from TTS.api import TTS  # Heavy import — keep lazy

        # PyTorch 2.6+ changed torch.load() default to weights_only=True,
        # which breaks Coqui TTS model loading (pickle-based checkpoints).
        # Temporarily patch torch.load to use weights_only=False.
        import torch
        _original_torch_load = torch.load

        def _patched_torch_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return _original_torch_load(*args, **kwargs)

        torch.load = _patched_torch_load
        try:
            self._tts = TTS(model_name=self.model_name).to(self._device)
        finally:
            torch.load = _original_torch_load
        self._model_loaded = True

        # Restore original ask_tos (good hygiene)
        try:
            ModelManager.ask_tos = _orig_ask_tos
        except (NameError, UnboundLocalError):
            pass

        logger.info(
            "Coqui XTTS model loaded successfully on %s", self._device
        )

    async def ensure_loaded(self):
        """Ensure the model is loaded (async-safe)."""
        if self._tts is None:
            await asyncio.to_thread(self._load_model)

    # ------------------------------------------------------------------
    # Core synthesis
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        rate: Optional[int] = None,
        output_format: str = "wav",
    ) -> SynthesisResult:
        """
        Synthesize text to speech.

        Args:
            text: Text to convert to speech.
            voice_id: Unused for XTTS (kept for interface compat).
            rate: Unused for XTTS (neural model controls its own pacing).
            output_format: Only ``"wav"`` is supported.

        Returns:
            ``SynthesisResult`` with raw WAV bytes.
        """
        if not text.strip():
            raise ValueError("Text cannot be empty")

        await self.ensure_loaded()

        result = await asyncio.to_thread(
            self._synthesize_sync, text, voice_id
        )
        return result

    def _synthesize_sync(
        self,
        text: str,
        voice_id: Optional[str] = None,
    ) -> SynthesisResult:
        """Blocking synthesis implementation."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        try:
            # Build kwargs for tts_to_file
            kwargs: Dict[str, Any] = {
                "text": text,
                "file_path": temp_path,
                "language": self.language,
            }
            if self._reference_audio:
                kwargs["speaker_wav"] = self._reference_audio
            else:
                # Use built-in speaker embedding (XTTS v2 is multi-speaker)
                kwargs["speaker"] = self._speaker

            self._tts.tts_to_file(**kwargs)

            # Read back the generated WAV
            with open(temp_path, "rb") as f:
                audio_data = f.read()

            with wave.open(temp_path, "rb") as wav:
                sample_rate = wav.getframerate()
                n_frames = wav.getnframes()
                duration = n_frames / sample_rate

            return SynthesisResult(
                audio_data=audio_data,
                sample_rate=sample_rate,
                duration_seconds=duration,
                text=text,
                voice_id=voice_id or "xtts-default",
            )
        finally:
            Path(temp_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Convenience methods (match pyttsx3 provider interface)
    # ------------------------------------------------------------------

    async def synthesize_to_file(
        self,
        text: str,
        output_path: str,
        voice_id: Optional[str] = None,
        rate: Optional[int] = None,
    ) -> str:
        """Synthesize text and save directly to *output_path*."""
        result = await self.synthesize(text, voice_id, rate)
        with open(output_path, "wb") as f:
            f.write(result.audio_data)
        logger.info("Saved XTTS audio to: %s", output_path)
        return output_path

    async def speak(
        self,
        text: str,
        voice_id: Optional[str] = None,
        rate: Optional[int] = None,
        block: bool = True,
    ):
        """
        Speak text through system speakers.

        Synthesises first, then plays via sounddevice (if available) or
        falls back to writing a temp file.  This is a best-effort
        convenience — the main pipeline uses ``synthesize()`` and streams
        WAV bytes to the frontend.
        """
        result = await self.synthesize(text, voice_id, rate)
        try:
            import sounddevice as sd  # Optional dependency
            audio_np = np.frombuffer(result.audio_data[44:], dtype=np.int16)
            sd.play(audio_np, samplerate=result.sample_rate)
            if block:
                sd.wait()
        except ImportError:
            logger.warning(
                "sounddevice not installed — cannot play audio directly. "
                "Use synthesize() and stream to client instead."
            )

    async def synthesize_interview_question(
        self,
        question: str,
        question_number: Optional[int] = None,
        total_questions: Optional[int] = None,
    ) -> SynthesisResult:
        """
        Synthesize an interview question with contextual preamble.

        Mirrors ``Pyttsx3TTSProvider.synthesize_interview_question``.
        """
        parts: List[str] = []
        if question_number is not None:
            if total_questions:
                parts.append(f"Question {question_number} of {total_questions}.")
            else:
                parts.append(f"Question {question_number}.")
        parts.append(question)
        full_text = " ".join(parts)

        return await self.synthesize(full_text)

    # ------------------------------------------------------------------
    # Voice listing / info (interface compatibility)
    # ------------------------------------------------------------------

    def get_voices(self) -> List[VoiceInfo]:
        """
        Return available voices.

        XTTS v2 uses voice cloning rather than a fixed voice catalogue,
        so we return a single entry describing the current configuration.
        """
        if self._reference_audio:
            voice_name = f"Cloned ({Path(self._reference_audio).stem})"
        else:
            voice_name = f"XTTS ({self._speaker})"

        return [
            VoiceInfo(
                id="xtts-default",
                name=voice_name,
                languages=["en", "es", "fr", "de", "it", "pt", "pl",
                           "tr", "ru", "nl", "cs", "ar", "zh", "ja",
                           "hu", "ko"],
                gender=None,
            )
        ]

    def set_voice(self, voice_id: str):
        """No-op — XTTS doesn't use selectable voice IDs."""
        logger.debug("set_voice(%s) is a no-op for XTTS", voice_id)

    def set_rate(self, rate: int):
        """No-op — XTTS controls its own pacing."""
        logger.debug("set_rate(%d) is a no-op for XTTS", rate)

    def set_volume(self, volume: float):
        """No-op — volume is controlled downstream."""
        logger.debug("set_volume(%.2f) is a no-op for XTTS", volume)

    def get_provider_info(self) -> Dict[str, Any]:
        """Return provider metadata (used by health-check & /tts/info)."""
        return {
            "provider": "coqui-xtts",
            "model": self.model_name,
            "device": self._device,
            "model_loaded": self._model_loaded,
            "reference_audio": self._reference_audio or "(none)",
            "speaker": self._speaker,
            "language": self.language,
            "available_voices": 1,
        }


# ------------------------------------------------------------------
# Singleton helpers (provider-specific, for backward compat)
# ------------------------------------------------------------------

_coqui_provider: Optional[CoquiXTTSProvider] = None


def get_coqui_provider(
    model_name: str = DEFAULT_MODEL,
    device: Optional[str] = None,
    reference_audio: Optional[str] = None,
    language: str = "en",
) -> CoquiXTTSProvider:
    """Get or create the Coqui XTTS singleton."""
    global _coqui_provider
    if _coqui_provider is None:
        _coqui_provider = CoquiXTTSProvider(
            model_name=model_name,
            device=device,
            reference_audio=reference_audio,
            language=language,
        )
    return _coqui_provider


async def get_coqui_provider_async(
    model_name: str = DEFAULT_MODEL,
    device: Optional[str] = None,
    reference_audio: Optional[str] = None,
    language: str = "en",
) -> CoquiXTTSProvider:
    """Async version of ``get_coqui_provider``."""
    return get_coqui_provider(model_name, device, reference_audio, language)
