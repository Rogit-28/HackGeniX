"""
STT Provider Interface and Base Classes.

Defines the abstract interface for Speech-to-Text providers, enabling
plug-and-play swapping between local (Whisper, faster-whisper) and cloud
(Groq Whisper, Deepgram, etc.) backends.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Union
from enum import Enum
from pathlib import Path

import numpy as np


class STTProvider(str, Enum):
    """Supported STT provider backends."""
    WHISPER = "whisper"
    FASTER_WHISPER = "faster-whisper"
    GROQ_WHISPER = "groq-whisper"


class WhisperModel(str, Enum):
    """Available Whisper model sizes."""
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE_V2 = "large-v2"
    LARGE_V3 = "large-v3"
    LARGE_V3_TURBO = "large-v3-turbo"


@dataclass
class TranscriptionSegment:
    """A segment of transcribed audio with timing info."""
    id: int
    start: float
    end: float
    text: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "confidence": self.confidence,
        }


@dataclass
class TranscriptionResult:
    """Result of speech-to-text transcription."""
    text: str
    language: str
    confidence: float
    duration_seconds: float
    segments: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "confidence": self.confidence,
            "duration_seconds": self.duration_seconds,
            "segments": self.segments,
        }


class BaseSTTProvider(ABC):
    """
    Abstract base class for Speech-to-Text providers.

    All STT backends must implement this interface to be swappable.
    """

    @abstractmethod
    async def transcribe(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        word_timestamps: bool = False,
    ) -> TranscriptionResult:
        """
        Transcribe audio to text.

        Args:
            audio_data: Audio as bytes, numpy array, or file path.
            language: Language code (e.g., 'en'). None for auto-detect.
            prompt: Optional prompt to guide transcription.
            word_timestamps: Whether to include word-level timestamps.

        Returns:
            TranscriptionResult with text and metadata.
        """
        ...

    @abstractmethod
    async def transcribe_with_interview_context(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
        context: Optional[str] = None,
        technical_terms: Optional[List[str]] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio with interview-specific context.

        Uses a prompt to improve recognition of technical terminology.

        Args:
            audio_data: Audio to transcribe.
            context: Interview context description.
            technical_terms: List of technical terms to recognise.

        Returns:
            TranscriptionResult.
        """
        ...

    @abstractmethod
    def get_model_info(self) -> Dict[str, Any]:
        """Return metadata about the provider and loaded model."""
        ...

    async def detect_language(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
    ) -> tuple:
        """
        Detect the language of audio.

        Returns:
            Tuple of (language_code, confidence).

        Default implementation raises NotImplementedError — override in
        providers that support language detection.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support language detection"
        )
