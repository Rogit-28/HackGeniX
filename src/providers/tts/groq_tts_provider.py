"""
Groq Cloud TTS Provider (Orpheus).

Uses Groq's Orpheus TTS API for fast, cloud-based text-to-speech.
Model: canopylabs/orpheus-v1-english with 6 English voices.

Supports vocal directions in text such as ``[cheerful]``, ``[whisper]``,
``[excited]``, ``[dramatic]`` for expressive speech (English model only).

Input text is limited to 200 characters per request; longer texts are
automatically chunked and concatenated.

Requires a ``GROQ_API_KEY`` environment variable.
"""
import io
import logging
import wave
from typing import Any, Dict, List, Optional

import httpx

from src.providers.tts.base import (
    BaseTTSProvider,
    SynthesisResult,
    VoiceGender,
    VoiceInfo,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "canopylabs/orpheus-v1-english"
DEFAULT_VOICE = "troy"

# Groq Orpheus input limit per request
MAX_INPUT_CHARS = 200

# Available Orpheus English voices (from Groq docs)
GROQ_TTS_VOICES = [
    VoiceInfo(id="autumn", name="Autumn", languages=["en"], gender=VoiceGender.FEMALE),
    VoiceInfo(id="diana",  name="Diana",  languages=["en"], gender=VoiceGender.FEMALE),
    VoiceInfo(id="hannah", name="Hannah", languages=["en"], gender=VoiceGender.FEMALE),
    VoiceInfo(id="austin", name="Austin", languages=["en"], gender=VoiceGender.MALE),
    VoiceInfo(id="daniel", name="Daniel", languages=["en"], gender=VoiceGender.MALE),
    VoiceInfo(id="troy",   name="Troy",   languages=["en"], gender=VoiceGender.MALE),
]


class GroqTTSProvider(BaseTTSProvider):
    """
    Cloud-based TTS provider using Groq's TTS API.

    Sends a JSON POST to ``/audio/speech`` and receives raw audio bytes.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        voice: str = DEFAULT_VOICE,
        api_key: Optional[str] = None,
        api_url: str = "https://api.groq.com/openai/v1",
        response_format: str = "wav",
        timeout: float = 60.0,
    ):
        self.model = model
        self.voice = voice
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.response_format = response_format

        if not self.api_key:
            raise ValueError(
                "Groq API key is required. Set the GROQ_API_KEY environment "
                "variable or pass api_key= explicitly."
            )

        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )

        logger.info(
            "GroqTTSProvider configured: model=%s, voice=%s, format=%s",
            self.model,
            self.voice,
            self.response_format,
        )

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
        """Synthesize text to speech via Groq TTS API.

        Automatically chunks text that exceeds the 200-char API limit and
        concatenates the resulting WAV segments.
        """
        if not text.strip():
            raise ValueError("Text cannot be empty")

        voice = voice_id or self.voice
        fmt = output_format or self.response_format

        # Chunk if needed (Orpheus limit: 200 chars per request)
        chunks = self._chunk_text(text, MAX_INPUT_CHARS)

        audio_parts: List[bytes] = []
        for chunk in chunks:
            raw = await self._synthesize_chunk(chunk, voice, fmt)
            audio_parts.append(raw)

        # Concatenate audio
        if len(audio_parts) == 1:
            audio_data = audio_parts[0]
        else:
            audio_data = self._concat_wav(audio_parts)

        sample_rate, duration = self._parse_audio_metadata(audio_data, fmt)

        return SynthesisResult(
            audio_data=audio_data,
            sample_rate=sample_rate,
            duration_seconds=duration,
            text=text,
            voice_id=voice,
        )

    async def _synthesize_chunk(
        self, text: str, voice: str, fmt: str
    ) -> bytes:
        """Send a single chunk (<= 200 chars) to the Groq TTS API."""
        payload = {
            "model": self.model,
            "input": text,
            "voice": voice,
            "response_format": fmt,
        }

        url = f"{self.api_url}/audio/speech"

        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPStatusError as e:
            logger.error(
                "Groq TTS API error: %s — %s",
                e.response.status_code,
                e.response.text,
            )
            raise
        except Exception as e:
            logger.error("Groq TTS synthesis failed: %s", e)
            raise

    async def synthesize_interview_question(
        self,
        question: str,
        question_number: Optional[int] = None,
        total_questions: Optional[int] = None,
    ) -> SynthesisResult:
        """Synthesize an interview question with contextual preamble."""
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
    # Audio metadata helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_audio_metadata(audio_data: bytes, fmt: str) -> tuple:
        """
        Extract sample_rate and duration from audio bytes.

        Returns:
            (sample_rate, duration_seconds)
        """
        if fmt == "wav" and len(audio_data) > 44:
            try:
                buf = io.BytesIO(audio_data)
                with wave.open(buf, "rb") as wf:
                    sr = wf.getframerate()
                    channels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    frames = wf.getnframes()

                    # Groq streams WAVs with RIFF size 0xFFFFFFFF, which
                    # makes nframes unreliable (returns INT32_MAX).  In
                    # that case compute from actual byte length instead.
                    bytes_per_frame = channels * sampwidth
                    max_possible = (
                        (len(audio_data) - 44) // bytes_per_frame
                        if bytes_per_frame
                        else 0
                    )
                    if frames > max_possible:
                        frames = max_possible

                    duration = frames / sr if sr else 0.0
                    return sr, duration
            except Exception:
                pass

        # Fallback: assume 24 kHz mono 16-bit
        sr = 24000
        duration = max(0.0, (len(audio_data) - 44)) / (sr * 2) if fmt == "wav" else 0.0
        return sr, duration

    @staticmethod
    def _chunk_text(text: str, max_chars: int) -> List[str]:
        """Split text into chunks of at most *max_chars*, breaking on
        sentence boundaries (. ! ?) or spaces when possible."""
        if len(text) <= max_chars:
            return [text]

        chunks: List[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= max_chars:
                chunks.append(remaining)
                break

            # Try to break at sentence boundary
            candidate = remaining[:max_chars]
            split_at = -1
            for delim in [". ", "! ", "? "]:
                idx = candidate.rfind(delim)
                if idx > split_at:
                    split_at = idx + len(delim) - 1  # include the punctuation

            if split_at <= 0:
                # Fall back to last space
                split_at = candidate.rfind(" ")

            if split_at <= 0:
                # No good break point — hard cut
                split_at = max_chars

            chunks.append(remaining[: split_at + 1].strip())
            remaining = remaining[split_at + 1 :].strip()

        return [c for c in chunks if c]

    @staticmethod
    def _concat_wav(parts: List[bytes]) -> bytes:
        """Concatenate multiple WAV byte strings into one WAV file."""
        if not parts:
            return b""
        if len(parts) == 1:
            return parts[0]

        # Groq returns streaming WAVs with RIFF size 0xFFFFFFFF, which
        # makes getnframes() return INT32_MAX.  We read all raw frame
        # data with readframes(-1) and rebuild the header from scratch
        # so the output WAV has correct sizes.
        all_frames: List[bytes] = []
        nchannels = sampwidth = framerate = 0

        for i, p in enumerate(parts):
            buf = io.BytesIO(p)
            with wave.open(buf, "rb") as wf:
                if i == 0:
                    nchannels = wf.getnchannels()
                    sampwidth = wf.getsampwidth()
                    framerate = wf.getframerate()
                all_frames.append(wf.readframes(-1))

        combined = b"".join(all_frames)
        total_frames = len(combined) // (nchannels * sampwidth) if (nchannels * sampwidth) else 0

        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(nchannels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(framerate)
            wf.setnframes(total_frames)
            wf.writeframesraw(combined)
        return out.getvalue()

    # ------------------------------------------------------------------
    # Voice listing / info
    # ------------------------------------------------------------------

    def get_voices(self) -> List[VoiceInfo]:
        """Return available Groq TTS voices."""
        return list(GROQ_TTS_VOICES)

    def set_voice(self, voice_id: str):
        """Set the active voice."""
        self.voice = voice_id

    def get_provider_info(self) -> Dict[str, Any]:
        """Return provider metadata."""
        return {
            "provider": "groq-tts",
            "model": self.model,
            "voice": self.voice,
            "api_url": self.api_url,
            "response_format": self.response_format,
            "available_voices": len(GROQ_TTS_VOICES),
            "cloud": True,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
