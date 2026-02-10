"""
AI Interviewer System - Main FastAPI Application

This is the entry point for the interview system API.
"""
import os
import sys

# Register NVIDIA pip-package DLL directories so ctranslate2 (faster-whisper)
# can find cublas64_12.dll, cudnn, etc. on Windows.  Must happen before any
# ctranslate2 / faster_whisper import.
# NOTE: os.add_dll_directory() is NOT enough — ctranslate2 loads CUDA kernels
# at inference time via a path that only checks the system PATH.
if sys.platform == "win32":
    _site_packages = os.path.join(os.path.dirname(sys.executable), "..", "Lib", "site-packages")
    _nvidia_dirs = [
        os.path.join(_site_packages, "nvidia", "cublas", "bin"),
        os.path.join(_site_packages, "nvidia", "cudnn", "bin"),
    ]
    _prepend = []
    for _d in _nvidia_dirs:
        _d = os.path.normpath(_d)
        if os.path.isdir(_d):
            _prepend.append(_d)
    if _prepend:
        os.environ["PATH"] = os.pathsep.join(_prepend) + os.pathsep + os.environ.get("PATH", "")

import logging
from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.core.database import mongodb_client
from src.core.storage import storage_client
from src.api import health, documents, interviews, questions, voice, sessions, reports
from src.api.middleware import AuthMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting AI Interviewer System...")
    
    # Initialize MongoDB connection
    await mongodb_client.connect()
    logger.info("MongoDB connection established")
    
    # Initialize S3/MinIO storage (with local fallback)
    await storage_client.initialize()
    logger.info(f"Storage initialized (backend: {storage_client.storage_type})")
    
    # Eager-load embedding model so first request isn't penalized.
    # SentenceTransformer.__init__ is CPU/GPU-bound (~10-30s), so run in
    # a thread to keep the event loop responsive during startup.
    from src.services.semantic_matcher import get_semantic_matcher
    logger.info("Loading embedding model (this may take a moment)...")
    await asyncio.to_thread(get_semantic_matcher)
    logger.info("Embedding model ready")
    
    # Eager-load TTS model so first synthesis request isn't penalized.
    # Coqui XTTS v2 downloads ~1.8 GB of weights on first run and loads
    # them into RAM/VRAM, which can take 30-60 s.  If the TTS package
    # isn't installed, the factory silently falls back to pyttsx3 (which
    # initialises instantly), so this is safe either way.
    from src.providers.tts import get_tts_provider_async
    logger.info("Loading TTS model...")
    tts = await get_tts_provider_async()
    # If the provider supports async model loading (Coqui), trigger it now.
    if hasattr(tts, "ensure_loaded"):
        await tts.ensure_loaded()
    logger.info("TTS model ready (%s)", tts.get_provider_info().get("provider", "unknown"))
    
    yield
    
    # Shutdown
    logger.info("Shutting down AI Interviewer System...")
    await mongodb_client.disconnect()
    logger.info("MongoDB connection closed")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="AI-powered autonomous interview system for technical and behavioral interviews",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add auth middleware (optional - can be disabled for development)
    # Note: Auth is also enforced at route level via Depends()
    # This middleware provides global auth enforcement if enabled
    if settings.auth_enabled:
        logger.info("JWT Authentication enabled")
    else:
        logger.warning("JWT Authentication DISABLED - development mode only!")
    
    # Include routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
    app.include_router(interviews.router, prefix="/api/v1/interviews", tags=["Interviews"])
    app.include_router(questions.router, prefix="/api/v1/questions", tags=["Questions"])
    app.include_router(voice.router, tags=["Voice"])
    app.include_router(sessions.router, tags=["Sessions"])
    app.include_router(reports.router, tags=["Reports"])
    
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
