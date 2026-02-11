"""
LLM Provider Factory.

Creates the appropriate LLM provider based on configuration.
Supports automatic failover between providers.
"""
import logging
from typing import Optional

from src.core.config import load_model_config, get_settings
from src.providers.llm.base import BaseLLMProvider, LLMProvider
from src.providers.llm.vllm_provider import VLLMProvider
from src.providers.llm.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


class LLMProviderFactory:
    """
    Factory for creating LLM provider instances.
    
    Reads configuration and creates the appropriate provider.
    Supports fallback providers if primary is unavailable.
    """
    
    @staticmethod
    def create(
        provider_type: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> BaseLLMProvider:
        """
        Create an LLM provider instance.
        
        Args:
            provider_type: Provider type (vllm, ollama, etc.). If None, reads from config.
            model: Model name. If None, reads from config.
            **kwargs: Additional provider-specific arguments.
            
        Returns:
            Configured LLM provider instance.
        """
        # Load configuration
        config = load_model_config()
        settings = get_settings()
        llm_config = config.get("providers", {}).get("llm", {})
        
        # Use provided values or fall back to config
        provider_type = provider_type or llm_config.get("provider", "ollama")
        model = model or llm_config.get("model", "qwen2.5:3b")
        
        logger.info(f"Creating LLM provider: {provider_type} with model: {model}")
        
        if provider_type == LLMProvider.VLLM.value or provider_type == "vllm":
            return VLLMProvider(
                model=model,
                api_url=kwargs.get("api_url", settings.vllm_api_url),
                api_key=kwargs.get("api_key", settings.vllm_api_key),
                **{k: v for k, v in kwargs.items() if k not in ["api_url", "api_key"]}
            )
        
        elif provider_type == LLMProvider.OLLAMA.value or provider_type == "ollama":
            return OllamaProvider(
                model=model,
                api_url=kwargs.get("api_url", settings.ollama_api_url),
                **{k: v for k, v in kwargs.items() if k not in ["api_url"]}
            )
        
        elif provider_type == LLMProvider.OPENAI_COMPATIBLE.value or provider_type == "openai-compatible":
            # Use vLLM provider which speaks OpenAI protocol
            return VLLMProvider(
                model=model,
                api_url=kwargs.get("api_url", settings.vllm_api_url),
                api_key=kwargs.get("api_key", settings.vllm_api_key),
                **{k: v for k, v in kwargs.items() if k not in ["api_url", "api_key"]}
            )
        
        elif provider_type == LLMProvider.GROQ.value or provider_type == "groq":
            from src.providers.llm.groq_provider import GroqLLMProvider
            return GroqLLMProvider(
                model=model,
                api_key=kwargs.get("api_key", settings.groq_api_key),
                api_url=kwargs.get("api_url", settings.groq_api_url),
                **{k: v for k, v in kwargs.items() if k not in ["api_url", "api_key"]}
            )
        
        else:
            raise ValueError(f"Unsupported LLM provider: {provider_type}")
    
    @staticmethod
    async def create_with_fallback(
        primary_provider: Optional[str] = None,
        fallback_provider: str = "ollama",
        **kwargs
    ) -> BaseLLMProvider:
        """
        Create an LLM provider with automatic fallback.
        
        If primary provider is unavailable, falls back to secondary.
        
        Args:
            primary_provider: Primary provider type
            fallback_provider: Fallback provider type (default: ollama)
            **kwargs: Provider arguments
            
        Returns:
            Working LLM provider instance
        """
        # Try primary provider
        try:
            provider = LLMProviderFactory.create(primary_provider, **kwargs)
            if await provider.health_check():
                logger.info(f"Primary provider {primary_provider} is healthy")
                return provider
            else:
                logger.warning(f"Primary provider {primary_provider} health check failed")
                await provider.close()
        except Exception as e:
            logger.warning(f"Failed to create primary provider: {e}")
        
        # Try fallback provider
        logger.info(f"Falling back to {fallback_provider}")
        try:
            config = load_model_config()
            fallback_model = config.get("providers", {}).get("llm", {}).get("model", "qwen2.5:3b")
            
            # Convert model name for Ollama format if needed
            if fallback_provider == "ollama" and "/" in fallback_model:
                # Convert HuggingFace format to Ollama format
                fallback_model = "qwen2.5:3b"
            
            provider = LLMProviderFactory.create(
                fallback_provider,
                model=fallback_model,
                **kwargs
            )
            
            if await provider.health_check():
                logger.info(f"Fallback provider {fallback_provider} is healthy")
                return provider
            else:
                await provider.close()
                raise RuntimeError(f"Fallback provider {fallback_provider} is not available")
                
        except Exception as e:
            raise RuntimeError(f"No LLM provider available: {e}")


# Global provider instance (lazy loaded)
_llm_provider: Optional[BaseLLMProvider] = None


async def get_llm_provider() -> BaseLLMProvider:
    """
    Get or create the global LLM provider instance.
    
    Uses factory with fallback to ensure availability.
    """
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = await LLMProviderFactory.create_with_fallback()
    return _llm_provider


def get_llm_provider_sync() -> BaseLLMProvider:
    """
    Get LLM provider synchronously (without health check).
    
    Use this when you need a provider but can't await.
    Health check will happen on first use.
    """
    global _llm_provider
    if _llm_provider is None:
        _llm_provider = LLMProviderFactory.create()
    return _llm_provider
