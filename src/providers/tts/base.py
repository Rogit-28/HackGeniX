"""
TTS Provider Interface and Base Classes.

Defines the abstract interface for Text-to-Speech providers, enabling
plug-and-play swapping between local (pyttsx3, Coqui XTTS) and cloud
(Groq Orpheus, ElevenLabs, etc.) backends.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum


class TTSProvider(str, Enum):
    """Supported TTS provider backends."""
    PYTTSX3 = "pyttsx3"
    COQUI_XTTS = "coqui-xtts"
    GROQ_ORPHEUS = "groq-orpheus"


class VoiceGender(str, Enum):
    """Voice gender options."""
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


@dataclass
class VoiceInfo:
    """Information about an available voice."""
    id: str
    name: str
    languages: List[str]
    gender: Optional[str] = None
    age: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "languages": self.languages,
            "gender": self.gender,
            "age": self.age,
        }


@dataclass
class SynthesisResult:
    """Result of text-to-speech synthesis."""
    audio_data: bytes
    sample_rate: int
    duration_seconds: float
    text: str
    voice_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_rate": self.sample_rate,
            "duration_seconds": self.duration_seconds,
            "text": self.text,
            "voice_id": self.voice_id,
            "audio_size_bytes": len(self.audio_data),
        }


class BaseTTSProvider(ABC):
    """
    Abstract base class for Text-to-Speech providers.

    All TTS backends must implement this interface to be swappable.
    """

    @abstractmethod
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
            voice_id: Voice identifier (provider-specific).
            rate: Speech rate (provider-specific, may be ignored).
            output_format: Output audio format (default "wav").

        Returns:
            SynthesisResult with audio data and metadata.
        """
        ...

    @abstractmethod
    async def synthesize_interview_question(
        self,
        question: str,
        question_number: Optional[int] = None,
        total_questions: Optional[int] = None,
    ) -> SynthesisResult:
        """
        Synthesize an interview question with contextual preamble.

        Args:
            question: The question text.
            question_number: Current question number.
            total_questions: Total number of questions.

        Returns:
            SynthesisResult with audio data.
        """
        ...

    @abstractmethod
    def get_voices(self) -> List[VoiceInfo]:
        """Return available voices for this provider."""
        ...

    @abstractmethod
    def get_provider_info(self) -> Dict[str, Any]:
        """Return provider metadata (used by health-check endpoints)."""
        ...

    # ------------------------------------------------------------------
    # Optional methods with sensible defaults
    # ------------------------------------------------------------------

    async def synthesize_to_file(
        self,
        text: str,
        output_path: str,
        voice_id: Optional[str] = None,
        rate: Optional[int] = None,
    ) -> str:
        """Synthesize text and save to a file. Returns output path."""
        result = await self.synthesize(text, voice_id, rate)
        with open(output_path, "wb") as f:
            f.write(result.audio_data)
        return output_path

    def set_voice(self, voice_id: str):
        """Set the active voice. Override in providers that support it."""
        pass

    def set_rate(self, rate: int):
        """Set speech rate. Override in providers that support it."""
        pass

    def set_volume(self, volume: float):
        """Set volume. Override in providers that support it."""
        pass
