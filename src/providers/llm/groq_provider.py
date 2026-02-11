"""
Groq Cloud LLM Provider.

Uses Groq's OpenAI-compatible chat completions API for fast inference
on Llama, Mixtral, Gemma, and other models hosted on Groq's LPU hardware.

Requires a ``GROQ_API_KEY`` environment variable (free tier available at
https://console.groq.com).
"""
import json
import logging
import time
from typing import AsyncIterator, Dict, List, Optional

import httpx

from src.providers.llm.base import (
    BaseLLMProvider,
    GenerationConfig,
    LLMResponse,
    Message,
)

logger = logging.getLogger(__name__)

# Groq-hosted models (non-exhaustive; new models added frequently)
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "llama-3.2-1b-preview",
    "llama-3.2-3b-preview",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

DEFAULT_MODEL = "llama-3.1-70b-versatile"


class GroqLLMProvider(BaseLLMProvider):
    """
    LLM provider backed by the Groq cloud inference API.

    Groq exposes an OpenAI-compatible ``/chat/completions`` endpoint,
    so the implementation closely mirrors ``VLLMProvider``.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        api_url: str = "https://api.groq.com/openai/v1",
        timeout: float = 60.0,
        **kwargs,
    ):
        super().__init__(model=model, **kwargs)
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key

        if not self.api_key:
            raise ValueError(
                "Groq API key is required. Set the GROQ_API_KEY environment "
                "variable or pass api_key= explicitly."
            )

        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )

        logger.info(
            "GroqLLMProvider configured: model=%s, api_url=%s",
            self.model,
            self.api_url,
        )

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: List[Message],
        config: Optional[GenerationConfig] = None,
    ) -> LLMResponse:
        """Generate a response from the Groq LLM."""
        config = config or GenerationConfig()
        start = time.perf_counter()

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "stream": False,
        }

        if config.stop_sequences:
            payload["stop"] = config.stop_sequences

        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()

            latency = (time.perf_counter() - start) * 1000

            choice = data["choices"][0]
            usage = data.get("usage", {})

            return LLMResponse(
                content=choice["message"]["content"],
                model=data.get("model", self.model),
                finish_reason=choice.get("finish_reason"),
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                latency_ms=latency,
            )
        except httpx.HTTPStatusError as e:
            logger.error("Groq API error: %s — %s", e.response.status_code, e.response.text)
            raise
        except Exception as e:
            logger.error("Groq LLM generation failed: %s", e)
            raise

    async def generate_stream(
        self,
        messages: List[Message],
        config: Optional[GenerationConfig] = None,
    ) -> AsyncIterator[str]:
        """Stream tokens from the Groq LLM."""
        config = config or GenerationConfig()

        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "stream": True,
        }

        if config.stop_sequences:
            payload["stop"] = config.stop_sequences

        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[len("data: "):]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except httpx.HTTPStatusError as e:
            logger.error("Groq stream error: %s — %s", e.response.status_code, e.response.text)
            raise
        except Exception as e:
            logger.error("Groq LLM streaming failed: %s", e)
            raise

    # ------------------------------------------------------------------
    # Health & lifecycle
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if the Groq API is reachable."""
        try:
            resp = await self._client.get("/models")
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Groq health check failed: %s", e)
            return False

    async def list_models(self) -> List[str]:
        """List models available on Groq."""
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            logger.warning("Failed to list Groq models: %s", e)
            return GROQ_MODELS  # fallback to known list

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
