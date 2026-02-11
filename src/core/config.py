"""
Core configuration module for the AI Interviewer System.
Loads settings from environment variables and config files.
"""
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Application
    app_name: str = "AI_Interviewer"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "interview_system"
    
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    
    # S3/MinIO Storage
    s3_endpoint_url: Optional[str] = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_name: str = "interview-system"
    s3_region: str = "us-east-1"
    
    # JWT Authentication
    jwt_secret_key: str = "your-super-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    auth_enabled: bool = True  # Set to False to disable auth (for development)
    
    # Model Provider Overrides
    provider_llm_model: Optional[str] = None
    provider_embeddings_model: Optional[str] = None
    provider_stt_model: Optional[str] = None
    provider_tts_provider: Optional[str] = None
    
    # vLLM
    vllm_api_url: str = "http://localhost:8001/v1"
    vllm_api_key: Optional[str] = None
    
    # Ollama
    ollama_api_url: str = "http://localhost:11434"
    
    # Groq Cloud API
    groq_api_key: Optional[str] = None
    groq_api_url: str = "https://api.groq.com/openai/v1"
    
    # Feature Flags
    enable_voice_pipeline: bool = True
    enable_tts_cache: bool = True
    enable_audio_logging: bool = False
    
    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"
    
    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def load_model_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load model configuration from YAML file.
    Environment variables can override config values.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "models.yaml"
    else:
        config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Model config not found: {config_path}")
    
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    
    # Apply environment variable overrides
    settings = get_settings()
    
    if settings.provider_llm_model:
        config["providers"]["llm"]["model"] = settings.provider_llm_model
    
    if settings.provider_embeddings_model:
        config["providers"]["embeddings"]["model"] = settings.provider_embeddings_model
    
    if settings.provider_stt_model:
        config["providers"]["stt"]["model"] = settings.provider_stt_model
    
    if settings.provider_tts_provider:
        config["providers"]["tts"]["provider"] = settings.provider_tts_provider
    
    return config


# Convenience function for accessing config in other modules
def get_model_config() -> Dict[str, Any]:
    """Get cached model configuration."""
    return load_model_config()
