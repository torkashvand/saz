"""HttpTool must surface non-2xx HTTP responses as failures, not successes.

Bug being pinned: HttpTool.execute() never calls response.raise_for_status().
A 500 or 404 returns just like a 200 — same shape, status_code attribute set,
the only signal an httpx.HTTPError on transport-level failure. Downstream the
post-execution critic might catch it, but it might also accept a syntactically
valid JSON error page as success.

This file does NOT prescribe how the failure surfaces — raising
httpx.HTTPStatusError, returning {"status": "failed", ...}, or anything else
deliberate. The contract is: a 5xx must not look like a 2xx.
"""

import httpx
import pytest

from saz.tools.http_tool import HttpTool


@pytest.fixture
def tool() -> HttpTool:
    return HttpTool(allowed_domains=["example.com"], timeout=5)


def _mock_transport(status_code: int, body: dict | None = None) -> httpx.MockTransport:
    payload = body if body is not None else {"detail": f"error {status_code}"}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_http_tool_does_not_silently_return_500_as_success(tool: HttpTool, monkeypatch):
    """A 500 response must not come back looking like a 200.

    Either raise an httpx exception or return a structured failure with an
    explicit non-success indicator. Returning {"status_code": 500, "body": ...}
    with no other signal is a bug: callers that don't dig into status_code
    will treat it as success.
    """
    transport = _mock_transport(500)
    original_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("saz.tools.http_tool.httpx.AsyncClient", make_client)

    try:
        result = await tool.execute(method="GET", url="https://example.com/api")
    except httpx.HTTPError:
        return  # raising is one acceptable surfacing of the failure

    # If no exception, the result must explicitly signal failure.
    assert (
        result.get("status_code") == 500
    ), f"sanity check failed: got status_code={result.get('status_code')!r}"
    signaled = (
        result.get("ok") is False
        or result.get("success") is False
        or result.get("status") in ("failed", "error")
        or result.get("error") is not None
    )
    assert signaled, (
        "HttpTool returned a 5xx as an otherwise-normal result. Callers and "
        "the critic cannot distinguish 'request worked' from 'server returned "
        "500'. Either raise on non-2xx or add an explicit failure indicator."
    )


@pytest.mark.asyncio
async def test_http_tool_does_not_silently_return_404_as_success(tool: HttpTool, monkeypatch):
    """4xx parity with the 5xx test — same contract."""
    transport = _mock_transport(404)
    original_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("saz.tools.http_tool.httpx.AsyncClient", make_client)

    try:
        result = await tool.execute(method="GET", url="https://example.com/missing")
    except httpx.HTTPError:
        return

    assert result.get("status_code") == 404
    signaled = (
        result.get("ok") is False
        or result.get("success") is False
        or result.get("status") in ("failed", "error")
        or result.get("error") is not None
    )
    assert signaled, (
        "HttpTool returned a 404 as an otherwise-normal result. See the 500 "
        "test for the contract — non-2xx must be distinguishable from success."
    )


@pytest.mark.asyncio
async def test_http_tool_returns_2xx_normally(tool: HttpTool, monkeypatch):
    """Sanity: a successful 200 still comes through as success."""
    transport = _mock_transport(200, {"ok": True})
    original_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("saz.tools.http_tool.httpx.AsyncClient", make_client)

    result = await tool.execute(method="GET", url="https://example.com/ok")
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_http_tool_redacts_upstream_response_secrets(tool: HttpTool, monkeypatch):
    """Set-Cookie / sensitive response headers and credential-named body fields
    must be redacted before the result is returned (and thus persisted)."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "tok_secret_value_123", "name": "ok"},
            headers={
                "Set-Cookie": "session=supersecretcookie; HttpOnly",
                "WWW-Authenticate": "Bearer realm=x",
                "X-Trace-Id": "trace-123",
            },
        )

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("saz.tools.http_tool.httpx.AsyncClient", make_client)

    result = await tool.execute(method="GET", url="https://example.com/login")

    headers = result["headers"]
    assert headers["set-cookie"] == "***REDACTED***"
    assert headers["www-authenticate"] == "***REDACTED***"
    # Non-sensitive headers pass through.
    assert headers["x-trace-id"] == "trace-123"
    # Credential-named body fields are redacted by key name.
    assert result["body"]["access_token"] == "***REDACTED***"
    assert result["body"]["name"] == "ok"
    assert "supersecretcookie" not in str(result)


@pytest.mark.asyncio
async def test_http_tool_fails_closed_when_no_allowlist() -> None:
    """With no allowlist configured, outbound requests are denied."""
    closed = HttpTool(allowed_domains=None, timeout=5)
    with pytest.raises(ValueError, match="not in allowed_domains"):
        await closed.execute(method="GET", url="https://example.com/api")


@pytest.mark.asyncio
async def test_http_tool_blocks_unlisted_domain() -> None:
    tool = HttpTool(allowed_domains=["api.allowed.com"], timeout=5)
    with pytest.raises(ValueError, match="blocked"):
        await tool.execute(method="GET", url="https://evil.example.com/x")


@pytest.mark.asyncio
async def test_http_tool_wildcard_allows_all(monkeypatch) -> None:
    tool = HttpTool(allowed_domains=["*"], timeout=5)
    transport = _mock_transport(200, {"ok": True})
    original_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("saz.tools.http_tool.httpx.AsyncClient", make_client)
    result = await tool.execute(method="GET", url="https://anything.example.org/x")
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_http_tool_does_not_follow_redirect_to_loopback(monkeypatch) -> None:
    """SSRF guard: validate_outbound_url checks only the initial URL, so a
    followed 3xx to a loopback/internal host would bypass it. The client must
    not follow redirects — the redirect target must never be contacted."""
    contacted: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        contacted.append(str(request.url))
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})
        return httpx.Response(200, json={"pwned": True})

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr("saz.tools.http_tool.httpx.AsyncClient", make_client)

    tool = HttpTool(allowed_domains=["example.com"], timeout=5)
    try:
        await tool.execute(method="GET", url="https://example.com/x")
    except httpx.HTTPError:
        pass  # a 3xx surfacing as non-2xx is acceptable; not-following is the point

    assert contacted == [
        "https://example.com/x"
    ], f"redirect was followed to an internal host, bypassing the SSRF guard: {contacted}"
