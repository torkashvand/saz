"""LiteLLMPort must translate provider transport failures into a domain
LLMTransportError so callers can distinguish 'provider unreachable' from
'model returned content we couldn't parse'."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from saz.agents.llm_port import LiteLLMPort, LLMTransportError


class _FakeResponse:
    """Just enough surface for LiteLLMPort.complete to extract content."""

    def __init__(self) -> None:
        self.choices = [type("Msg", (), {"message": type("M", (), {"content": "{}"})()})()]
        self.usage = type(
            "U", (), {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0}
        )()
        self.model = "gpt-test"


@pytest.mark.asyncio
async def test_completion_success_returns_llmresponse() -> None:
    """Baseline: when litellm returns normally, we map to LLMResponse."""

    with patch("litellm.completion", return_value=_FakeResponse()):
        port = LiteLLMPort()
        resp = await port.complete(model="gpt-test", messages=[{"role": "user", "content": "hi"}])
    assert resp.content == "{}"
    assert resp.total_tokens == 1


@pytest.mark.parametrize(
    "exc_attr",
    [
        "RateLimitError",
        "AuthenticationError",
        "APIConnectionError",
        "ServiceUnavailableError",
        "InternalServerError",
        "BudgetExceededError",
    ],
)
@pytest.mark.asyncio
async def test_transport_class_litellm_exceptions_become_llmtransporterror(exc_attr: str) -> None:
    """Provider-side failures must surface as LLMTransportError so the
    critic can re-raise them instead of bucketing them as ESCALATE."""

    import litellm.exceptions as lle

    exc_cls = getattr(lle, exc_attr)
    # Different litellm exception classes have wildly different __init__
    # signatures; just patch completion to raise an *instance* without
    # caring how it was constructed.
    instance = _make_instance(exc_cls)

    def _raise(**_kwargs: Any) -> Any:
        raise instance

    with patch("litellm.completion", side_effect=_raise):
        port = LiteLLMPort()
        with pytest.raises(LLMTransportError) as ei:
            await port.complete(model="gpt-test", messages=[{"role": "user", "content": "hi"}])
    # The translated message keeps the original class name for triage.
    assert exc_attr in str(ei.value)


def _make_instance(exc_cls: type[BaseException]) -> BaseException:
    """Construct a litellm exception in a signature-agnostic way."""

    candidates: list[tuple[tuple[Any, ...], dict[str, Any]]] = [
        ((), {}),
        (("test",), {}),
        ((), {"message": "test"}),
        (("test", "gpt-test", "openai"), {}),
        ((), {"message": "test", "model": "gpt-test", "llm_provider": "openai"}),
    ]
    last_err: BaseException | None = None
    for args, kwargs in candidates:
        try:
            return exc_cls(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise AssertionError(f"Could not instantiate {exc_cls.__name__}: {last_err}")


@pytest.mark.asyncio
async def test_none_content_raises_llmtransporterror() -> None:
    """A completion with no content must surface as LLMTransportError, not a
    silent None that later trips json.loads(None) with a TypeError."""
    resp = _FakeResponse()
    resp.choices = [type("Msg", (), {"message": type("M", (), {"content": None})()})()]
    with patch("litellm.completion", return_value=resp):
        port = LiteLLMPort()
        with pytest.raises(LLMTransportError) as exc_info:
            await port.complete(model="gpt-test", messages=[{"role": "user", "content": "hi"}])
    assert "empty" in str(exc_info.value).lower()
