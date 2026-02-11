"""
Text-to-Speech provider using pyttsx3.

Uses system TTS engines for cross-platform speech synthesis.
Supports Windows (SAPI5), macOS (NSSpeechSynthesizer), and Linux (espeak).
"""
import io
import logging
import tempfile
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import wave

import pyttsx3
import numpy as np

from src.providers.tts.base import (
    BaseTTSProvider,
    VoiceGender,
    VoiceInfo,
    SynthesisResult,
)

logger = logging.getLogger(__name__)


class Pyttsx3TTSProvider(BaseTTSProvider):
    """
    Text-to-Speech provider using pyttsx3.
    
    Features:
    - Cross-platform support (Windows, macOS, Linux)
    - Multiple voice options
    - Configurable speech rate and volume
    - Async-compatible with thread pool
    """
    
    def __init__(
        self,
        voice_id: Optional[str] = None,
        rate: int = 150,  # Words per minute
        volume: float = 1.0,  # 0.0 to 1.0
    ):
        """
        Initialize the TTS provider.
        
        Args:
            voice_id: Specific voice ID to use (None for default)
            rate: Speech rate in words per minute (default: 150)
            volume: Volume level from 0.0 to 1.0
        """
        self.voice_id = voice_id
        self.rate = rate
        self.volume = volume
        
        # Initialize engine (will be recreated for each synthesis to avoid threading issues)
        self._engine = None
        self._voices: List[VoiceInfo] = []
        
        # Load available voices
        self._load_voices()
        
        logger.info(f"Initialized TTS provider: rate={rate}, volume={volume}")
    
    def _create_engine(self) -> pyttsx3.Engine:
        """Create a new pyttsx3 engine instance."""
        engine = pyttsx3.init()
        engine.setProperty('rate', self.rate)
        engine.setProperty('volume', self.volume)
        
        if self.voice_id:
            engine.setProperty('voice', self.voice_id)
        
        return engine
    
    def _load_voices(self):
        """Load available voices from the system."""
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            
            self._voices = []
            for voice in voices:
                # Parse voice info
                gender = None
                if hasattr(voice, 'gender'):
                    gender = voice.gender
                elif 'female' in voice.name.lower():
                    gender = 'female'
                elif 'male' in voice.name.lower():
                    gender = 'male'
                
                languages = []
                if hasattr(voice, 'languages') and voice.languages:
                    languages = list(voice.languages)
                
                self._voices.append(VoiceInfo(
                    id=voice.id,
                    name=voice.name,
                    languages=languages,
                    gender=gender,
                ))
            
            engine.stop()
            logger.info(f"Loaded {len(self._voices)} available voices")
            
        except Exception as e:
            logger.warning(f"Failed to load voices: {e}")
    
    def get_voices(self) -> List[VoiceInfo]:
        """Get list of available voices."""
        return self._voices
    
    def set_voice(self, voice_id: str):
        """Set the voice to use for synthesis."""
        self.voice_id = voice_id
        logger.info(f"Set voice to: {voice_id}")
    
    def set_rate(self, rate: int):
        """Set speech rate in words per minute."""
        self.rate = rate
        logger.info(f"Set rate to: {rate}")
    
    def set_volume(self, volume: float):
        """Set volume (0.0 to 1.0)."""
        self.volume = max(0.0, min(1.0, volume))
        logger.info(f"Set volume to: {self.volume}")
    
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
            text: Text to convert to speech
            voice_id: Voice ID to use (overrides default)
            rate: Speech rate (overrides default)
            output_format: Output format (currently only 'wav' supported)
            
        Returns:
            SynthesisResult with audio data
        """
        if not text.strip():
            raise ValueError("Text cannot be empty")
        
        # Run synthesis in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._synthesize_sync,
            text,
            voice_id,
            rate,
        )
        
        return result
    
    def _synthesize_sync(
        self,
        text: str,
        voice_id: Optional[str] = None,
        rate: Optional[int] = None,
    ) -> SynthesisResult:
        """Synchronous synthesis implementation."""
        # Create temp file for audio output
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
        
        try:
            # Create fresh engine instance
            engine = pyttsx3.init()
            
            # Set properties
            engine.setProperty('rate', rate or self.rate)
            engine.setProperty('volume', self.volume)
            
            if voice_id or self.voice_id:
                engine.setProperty('voice', voice_id or self.voice_id)
            
            # Save to file
            engine.save_to_file(text, temp_path)
            engine.runAndWait()
            engine.stop()
            
            # Read the audio file
            with open(temp_path, 'rb') as f:
                audio_data = f.read()
            
            # Get audio info
            with wave.open(temp_path, 'rb') as wav:
                sample_rate = wav.getframerate()
                n_frames = wav.getnframes()
                duration = n_frames / sample_rate
            
            return SynthesisResult(
                audio_data=audio_data,
                sample_rate=sample_rate,
                duration_seconds=duration,
                text=text,
                voice_id=voice_id or self.voice_id or "default",
            )
            
        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)
    
    async def synthesize_to_file(
        self,
        text: str,
        output_path: str,
        voice_id: Optional[str] = None,
        rate: Optional[int] = None,
    ) -> str:
        """
        Synthesize text directly to a file.
        
        Args:
            text: Text to convert
            output_path: Path to save audio file
            voice_id: Voice to use
            rate: Speech rate
            
        Returns:
            Path to saved file
        """
        result = await self.synthesize(text, voice_id, rate)
        
        with open(output_path, 'wb') as f:
            f.write(result.audio_data)
        
        logger.info(f"Saved audio to: {output_path}")
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
        
        Args:
            text: Text to speak
            voice_id: Voice to use
            rate: Speech rate
            block: Whether to wait for speech to complete
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._speak_sync,
            text,
            voice_id,
            rate,
            block,
        )
    
    def _speak_sync(
        self,
        text: str,
        voice_id: Optional[str] = None,
        rate: Optional[int] = None,
        block: bool = True,
    ):
        """Synchronous speak implementation."""
        engine = pyttsx3.init()
        
        engine.setProperty('rate', rate or self.rate)
        engine.setProperty('volume', self.volume)
        
        if voice_id or self.voice_id:
            engine.setProperty('voice', voice_id or self.voice_id)
        
        engine.say(text)
        
        if block:
            engine.runAndWait()
        else:
            engine.startLoop(False)
            engine.iterate()
            engine.endLoop()
        
        engine.stop()
    
    async def synthesize_interview_question(
        self,
        question: str,
        question_number: Optional[int] = None,
        total_questions: Optional[int] = None,
    ) -> SynthesisResult:
        """
        Synthesize an interview question with appropriate pacing.
        
        Args:
            question: The question text
            question_number: Current question number
            total_questions: Total number of questions
            
        Returns:
            SynthesisResult with audio
        """
        # Build the full text with context
        parts = []
        
        if question_number is not None:
            if total_questions:
                parts.append(f"Question {question_number} of {total_questions}.")
            else:
                parts.append(f"Question {question_number}.")
        
        parts.append(question)
        
        full_text = " ".join(parts)
        
        # Use slightly slower rate for clarity
        interview_rate = max(120, self.rate - 20)
        
        return await self.synthesize(full_text, rate=interview_rate)
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about the TTS provider."""
        return {
            "provider": "pyttsx3",
            "voice_id": self.voice_id,
            "rate": self.rate,
            "volume": self.volume,
            "available_voices": len(self._voices),
        }


# Singleton instance
_tts_provider: Optional[Pyttsx3TTSProvider] = None


def get_tts_provider(
    voice_id: Optional[str] = None,
    rate: int = 150,
    volume: float = 1.0,
) -> Pyttsx3TTSProvider:
    """
    Get or create the TTS provider singleton.
    
    Args:
        voice_id: Voice ID to use
        rate: Speech rate
        volume: Volume level
        
    Returns:
        Pyttsx3TTSProvider instance
    """
    global _tts_provider
    
    if _tts_provider is None:
        _tts_provider = Pyttsx3TTSProvider(
            voice_id=voice_id,
            rate=rate,
            volume=volume,
        )
    
    return _tts_provider


async def get_tts_provider_async(
    voice_id: Optional[str] = None,
    rate: int = 150,
    volume: float = 1.0,
) -> Pyttsx3TTSProvider:
    """Async version of get_tts_provider."""
    return get_tts_provider(voice_id, rate, volume)
