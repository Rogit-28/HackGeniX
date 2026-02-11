"""
Whisper-based Speech-to-Text provider.

Uses OpenAI's Whisper model for accurate speech recognition.
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
import torch
import whisper
import soundfile as sf

from src.providers.stt.base import (
    BaseSTTProvider,
    TranscriptionResult,
    TranscriptionSegment,
    WhisperModel,
)

logger = logging.getLogger(__name__)


class WhisperSTTProvider(BaseSTTProvider):
    """
    Speech-to-Text provider using OpenAI's Whisper.
    
    Optimized for interview transcription with focus on:
    - Accurate technical term recognition
    - Speaker clarity
    - Real-time processing capability
    """
    
    def __init__(
        self,
        model_name: str = "base",
        device: Optional[str] = None,
        compute_type: str = "float16",
        language: Optional[str] = "en",
    ):
        """
        Initialize the Whisper STT provider.
        
        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
            device: Device to use (cuda, cpu, or None for auto-detect)
            compute_type: Compute precision (float16, float32)
            language: Default language for transcription (None for auto-detect)
        """
        self.model_name = model_name
        self.language = language
        self.compute_type = compute_type
        
        # Auto-detect device
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
        
        logger.info(f"Initializing Whisper STT: model={model_name}, device={self.device}")
        
        # Load model
        self._model = None
        self._load_model()
    
    def _load_model(self):
        """Load the Whisper model."""
        try:
            logger.info(f"Loading Whisper model '{self.model_name}'...")
            self._model = whisper.load_model(self.model_name, device=self.device)
            logger.info(f"Whisper model loaded successfully on {self.device}")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            # Fallback to CPU if GPU fails
            if self.device == "cuda":
                logger.warning("Falling back to CPU...")
                self.device = "cpu"
                self._model = whisper.load_model(self.model_name, device="cpu")
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
        audio_array = await self._prepare_audio(audio_data)
        
        # Build transcription options
        options = {
            "language": language or self.language,
            "task": "transcribe",
            "fp16": self.device == "cuda" and self.compute_type == "float16",
        }
        
        if prompt:
            options["initial_prompt"] = prompt
        
        if word_timestamps:
            options["word_timestamps"] = True
        
        logger.debug(f"Transcribing audio ({len(audio_array) / 16000:.1f}s)")
        
        # Run transcription
        try:
            result = self.model.transcribe(audio_array, **options)
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise
        
        # Parse segments
        segments = []
        for seg in result.get("segments", []):
            segments.append(TranscriptionSegment(
                id=seg["id"],
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
                confidence=seg.get("avg_logprob", 0.0),
            ))
        
        # Calculate overall confidence (average of segment confidences)
        avg_confidence = 0.0
        if segments:
            # Convert log prob to probability (approximate)
            log_probs = [s.confidence for s in segments if s.confidence < 0]
            if log_probs:
                avg_log_prob = sum(log_probs) / len(log_probs)
                avg_confidence = min(1.0, max(0.0, 1.0 + avg_log_prob / 5.0))
        
        # Calculate duration
        duration = len(audio_array) / 16000  # Whisper uses 16kHz
        
        return TranscriptionResult(
            text=result["text"].strip(),
            language=result.get("language", self.language or "en"),
            confidence=avg_confidence,
            duration_seconds=duration,
            segments=[s.to_dict() for s in segments],
        )
    
    async def _prepare_audio(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
    ) -> np.ndarray:
        """
        Prepare audio data for Whisper.
        
        Whisper expects:
        - Sample rate: 16kHz
        - Channels: Mono
        - Format: float32 numpy array
        
        Args:
            audio_data: Audio in various formats
            
        Returns:
            Processed audio as numpy array
        """
        if isinstance(audio_data, np.ndarray):
            audio_array = audio_data
        elif isinstance(audio_data, (str, Path)):
            # Load from file
            audio_array, sample_rate = sf.read(str(audio_data))
            if sample_rate != 16000:
                audio_array = self._resample(audio_array, sample_rate, 16000)
        elif isinstance(audio_data, bytes):
            # Load from bytes
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                temp_path = f.name
            try:
                audio_array, sample_rate = sf.read(temp_path)
                if sample_rate != 16000:
                    audio_array = self._resample(audio_array, sample_rate, 16000)
            finally:
                Path(temp_path).unlink(missing_ok=True)
        else:
            raise ValueError(f"Unsupported audio data type: {type(audio_data)}")
        
        # Convert to mono if stereo
        if len(audio_array.shape) > 1:
            audio_array = audio_array.mean(axis=1)
        
        # Ensure float32
        audio_array = audio_array.astype(np.float32)
        
        return audio_array
    
    def _resample(
        self,
        audio: np.ndarray,
        orig_sr: int,
        target_sr: int,
    ) -> np.ndarray:
        """
        Resample audio to target sample rate.
        
        Simple linear interpolation resampling.
        For production, consider using librosa or scipy for better quality.
        """
        if orig_sr == target_sr:
            return audio
        
        duration = len(audio) / orig_sr
        target_length = int(duration * target_sr)
        
        # Use numpy interpolation
        indices = np.linspace(0, len(audio) - 1, target_length)
        resampled = np.interp(indices, np.arange(len(audio)), audio)
        
        return resampled.astype(np.float32)
    
    async def transcribe_with_interview_context(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
        context: Optional[str] = None,
        technical_terms: Optional[list] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio with interview-specific context.
        
        Uses a prompt to improve recognition of:
        - Technical terminology
        - Company/role-specific terms
        - Common interview phrases
        
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
            terms_str = ", ".join(technical_terms[:20])  # Limit to 20 terms
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
            "is_multilingual": self.model_name not in ["tiny.en", "base.en", "small.en", "medium.en"],
        }
    
    async def detect_language(
        self,
        audio_data: Union[bytes, np.ndarray, str, Path],
    ) -> tuple[str, float]:
        """
        Detect the language of audio.
        
        Args:
            audio_data: Audio to analyze
            
        Returns:
            Tuple of (language_code, confidence)
        """
        audio_array = await self._prepare_audio(audio_data)
        
        # Use only first 30 seconds for language detection
        audio_sample = audio_array[:16000 * 30]
        
        # Pad or trim to 30 seconds
        audio_sample = whisper.pad_or_trim(audio_sample)
        
        # Make log-mel spectrogram
        mel = whisper.log_mel_spectrogram(audio_sample).to(self.device)
        
        # Detect language
        _, probs = self.model.detect_language(mel)
        
        # Get top language
        top_lang = max(probs, key=probs.get)
        confidence = probs[top_lang]
        
        return top_lang, confidence


# Singleton instance
_whisper_provider: Optional[WhisperSTTProvider] = None


def get_whisper_provider(
    model_name: str = "base",
    device: Optional[str] = None,
) -> WhisperSTTProvider:
    """
    Get or create the Whisper STT provider singleton.
    
    Args:
        model_name: Whisper model size
        device: Device to use
        
    Returns:
        WhisperSTTProvider instance
    """
    global _whisper_provider
    
    if _whisper_provider is None:
        _whisper_provider = WhisperSTTProvider(
            model_name=model_name,
            device=device,
        )
    
    return _whisper_provider


async def get_whisper_provider_async(
    model_name: str = "base",
    device: Optional[str] = None,
) -> WhisperSTTProvider:
    """Async version of get_whisper_provider."""
    return get_whisper_provider(model_name, device)
