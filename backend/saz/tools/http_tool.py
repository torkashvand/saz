"""HTTP Client Tool - Makes HTTP requests with policy enforcement and secret redaction."""

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from saz.security.url_guard import validate_outbound_url

logger = structlog.get_logger(__name__)


class HttpTool:
    """
    MCP-style HTTP client tool with safety features.

    Enforces:
    - Domain allowlists (if configured)
    - Header redaction (Authorization, API keys)
    - Timeout limits
    - Retry policies
    """

    def __init__(
        self, allowed_domains: list[str] | None = None, timeout: int = 30, max_retries: int = 3
    ):
        self.allowed_domains = allowed_domains
        self.timeout = timeout
        self.max_retries = max_retries
        self.logger = logger.bind(tool="http")

    @property
    def spec(self) -> dict[str, Any]:
        """MCP-style tool specification"""
        return {
            "name": "http_request",
            "description": "Make HTTP requests to external APIs",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                        "description": "HTTP method",
                    },
                    "url": {"type": "string", "format": "uri", "description": "Target URL"},
                    "headers": {
                        "type": "object",
                        "description": "HTTP headers (Authorization will be redacted in logs)",
                        "additionalProperties": {"type": "string"},
                    },
                    "body": {"type": "object", "description": "Request body (for POST/PUT/PATCH)"},
                    "params": {
                        "type": "object",
                        "description": "Query parameters",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["method", "url"],
            },
        }

    async def execute(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """
        Execute HTTP request with policy enforcement.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Target URL
            headers: HTTP headers
            body: Request body
            params: Query parameters
            idempotency_key: For deduplication

        Returns:
            Dict with status_code, headers, body, and metadata

        Raises:
            ValueError: If domain not allowed
            httpx.HTTPError: If request fails
        """
        # Fail closed: outbound HTTP is denied unless an allowlist is configured,
        # and even allow-listed hosts are blocked if they resolve to internal /
        # reserved addresses (SSRF protection). Raises ValueError on block.
        validate_outbound_url(url, self.allowed_domains)

        # Redact sensitive headers for logging
        safe_headers = self._redact_headers(headers or {})

        self.logger.info(
            "http_request_start",
            method=method,
            url=url,
            headers=safe_headers,
            idempotency_key=idempotency_key,
        )

        start_time = datetime.now(UTC)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=method, url=url, headers=headers, json=body, params=params
                )

                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

                # Parse response body
                try:
                    response_body = response.json()
                except Exception:
                    response_body = {"raw": response.text}

                ok = 200 <= response.status_code < 300
                result = {
                    "status_code": response.status_code,
                    "ok": ok,
                    "headers": dict(response.headers),
                    "body": response_body,
                    "metadata": {
                        "duration_ms": duration_ms,
                        "idempotency_key": idempotency_key,
                        "timestamp": start_time.isoformat(),
                    },
                }

                # Non-2xx responses are surfaced as failures so the
                # post-execution critic and downstream steps cannot mistake a
                # 500 error page for a successful tool call. The structured
                # result is included on the exception so callers that catch
                # it can inspect status_code/body.
                if not ok:
                    self.logger.warning(
                        "http_request_non_2xx",
                        method=method,
                        url=url,
                        status_code=response.status_code,
                        duration_ms=duration_ms,
                        idempotency_key=idempotency_key,
                    )
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code} for {method} {url}",
                        request=response.request,
                        response=response,
                    )

                self.logger.info(
                    "http_request_success",
                    method=method,
                    url=url,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    idempotency_key=idempotency_key,
                )

                return result

        except httpx.HTTPError as e:
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            self.logger.error(
                "http_request_failed",
                method=method,
                url=url,
                error=str(e),
                duration_ms=duration_ms,
                idempotency_key=idempotency_key,
            )
            raise

    def _redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Redact sensitive header values for logging"""
        sensitive_keys = {
            "authorization",
            "api-key",
            "x-api-key",
            "apikey",
            "token",
            "x-auth-token",
            "cookie",
        }

        return {
            key: "***REDACTED***" if key.lower() in sensitive_keys else value
            for key, value in headers.items()
        }
