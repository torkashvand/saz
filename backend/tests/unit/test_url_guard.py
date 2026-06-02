"""SSRF / allowlist protection for outbound tools.

Covers the shared ``validate_outbound_url`` guard plus its application in
``HttpTool`` and ``WebhookTool``. Internal/reserved targets must be blocked
even when allow-listed; arbitrary destinations must be blocked by default.
"""

import asyncio

import pytest

from saz.security.url_guard import URLNotAllowedError, validate_outbound_url
from saz.tools.http_tool import HttpTool
from saz.tools.webhook_tool import WebhookTool

# --------------------------- guard unit ---------------------------


def test_guard_blocks_when_no_allowlist():
    with pytest.raises(URLNotAllowedError, match="not in allowed_domains"):
        validate_outbound_url("https://evil.example/x", None)


def test_guard_allows_listed_public_host():
    # ".test" never resolves, so only the allowlist gate applies.
    assert validate_outbound_url("https://api.partner.test/x", ["api.partner.test"]) == (
        "api.partner.test"
    )


def test_guard_star_allows_public_but_still_blocks_internal_ip():
    assert validate_outbound_url("https://api.partner.test/x", ["*"]) == "api.partner.test"
    with pytest.raises(URLNotAllowedError, match="internal/reserved"):
        validate_outbound_url("http://127.0.0.1/x", ["*"])


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata
        "http://10.0.0.5/x",  # RFC1918
        "http://192.168.1.1/x",  # RFC1918
        "http://172.16.0.9/x",  # RFC1918
        "http://[::1]/x",  # IPv6 loopback
        "http://0.0.0.0/x",  # unspecified
    ],
)
def test_guard_blocks_internal_targets_even_when_allowlisted(url):
    from urllib.parse import urlparse

    host = urlparse(url).hostname
    with pytest.raises(URLNotAllowedError, match="internal/reserved"):
        validate_outbound_url(url, [host])


def test_guard_rejects_non_http_scheme():
    with pytest.raises(URLNotAllowedError, match="scheme"):
        validate_outbound_url("file:///etc/passwd", ["*"])


# --------------------------- HttpTool ---------------------------


def test_http_tool_fail_closed_without_allowlist():
    tool = HttpTool(allowed_domains=None, timeout=5)
    with pytest.raises(ValueError, match="not in allowed_domains"):
        asyncio.run(tool.execute(method="GET", url="https://anything.example/x"))


def test_http_tool_blocks_metadata_ip_even_if_allowlisted():
    tool = HttpTool(allowed_domains=["169.254.169.254"], timeout=5)
    with pytest.raises(ValueError, match="internal/reserved"):
        asyncio.run(tool.execute(method="GET", url="http://169.254.169.254/latest/meta-data"))


def test_http_tool_blocks_localhost_even_if_allowlisted():
    tool = HttpTool(allowed_domains=["localhost"], timeout=5)
    with pytest.raises(ValueError, match="internal/reserved"):
        asyncio.run(tool.execute(method="GET", url="http://localhost:8000/admin"))


# --------------------------- WebhookTool ---------------------------


def test_webhook_emit_fail_closed_by_default():
    tool = WebhookTool(callback_base_url="https://saz.test", timeout=5)
    with pytest.raises(ValueError, match="not in allowed_domains"):
        asyncio.run(tool.emit(url="https://anything.example/wh", payload={"x": 1}))


def test_webhook_emit_blocks_localhost():
    tool = WebhookTool(
        callback_base_url="https://saz.test", timeout=5, allowed_domains=["localhost"]
    )
    with pytest.raises(ValueError, match="internal/reserved"):
        asyncio.run(tool.emit(url="http://localhost:9000/wh", payload={"x": 1}))


def test_webhook_emit_blocks_metadata_ip():
    tool = WebhookTool(
        callback_base_url="https://saz.test", timeout=5, allowed_domains=["169.254.169.254"]
    )
    with pytest.raises(ValueError, match="internal/reserved"):
        asyncio.run(tool.emit(url="http://169.254.169.254/x", payload={"x": 1}))
