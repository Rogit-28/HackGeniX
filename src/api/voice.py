"""
Voice API endpoints for STT and TTS.

Provides REST API for:
- Speech-to-text transcription (Whisper)
- Text-to-speech synthesis (Coqui XTTS v2 / pyttsx3 fallback)
- Voice configuration
"""
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import io

from src.core.auth import get_current_user, require_permission, require_role
from src.core.permissions import Permissions
from src.models.auth import AuthenticatedUser, UserRole
from src.providers.stt import (
    get_stt_provider_async,
    TranscriptionResult,
    WhisperModel,
)
from src.providers.tts import (
    get_tts_provider_async,
    VoiceInfo,
    SynthesisResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


# ============== Request/Response Models ==============

class TranscribeRequest(BaseModel):
    """Request for transcription with context."""
    language: Optional[str] = Field(None, description="Language code (e.g., 'en')")
    context: Optional[str] = Field(None, description="Interview context for better accuracy")
    technical_terms: Optional[List[str]] = Field(None, description="Technical terms to recognize")


class TranscribeResponse(BaseModel):
    """Response from transcription."""
    text: str
    language: str
    confidence: float
    duration_seconds: float
    segments: Optional[List[dict]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SynthesizeRequest(BaseModel):
    """Request for text-to-speech synthesis."""
    text: str = Field(..., min_length=1, max_length=5000, description="Text to synthesize")
    voice_id: Optional[str] = Field(None, description="Voice ID to use")
    rate: Optional[int] = Field(None, ge=50, le=300, description="Speech rate (words per minute)")


class SynthesizeResponse(BaseModel):
    """Response metadata for synthesis (audio returned separately)."""
    sample_rate: int
    duration_seconds: float
    text_length: int
    voice_id: str


class VoiceListResponse(BaseModel):
    """Response with available voices."""
    voices: List[dict]
    default_voice_id: Optional[str]


class STTInfoResponse(BaseModel):
    """Information about STT provider."""
    model_name: str
    device: str
    language: Optional[str]
    is_multilingual: bool


class TTSInfoResponse(BaseModel):
    """Information about TTS provider."""
    provider: str
    voice_id: Optional[str]
    rate: int
    volume: float
    available_voices: int


class LanguageDetectResponse(BaseModel):
    """Response from language detection."""
    language: str
    confidence: float


# ============== STT Endpoints ==============

@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    audio: UploadFile = File(..., description="Audio file to transcribe"),
    language: Optional[str] = Query(None, description="Language code"),
    context: Optional[str] = Query(None, description="Interview context"),
    user: AuthenticatedUser = Depends(require_permission(Permissions.USE_VOICE)),
):
    """
    Transcribe audio file to text using Whisper.
    
    Supports common audio formats: WAV, MP3, M4A, FLAC, OGG.
    For best results with interview audio, provide context.
    """
    try:
        # Read audio data
        audio_bytes = await audio.read()
        
        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty audio file")
        
        # Get STT provider
        stt = await get_stt_provider_async()
        
        # Transcribe
        if context:
            result = await stt.transcribe_with_interview_context(
                audio_data=audio_bytes,
                context=context,
            )
        else:
            result = await stt.transcribe(
                audio_data=audio_bytes,
                language=language,
            )
        
        logger.info(f"Transcribed {result.duration_seconds:.1f}s audio: {len(result.text)} chars")
        
        return TranscribeResponse(
            text=result.text,
            language=result.language,
            confidence=result.confidence,
            duration_seconds=result.duration_seconds,
            segments=result.segments,
        )
        
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@router.post("/transcribe/interview", response_model=TranscribeResponse)
async def transcribe_interview_audio(
    audio: UploadFile = File(..., description="Interview audio to transcribe"),
    context: Optional[str] = Query(None, description="Role/position context"),
    technical_terms: Optional[str] = Query(None, description="Comma-separated technical terms"),
    user: AuthenticatedUser = Depends(require_permission(Permissions.USE_VOICE)),
):
    """
    Transcribe interview audio with optimized settings.
    
    Uses interview-specific prompts to improve recognition of:
    - Technical terminology
    - Industry jargon
    - Company-specific terms
    """
    try:
        audio_bytes = await audio.read()
        
        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty audio file")
        
        # Parse technical terms
        terms = None
        if technical_terms:
            terms = [t.strip() for t in technical_terms.split(",") if t.strip()]
        
        # Get STT provider
        stt = await get_stt_provider_async()
        
        result = await stt.transcribe_with_interview_context(
            audio_data=audio_bytes,
            context=context,
            technical_terms=terms,
        )
        
        return TranscribeResponse(
            text=result.text,
            language=result.language,
            confidence=result.confidence,
            duration_seconds=result.duration_seconds,
            segments=result.segments,
        )
        
    except Exception as e:
        logger.error(f"Interview transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@router.post("/detect-language", response_model=LanguageDetectResponse)
async def detect_language(
    audio: UploadFile = File(..., description="Audio file for language detection"),
    user: AuthenticatedUser = Depends(require_permission(Permissions.USE_VOICE)),
):
    """
    Detect the language of audio content.
    
    Uses first 30 seconds of audio for detection.
    """
    try:
        audio_bytes = await audio.read()
        
        stt = await get_stt_provider_async()
        language, confidence = await stt.detect_language(audio_bytes)
        
        return LanguageDetectResponse(
            language=language,
            confidence=confidence,
        )
        
    except Exception as e:
        logger.error(f"Language detection failed: {e}")
        raise HTTPException(status_code=500, detail=f"Detection failed: {str(e)}")


@router.get("/stt/info", response_model=STTInfoResponse)
async def get_stt_info(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get information about the STT provider."""
    try:
        stt = await get_stt_provider_async()
        info = stt.get_model_info()
        
        return STTInfoResponse(
            model_name=info["model_name"],
            device=info["device"],
            language=info.get("language"),
            is_multilingual=info.get("is_multilingual", True),
        )
        
    except Exception as e:
        logger.error(f"Failed to get STT info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stt/models")
async def list_stt_models(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List available Whisper model sizes."""
    return {
        "models": [
            {"name": "tiny", "parameters": "39M", "vram": "~1GB", "speed": "fastest"},
            {"name": "base", "parameters": "74M", "vram": "~1GB", "speed": "fast"},
            {"name": "small", "parameters": "244M", "vram": "~2GB", "speed": "moderate"},
            {"name": "medium", "parameters": "769M", "vram": "~5GB", "speed": "slow"},
            {"name": "large", "parameters": "1550M", "vram": "~10GB", "speed": "slowest"},
        ],
        "recommended": "base",
    }


# ============== TTS Endpoints ==============

@router.post("/synthesize")
async def synthesize_speech(
    request: SynthesizeRequest,
    user: AuthenticatedUser = Depends(require_permission(Permissions.USE_VOICE)),
):
    """
    Synthesize text to speech.
    
    Returns WAV audio file as streaming response.
    """
    try:
        tts = await get_tts_provider_async()
        
        result = await tts.synthesize(
            text=request.text,
            voice_id=request.voice_id,
            rate=request.rate,
        )
        
        logger.info(f"Synthesized {result.duration_seconds:.1f}s audio for {len(request.text)} chars")
        
        # Return audio as streaming response
        return StreamingResponse(
            io.BytesIO(result.audio_data),
            media_type="audio/wav",
            headers={
                "Content-Disposition": f"attachment; filename=speech.wav",
                "X-Duration-Seconds": str(result.duration_seconds),
                "X-Sample-Rate": str(result.sample_rate),
            },
        )
        
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {str(e)}")


@router.post("/synthesize/question")
async def synthesize_interview_question(
    text: str = Query(..., description="Question text"),
    question_number: Optional[int] = Query(None, description="Question number"),
    total_questions: Optional[int] = Query(None, description="Total questions"),
    user: AuthenticatedUser = Depends(require_permission(Permissions.USE_VOICE)),
):
    """
    Synthesize an interview question with appropriate pacing.
    
    Optimized for clear question delivery with slower speech rate.
    """
    try:
        tts = await get_tts_provider_async()
        
        result = await tts.synthesize_interview_question(
            question=text,
            question_number=question_number,
            total_questions=total_questions,
        )
        
        return StreamingResponse(
            io.BytesIO(result.audio_data),
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=question.wav",
                "X-Duration-Seconds": str(result.duration_seconds),
            },
        )
        
    except Exception as e:
        logger.error(f"Question synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tts/voices", response_model=VoiceListResponse)
async def list_voices(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """List available TTS voices."""
    try:
        tts = await get_tts_provider_async()
        voices = tts.get_voices()
        
        return VoiceListResponse(
            voices=[v.to_dict() for v in voices],
            default_voice_id=tts.voice_id,
        )
        
    except Exception as e:
        logger.error(f"Failed to list voices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tts/info", response_model=TTSInfoResponse)
async def get_tts_info(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get information about the TTS provider."""
    try:
        tts = await get_tts_provider_async()
        info = tts.get_provider_info()
        
        return TTSInfoResponse(**info)
        
    except Exception as e:
        logger.error(f"Failed to get TTS info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tts/configure")
async def configure_tts(
    voice_id: Optional[str] = Query(None, description="Voice ID to use"),
    rate: Optional[int] = Query(None, ge=50, le=300, description="Speech rate"),
    volume: Optional[float] = Query(None, ge=0.0, le=1.0, description="Volume level"),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN, UserRole.HIRING_MANAGER)),
):
    """Configure TTS settings."""
    try:
        tts = await get_tts_provider_async()
        
        if voice_id:
            tts.set_voice(voice_id)
        if rate:
            tts.set_rate(rate)
        if volume is not None:
            tts.set_volume(volume)
        
        return {
            "status": "configured",
            "settings": tts.get_provider_info(),
        }
        
    except Exception as e:
        logger.error(f"Failed to configure TTS: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== Health Check ==============

@router.get("/health")
async def voice_health_check():
    """Check health of voice services."""
    status = {
        "stt": {"status": "unknown"},
        "tts": {"status": "unknown"},
    }
    
    # Check STT
    try:
        stt = await get_stt_provider_async()
        info = stt.get_model_info()
        status["stt"] = {
            "status": "healthy",
            "model": info["model_name"],
            "device": info["device"],
        }
    except Exception as e:
        status["stt"] = {"status": "unhealthy", "error": str(e)}
    
    # Check TTS
    try:
        tts = await get_tts_provider_async()
        info = tts.get_provider_info()
        status["tts"] = {
            "status": "healthy",
            "provider": info["provider"],
            "voices_available": info["available_voices"],
        }
    except Exception as e:
        status["tts"] = {"status": "unhealthy", "error": str(e)}
    
    # Overall status
    all_healthy = all(s.get("status") == "healthy" for s in status.values())
    
    return {
        "overall": "healthy" if all_healthy else "degraded",
        "services": status,
    }
