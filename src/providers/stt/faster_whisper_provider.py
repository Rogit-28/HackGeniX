"""
Faster-Whisper based Speech-to-Text provider.

Uses CTranslate2-optimized Whisper models for faster inference.
Supports GPU acceleration with automatic fallback to CPU.
"""
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional, Union, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


class WhisperModel(str, Enum):
    """Available Whisper model sizes."""
    TINY = "tiny"       # 39M params, fastest
    BASE = "base"       # 74M params
    SMALL = "small"     # 244M params
    MEDIUM = "medium"   # 769M params
    LARGE_V2 = "large-v2"  # 1550M params
    LARGE_V3 = "large-v3"  # Latest large model


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


class FasterWhisperSTTProvider:
    """
    Speech-to-Text provider using faster-whisper (CTranslate2).
    
    Optimized for interview transcription with:
    - Faster inference than original Whisper
    - Lower memory usage
    - GPU acceleration support
    """
    
    def __init__(
        self,
        model_name: str = "base",
        device: Optional[str] = None,
        compute_type: str = "float16",
        language: Optional[str] = "en",
    ):
        """
        Initialize the Faster-Whisper STT provider.
        
        Args:
            model_name: Whisper model size (tiny, base, small, medium, large-v2, large-v3)
            device: Device to use (cuda, cpu, or None for auto-detect)
            compute_type: Compute precision (float16, int8, float32)
            language: Default language for transcription (None for auto-detect)
        """
        self.model_name = model_name
        self.language = language
        self.compute_type = compute_type
        
        # Auto-detect device
        if device is None:
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"
        else:
            self.device = device
        
        # Adjust compute type for CPU
        if self.device == "cpu" and compute_type == "float16":
            self.compute_type = "int8"  # float16 not supported on CPU
        
        logger.info(f"Initializing Faster-Whisper STT: model={model_name}, device={self.device}")
        
        # Load model
        self._model = None
        self._load_model()
    
    def _load_model(self):
        """Load the Whisper model."""
        try:
            from faster_whisper import WhisperModel
            
            logger.info(f"Loading Faster-Whisper model '{self.model_name}'...")
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
            logger.info(f"Faster-Whisper model loaded successfully on {self.device}")
        except Exception as e:
            logger.error(f"Failed to load Faster-Whisper model: {e}")
            # Fallback to CPU if GPU fails
            if self.device == "cuda":
                logger.warning("Falling back to CPU...")
                self.device = "cpu"
                self.compute_type = "int8"
                from faster_whisper import WhisperModel
                self._model = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type="int8",
                )
            else:
                raise
    
    @property
    def model(self):
        """Get the loaded Whisper model."""
        if self._model is None:
            self._load_model()
        return self._model
    
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
            audio_data: Audio as bytes, numpy array, or file path
            language: Language code (e.g., 'en', 'es'). None for auto-detect.
            prompt: Optional prompt to guide transcription (e.g., technical terms)
            word_timestamps: Whether to include word-level timestamps
            
        Returns:
            TranscriptionResult with text and metadata
        """
        # Prepare audio
        audio_path = await self._prepare_audio(audio_data)
        
        # Build transcription options
        options = {
            "language": language or self.language,
            "task": "transcribe",
            "word_timestamps": word_timestamps,
        }
        
        if prompt:
            options["initial_prompt"] = prompt
        
        logger.debug(f"Transcribing audio from {audio_path}")
        
        # Run transcription
        try:
            segments_gen, info = self.model.transcribe(str(audio_path), **options)
            
            # Collect segments
            segments = []
            full_text_parts = []
            
            for i, seg in enumerate(segments_gen):
                segments.append({
                    "id": i,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                    "confidence": seg.avg_logprob,
                })
                full_text_parts.append(seg.text)
            
            full_text = "".join(full_text_parts).strip()
            
            # Calculate confidence
            avg_confidence = 0.0
            if segments:
                log_probs = [s["confidence"] for s in segments if s["confidence"] < 0]
                if log_probs:
                    avg_log_prob = sum(log_probs) / len(log_probs)
                    avg_confidence = min(1.0, max(0.0, 1.0 + avg_log_prob / 5.0))
            
            return TranscriptionResult(
                text=full_text,
                language=info.language,
                confidence=avg_confidence,
                duration_seconds=info.duration,
                segments=segments,
            )
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise
        finally:
            # Clean up temp file if we created one
            if isinstance(audio_data, (bytes, np.ndarray)):
                Path(audio_path).unlink(missing_ok=True)
    
    async def _prepare_audio(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
    ) -> str:
        """
        Prepare audio data for Whisper.
        
        Args:
            audio_data: Audio in various formats
            
        Returns:
            Path to audio file
        """
        if isinstance(audio_data, (str, Path)):
            return str(audio_data)
        
        elif isinstance(audio_data, bytes):
            # Save bytes to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                return f.name
        
        elif isinstance(audio_data, np.ndarray):
            # Save numpy array to temp file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                sf.write(f.name, audio_data, 16000)
                return f.name
        
        else:
            raise ValueError(f"Unsupported audio data type: {type(audio_data)}")
    
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
            audio_data: Audio to transcribe
            context: Interview context (e.g., "technical interview for backend engineer")
            technical_terms: List of technical terms to recognize
            
        Returns:
            TranscriptionResult
        """
        # Build interview-optimized prompt
        prompt_parts = [
            "This is a technical interview conversation.",
        ]
        
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
        )
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        return {
            "model_name": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "language": self.language,
            "provider": "faster-whisper",
        }
    
    async def detect_language(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
    ) -> tuple:
        """
        Detect the language of audio.
        
        Args:
            audio_data: Audio to analyze
            
        Returns:
            Tuple of (language_code, confidence)
        """
        audio_path = await self._prepare_audio(audio_data)
        
        try:
            _, info = self.model.transcribe(
                str(audio_path),
                language=None,  # Auto-detect
            )
            return info.language, info.language_probability
        finally:
            if isinstance(audio_data, (bytes, np.ndarray)):
                Path(audio_path).unlink(missing_ok=True)


# Singleton instance
_faster_whisper_provider: Optional[FasterWhisperSTTProvider] = None


def get_faster_whisper_provider(
    model_name: str = "base",
    device: Optional[str] = None,
    compute_type: str = "float16",
) -> FasterWhisperSTTProvider:
    """
    Get or create the Faster-Whisper STT provider singleton.
    
    Args:
        model_name: Whisper model size
        device: Device to use
        compute_type: Compute precision (float16, int8, float32)
        
    Returns:
        FasterWhisperSTTProvider instance
    """
    global _faster_whisper_provider
    
    if _faster_whisper_provider is None:
        _faster_whisper_provider = FasterWhisperSTTProvider(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
        )
    
    return _faster_whisper_provider


async def get_faster_whisper_provider_async(
    model_name: str = "base",
    device: Optional[str] = None,
    compute_type: str = "float16",
) -> FasterWhisperSTTProvider:
    """Async version of get_faster_whisper_provider."""
    return get_faster_whisper_provider(model_name, device, compute_type)
