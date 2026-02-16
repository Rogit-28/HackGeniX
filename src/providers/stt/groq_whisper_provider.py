"""
Groq Cloud Whisper STT Provider.

Uses Groq's hosted Whisper API for fast, cloud-based speech-to-text.
Supports whisper-large-v3 and whisper-large-v3-turbo models.

Requires a ``GROQ_API_KEY`` environment variable.
"""
import io
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx
import numpy as np

from src.providers.stt.base import (
    BaseSTTProvider,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger(__name__)

# Groq-hosted Whisper models
GROQ_WHISPER_MODELS = [
    "whisper-large-v3-turbo",  # Faster, cheaper
    "whisper-large-v3",        # More accurate
]

DEFAULT_MODEL = "whisper-large-v3-turbo"

# Groq free tier limit
MAX_FILE_SIZE_MB = 25


class GroqWhisperSTTProvider(BaseSTTProvider):
    """
    Cloud-based STT provider using Groq's Whisper API.

    Audio is sent via multipart POST to ``/audio/transcriptions``.
    No local model is loaded — all inference happens on Groq's servers.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        api_url: str = "https://api.groq.com/openai/v1",
        language: Optional[str] = "en",
        timeout: float = 60.0,
    ):
        self.model_name = model_name
        self.language = language
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key

        if not self.api_key:
            raise ValueError(
                "Groq API key is required. Set the GROQ_API_KEY environment "
                "variable or pass api_key= explicitly."
            )

        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(timeout),
        )

        logger.info(
            "GroqWhisperSTTProvider configured: model=%s, api_url=%s, language=%s",
            self.model_name,
            self.api_url,
            self.language,
        )

    # ------------------------------------------------------------------
    # Audio preparation
    # ------------------------------------------------------------------

    async def _prepare_audio_bytes(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
        content_type: Optional[str] = None,
    ) -> tuple:
        """
        Convert audio_data to (filename, bytes, content_type) for upload.

        Args:
            audio_data: Audio as bytes, numpy array, or file path.
            content_type: Explicit MIME type for raw bytes (e.g.
                ``"audio/webm"``).  When provided, the correct filename
                extension and content-type are used instead of assuming WAV.

        Returns:
            Tuple of (filename, file_bytes, content_type).
        """
        if isinstance(audio_data, (str, Path)):
            path = Path(audio_data)
            suffix = path.suffix.lower() or ".wav"
            ct = "audio/wav" if suffix == ".wav" else f"audio/{suffix.lstrip('.')}"
            return (path.name, path.read_bytes(), ct)

        if isinstance(audio_data, np.ndarray):
            import soundfile as sf

            buf = io.BytesIO()
            sf.write(buf, audio_data, 16000, format="WAV")
            buf.seek(0)
            return ("audio.wav", buf.read(), "audio/wav")

        # Raw bytes — use explicit content_type if provided
        if content_type:
            # Normalize: strip codec params for extension lookup
            base_ct = content_type.split(";")[0].strip().lower()
            ext_map = {
                "audio/webm": ".webm",
                "audio/ogg": ".ogg",
                "audio/mp4": ".mp4",
                "audio/mpeg": ".mp3",
                "audio/wav": ".wav",
                "audio/x-wav": ".wav",
                "audio/flac": ".flac",
            }
            ext = ext_map.get(base_ct, ".webm")
            return (f"audio{ext}", audio_data, base_ct)

        # Fallback — assume WAV
        return ("audio.wav", audio_data, "audio/wav")

    # ------------------------------------------------------------------
    # Core transcription
    # ------------------------------------------------------------------

    async def transcribe(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        word_timestamps: bool = False,
        content_type: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio via Groq Whisper API.

        Args:
            content_type: Explicit MIME type for raw bytes (e.g.
                ``"audio/webm"``).  Passed through to
                :meth:`_prepare_audio_bytes` so Groq receives the correct
                filename extension and content-type header.
        """
        filename, file_bytes, content_type = await self._prepare_audio_bytes(
            audio_data, content_type=content_type,
        )

        # Build multipart form data
        data: Dict[str, Any] = {
            "model": self.model_name,
            "response_format": "verbose_json",
        }

        lang = language or self.language
        if lang:
            data["language"] = lang

        if prompt:
            data["prompt"] = prompt

        if word_timestamps:
            data["timestamp_granularities[]"] = "word"

        files = {"file": (filename, file_bytes, content_type)}

        url = f"{self.api_url}/audio/transcriptions"

        try:
            resp = await self._client.post(url, data=data, files=files)
            resp.raise_for_status()
            result = resp.json()

            # Parse verbose_json response
            text = result.get("text", "")
            detected_lang = result.get("language", lang or "unknown")
            duration = result.get("duration", 0.0)

            segments = []
            for seg in result.get("segments", []):
                segments.append({
                    "id": seg.get("id", 0),
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                    "text": seg.get("text", "").strip(),
                    "confidence": seg.get("avg_logprob", 0.0),
                })

            # Calculate confidence from segment log probs
            confidence = 0.0
            if segments:
                log_probs = [s["confidence"] for s in segments if s["confidence"] < 0]
                if log_probs:
                    avg_log_prob = sum(log_probs) / len(log_probs)
                    confidence = min(1.0, max(0.0, 1.0 + avg_log_prob / 5.0))

            return TranscriptionResult(
                text=text,
                language=detected_lang,
                confidence=confidence,
                duration_seconds=duration,
                segments=segments,
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                "Groq Whisper API error: %s — %s",
                e.response.status_code,
                e.response.text,
            )
            raise
        except Exception as e:
            logger.error("Groq Whisper transcription failed: %s", e)
            raise

    async def transcribe_with_interview_context(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
        context: Optional[str] = None,
        technical_terms: Optional[List[str]] = None,
        content_type: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe with interview-specific prompt context."""
        prompt_parts = ["This is a technical interview conversation."]

        if context:
            prompt_parts.append(f"Context: {context}")

        if technical_terms:
            terms_str = ", ".join(technical_terms[:20])
            prompt_parts.append(f"Technical terms: {terms_str}")

        prompt = " ".join(prompt_parts)

        return await self.transcribe(
            audio_data=audio_data,
            prompt=prompt,
            word_timestamps=True,
            content_type=content_type,
        )

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def get_model_info(self) -> Dict[str, Any]:
        """Return provider metadata."""
        return {
            "model_name": self.model_name,
            "provider": "groq-whisper",
            "api_url": self.api_url,
            "language": self.language,
            "cloud": True,
        }

    async def detect_language(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
    ) -> tuple:
        """Detect language by transcribing without a language hint."""
        result = await self.transcribe(audio_data, language=None)
        # Groq returns detected language in verbose_json
        return (result.language, result.confidence)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
