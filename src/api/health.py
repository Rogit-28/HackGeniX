"""
Health check endpoints.
"""
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, status
from pydantic import BaseModel

from src.core.database import mongodb_client
from src.core.storage import storage_client
from src.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    mongodb: bool
    storage: bool
    version: str = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Check the health of all system components.
    """
    mongodb_ok = await mongodb_client.health_check()
    storage_ok = await storage_client.health_check()
    
    overall_status = "healthy" if (mongodb_ok and storage_ok) else "degraded"
    
    return HealthResponse(
        status=overall_status,
        mongodb=mongodb_ok,
        storage=storage_ok,
    )


@router.get("/health/detailed")
async def health_detailed():
    """
    Detailed health check of all system components.
    Returns per-service status, metadata, and collection counts.
    """
    components = {}

    # --- MongoDB ---
    try:
        await mongodb_client.client.admin.command("ping")
        # Gather collection stats
        db = mongodb_client.db
        resume_count = await db["resumes"].count_documents({})
        jd_count = await db["job_descriptions"].count_documents({})
        session_count = await db["interview_sessions"].count_documents({})
        components["mongodb"] = {
            "status": "healthy",
            "database": settings.mongodb_db_name,
            "collections": {
                "resumes": resume_count,
                "job_descriptions": jd_count,
                "interview_sessions": session_count,
            },
        }
    except Exception as e:
        components["mongodb"] = {"status": "unhealthy", "error": str(e)}

    # --- Storage ---
    try:
        storage_ok = await storage_client.health_check()
        components["storage"] = {
            "status": "healthy" if storage_ok else "unhealthy",
            "backend": storage_client.storage_type,
        }
    except Exception as e:
        components["storage"] = {"status": "unhealthy", "error": str(e)}

    # --- Ollama LLM ---
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_api_url}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                components["ollama"] = {
                    "status": "healthy",
                    "url": settings.ollama_api_url,
                    "models_loaded": models,
                }
            else:
                components["ollama"] = {
                    "status": "unhealthy",
                    "error": f"HTTP {resp.status_code}",
                }
    except Exception as e:
        components["ollama"] = {"status": "unhealthy", "error": str(e)}

    # --- STT (faster-whisper) ---
    try:
        from src.providers.stt import get_stt_provider_async
        stt = await get_stt_provider_async()
        info = stt.get_model_info()
        components["stt"] = {
            "status": "healthy",
            "model": info.get("model_name", "unknown"),
            "device": info.get("device", "unknown"),
        }
    except Exception as e:
        components["stt"] = {"status": "unhealthy", "error": str(e)}

    # --- TTS ---
    try:
        from src.providers.tts import get_tts_provider_async
        tts = await get_tts_provider_async()
        info = tts.get_provider_info()
        components["tts"] = {
            "status": "healthy",
            "provider": info.get("provider", "unknown"),
            "voices_available": info.get("available_voices", 0),
        }
    except Exception as e:
        components["tts"] = {"status": "unhealthy", "error": str(e)}

    # --- Overall ---
    all_healthy = all(
        c.get("status") == "healthy" for c in components.values()
    )

    return {
        "status": "healthy" if all_healthy else "degraded",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": components,
    }


@router.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "AI Interviewer System",
        "version": "0.1.0",
        "docs": "/docs",
    }
