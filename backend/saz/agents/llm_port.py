"""LLM Port - Abstraction for LLM client calls to enable testing.

This interface decouples agents from litellm, allowing:
- Offline unit tests with mock responses
- Easy swapping of LLM providers
- Centralized cost tracking and retries
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Standardized LLM response."""
    content: str
    total_tokens: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    model: Optional[str] = None


class LLMPort(ABC):
    """Abstract interface for LLM client calls."""

    @abstractmethod
    async def complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
        timeout: int = 30
    ) -> LLMResponse:
        """
        Call LLM with messages.

        Args:
            model: Model identifier (e.g., "gpt-4o")
            messages: List of message dicts with "role" and "content"
            temperature: Sampling temperature (0-2)
            max_tokens: Max tokens in response
            response_format: Optional format spec (e.g., {"type": "json_object"})
            timeout: Request timeout in seconds

        Returns:
            LLMResponse with content and token usage
        """
        pass


class LiteLLMPort(LLMPort):
    """Default implementation using litellm library."""

    async def complete(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
        timeout: int = 30
    ) -> LLMResponse:
        """Call litellm.completion and map to LLMResponse."""
        from litellm import completion

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout
        }

        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if response_format:
            kwargs["response_format"] = response_format

        response = completion(**kwargs)

        return LLMResponse(
            content=response.choices[0].message.content,
            total_tokens=response.usage.total_tokens,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            model=response.model
        )


# Global default instance
_default_port: Optional[LLMPort] = None


def get_llm_port() -> LLMPort:
    """Get global LLM port instance."""
    global _default_port
    if _default_port is None:
        _default_port = LiteLLMPort()
    return _default_port


def set_llm_port(port: LLMPort) -> None:
    """Override global LLM port (for testing)."""
    global _default_port
    _default_port = port
