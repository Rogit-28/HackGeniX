"""
LLM Provider Interface and Base Classes.

Defines the abstract interface for LLM providers, enabling plug-and-play
swapping between vLLM, Ollama, and other backends.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, AsyncIterator
from enum import Enum


class LLMProvider(str, Enum):
    """Supported LLM provider backends."""
    VLLM = "vllm"
    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"
    OPENAI_COMPATIBLE = "openai-compatible"
    GROQ = "groq"


@dataclass
class Message:
    """Chat message structure."""
    role: str  # "system", "user", "assistant"
    content: str
    
    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class GenerationConfig:
    """Configuration for text generation."""
    max_tokens: int = 1024
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50
    repetition_penalty: float = 1.1
    stop_sequences: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repetition_penalty": self.repetition_penalty,
            "stop": self.stop_sequences if self.stop_sequences else None,
        }


@dataclass
class LLMResponse:
    """Response from LLM generation."""
    content: str
    model: str
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None  # prompt_tokens, completion_tokens, total_tokens
    latency_ms: Optional[float] = None
    
    @property
    def prompt_tokens(self) -> int:
        return self.usage.get("prompt_tokens", 0) if self.usage else 0
    
    @property
    def completion_tokens(self) -> int:
        return self.usage.get("completion_tokens", 0) if self.usage else 0
    
    @property
    def tokens_used(self) -> int:
        """Total tokens used (prompt + completion)."""
        return self.usage.get("total_tokens", 0) if self.usage else 0


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    All LLM backends must implement this interface to be swappable.
    """
    
    def __init__(self, model: str, **kwargs):
        self.model = model
        self.config = kwargs
    
    @abstractmethod
    async def generate(
        self,
        messages: List[Message],
        config: Optional[GenerationConfig] = None,
    ) -> LLMResponse:
        """
        Generate a response from the LLM.
        
        Args:
            messages: List of chat messages (conversation history)
            config: Generation configuration (temperature, max_tokens, etc.)
            
        Returns:
            LLMResponse with generated content and metadata
        """
        pass
    
    @abstractmethod
    async def generate_stream(
        self,
        messages: List[Message],
        config: Optional[GenerationConfig] = None,
    ) -> AsyncIterator[str]:
        """
        Stream a response from the LLM token by token.
        
        Args:
            messages: List of chat messages
            config: Generation configuration
            
        Yields:
            Generated tokens as they become available
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM provider is healthy and responding."""
        pass
    
    def format_prompt(self, messages: List[Message]) -> str:
        """
        Format messages into a prompt string.
        Default implementation for chat format.
        """
        formatted = []
        for msg in messages:
            if msg.role == "system":
                formatted.append(f"<|system|>\n{msg.content}</s>")
            elif msg.role == "user":
                formatted.append(f"<|user|>\n{msg.content}</s>")
            elif msg.role == "assistant":
                formatted.append(f"<|assistant|>\n{msg.content}</s>")
        formatted.append("<|assistant|>\n")
        return "\n".join(formatted)


# Convenience functions for creating messages
def system_message(content: str) -> Message:
    """Create a system message."""
    return Message(role="system", content=content)


def user_message(content: str) -> Message:
    """Create a user message."""
    return Message(role="user", content=content)


def assistant_message(content: str) -> Message:
    """Create an assistant message."""
    return Message(role="assistant", content=content)
