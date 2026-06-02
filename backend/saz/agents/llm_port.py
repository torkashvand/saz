"""LLM Port - Abstraction for LLM client calls to enable testing.

This interface decouples agents from litellm, allowing:
- Offline unit tests with mock responses
- Easy swapping of LLM providers
- Centralized cost tracking and retries
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMTransportError(RuntimeError):
    """The LLM call could not be completed for infrastructure reasons.

    Raised when the underlying provider is unreachable, rejected the request
    at the transport layer (rate limit, auth, quota, timeout, connection
    failure), or returned a non-domain error. Callers should treat this as a
    *failed run*, not as a model verdict — there is no critique here, the
    model never got a chance to weigh in.

    Domain errors (the model returned content but we couldn't parse it, the
    response failed schema validation, etc.) are *not* LLMTransportError —
    those are still subject to the verifier's normal safety-by-default
    behavior.
    """


@dataclass
class LLMResponse:
    """Standardized LLM response."""

    content: str
    total_tokens: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    model: str | None = None
    cost_usd: float = 0.0


class LLMPort(ABC):
    """Abstract interface for LLM client calls."""

    @abstractmethod
    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        timeout: int = 30,
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

    # LiteLLM exceptions that mean "we never got a usable response" — quota,
    # auth, network, or provider-side outages. None of these represent a
    # model verdict, so callers should treat them as run failures, not as
    # ESCALATE-to-human.
    _TRANSPORT_EXCEPTIONS: tuple[type[BaseException], ...] = ()

    @classmethod
    def _transport_exceptions(cls) -> tuple[type[BaseException], ...]:
        # Lazy-imported so importing this module doesn't pull litellm into
        # processes that don't need it (notably tests).
        if not cls._TRANSPORT_EXCEPTIONS:
            import litellm.exceptions as lle

            cls._TRANSPORT_EXCEPTIONS = (
                lle.RateLimitError,
                lle.AuthenticationError,
                lle.APIConnectionError,
                lle.APIError,
                lle.ServiceUnavailableError,
                lle.InternalServerError,
                lle.BudgetExceededError,
                lle.PermissionDeniedError,
                lle.NotFoundError,
                TimeoutError,
            )
        return cls._TRANSPORT_EXCEPTIONS

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> LLMResponse:
        """Call litellm.completion and map to LLMResponse."""
        import asyncio

        from litellm import completion

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout,
        }

        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if response_format:
            kwargs["response_format"] = response_format

        # Run sync litellm in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(None, lambda: completion(**kwargs))
        except self._transport_exceptions() as exc:
            raise LLMTransportError(f"{type(exc).__name__}: {exc}") from exc

        try:
            from litellm import completion_cost

            cost_usd = float(completion_cost(completion_response=response) or 0.0)
        except Exception:
            cost_usd = 0.0

        return LLMResponse(
            content=response.choices[0].message.content,
            total_tokens=response.usage.total_tokens,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            model=response.model,
            cost_usd=cost_usd,
        )


# Global default instance
_default_port: LLMPort | None = None


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
