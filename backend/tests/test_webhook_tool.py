"""Unit tests for WebhookTool.

The webhook tool has two surface areas:

  * ``wait_for_webhook`` — generates a callback URL and returns a
    suspension marker. The executor reads this marker to stop the run
    and persist callback_id metadata; the contract must remain stable.

  * ``emit`` — POSTs JSON payloads to an external system. Failure modes
    matter: a transport exception must propagate so the executor can
    mark the step failed and retry/replan.
"""

import asyncio

import httpx
import pytest

from saz.tools.webhook_tool import WebhookTool


@pytest.fixture
def tool() -> WebhookTool:
    return WebhookTool(callback_base_url="https://saz.test", timeout=5)


# --------------------------- wait ---------------------------


def test_webhook_tool_wait_returns_suspension_marker_with_callback_url(
    tool: WebhookTool,
) -> None:
    result = asyncio.run(
        tool.wait_for_webhook(event_name="approval", timeout_seconds=120, run_id="r1", step_id="s1")
    )
    assert result["action"] == "suspend"
    assert result["reason"] == "waiting_for_webhook:approval"
    assert result["timeout_seconds"] == 120
    assert result["metadata"] == {
        "event_name": "approval",
        "run_id": "r1",
        "step_id": "s1",
    }

    cb = result["callback_url"]
    # The URL must include the runtime identifiers so the callback API can
    # look up the suspended run/step deterministically.
    assert cb.startswith("https://saz.test/webhooks/callback/r1/s1/approval")
    assert "token=" in cb


def test_webhook_tool_wait_default_timeout_is_applied(tool: WebhookTool) -> None:
    result = asyncio.run(tool.wait_for_webhook(event_name="done", run_id="r1", step_id="s1"))
    # Default timeout from wait_spec is 3600s.
    assert result["timeout_seconds"] == 3600


def test_webhook_tool_generate_callback_url_includes_token(tool: WebhookTool) -> None:
    url1 = tool.generate_callback_url("r1", "s1", "approval")
    url2 = tool.generate_callback_url("r1", "s1", "approval")
    assert url1 != url2, "Each callback URL must carry a unique token to prevent replay"


# --------------------------- emit ---------------------------


def _mock_transport(status_code: int, body: dict | str | None = None) -> httpx.MockTransport:
    payload = body if body is not None else {"ok": True}

    async def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, str):
            return httpx.Response(status_code, text=payload)
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


def _install_transport(monkeypatch, transport: httpx.MockTransport) -> None:
    original_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("saz.tools.webhook_tool.httpx.AsyncClient", make_client)


def test_webhook_tool_emit_returns_metadata_on_success(
    tool: WebhookTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_transport(monkeypatch, _mock_transport(200, {"received": True}))

    result = asyncio.run(
        tool.emit(
            url="https://example.test/webhook",
            payload={"event": "ping"},
            headers={"X-Custom": "v"},
            idempotency_key="key-1",
        )
    )

    assert result["status"] == "sent"
    assert result["status_code"] == 200
    assert "received" in result["response_body"]
    assert result["metadata"]["idempotency_key"] == "key-1"
    assert result["metadata"]["duration_ms"] >= 0
    assert "timestamp" in result["metadata"]
    assert result["webhook_id"]


def test_webhook_tool_emit_includes_callback_url_in_payload_when_provided(
    tool: WebhookTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent_payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        sent_payloads.append(_json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    _install_transport(monkeypatch, httpx.MockTransport(handler))

    asyncio.run(
        tool.emit(
            url="https://example.test/wh",
            payload={"event": "ping"},
            callback_url="https://saz.test/cb/abc",
        )
    )

    assert len(sent_payloads) == 1
    assert sent_payloads[0]["event"] == "ping"
    assert sent_payloads[0]["callback_url"] == "https://saz.test/cb/abc"


def test_webhook_tool_emit_does_not_raise_on_non_2xx(
    tool: WebhookTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per the production contract, ``emit`` only raises on transport-level
    httpx.HTTPError. A 500 with a body comes back as ``status_code=500``
    so the caller can react to it explicitly."""
    _install_transport(monkeypatch, _mock_transport(500, {"error": "boom"}))

    result = asyncio.run(tool.emit(url="https://example.test/webhook", payload={"event": "ping"}))
    assert result["status_code"] == 500
    assert "boom" in result["response_body"]


def test_webhook_tool_emit_propagates_transport_errors(
    tool: WebhookTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    _install_transport(monkeypatch, httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPError):
        asyncio.run(tool.emit(url="https://unreachable.test/x", payload={"event": "ping"}))


# --------------------------- specs ---------------------------


def test_webhook_tool_emit_spec_requires_url_and_payload(tool: WebhookTool) -> None:
    spec = tool.emit_spec
    assert spec["name"] == "webhook_emit"
    assert set(spec["inputSchema"]["required"]) == {"url", "payload"}


def test_webhook_tool_wait_spec_requires_event_name(tool: WebhookTool) -> None:
    spec = tool.wait_spec
    assert spec["name"] == "webhook_wait"
    assert spec["inputSchema"]["required"] == ["event_name"]
