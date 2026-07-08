"""Webhook Tool - Emit webhooks and wait for callbacks."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import structlog

from saz.security.url_guard import validate_outbound_url

logger = structlog.get_logger(__name__)


class WebhookTool:
    """
    MCP-style webhook tool for emit and wait patterns.

    Supports:
    - Emitting webhooks to external systems
    - Generating callback URLs for workflow suspension
    - Validating webhook signatures (future)
    """

    def __init__(
        self,
        callback_base_url: str,
        timeout: int = 30,
        allowed_domains: list[str] | None = None,
    ):
        self.callback_base_url = callback_base_url
        self.timeout = timeout
        # Fail-closed outbound allowlist for webhook_emit, mirroring HttpTool.
        # None/empty => no outbound emits permitted unless "*" is present.
        self.allowed_domains = allowed_domains
        self.logger = logger.bind(tool="webhook")

    @property
    def emit_spec(self) -> dict[str, Any]:
        """MCP spec for webhook emission"""
        return {
            "name": "webhook_emit",
            "description": "Send webhook to external system",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "format": "uri",
                        "description": "Webhook destination URL",
                    },
                    "payload": {"type": "object", "description": "Webhook payload"},
                    "headers": {
                        "type": "object",
                        "description": "Custom headers",
                        "additionalProperties": {"type": "string"},
                    },
                    "callback_url": {
                        "type": "string",
                        "format": "uri",
                        "description": "Optional callback URL for responses",
                    },
                },
                "required": ["url", "payload"],
            },
        }

    @property
    def wait_spec(self) -> dict[str, Any]:
        """MCP spec for webhook wait"""
        return {
            "name": "webhook_wait",
            "description": "Generate callback URL and suspend until webhook received",
            "input_schema": {
                "type": "object",
                "properties": {
                    "event_name": {"type": "string", "description": "Name of event to wait for"},
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Max wait time (default 3600)",
                        "default": 3600,
                    },
                },
                "required": ["event_name"],
            },
        }

    async def emit(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        callback_url: str | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """
        Emit webhook to external system.

        Args:
            url: Webhook destination URL
            payload: Webhook payload
            headers: Custom headers
            callback_url: Optional callback URL
            idempotency_key: For deduplication

        Returns:
            Dict with status, response, and metadata
        """
        webhook_id = str(uuid4())

        # Fail closed: deny unless the destination is allow-listed, and block
        # internal/reserved targets even when allow-listed (SSRF protection).
        validate_outbound_url(url, self.allowed_domains)

        # Add callback URL to payload if provided
        if callback_url:
            payload = {**payload, "callback_url": callback_url}

        self.logger.info(
            "webhook_emit_start",
            webhook_id=webhook_id,
            url=url,
            has_callback=callback_url is not None,
            idempotency_key=idempotency_key,
        )

        start_time = datetime.now(UTC)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url=url, json=payload, headers=headers or {})

                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

                result = {
                    "webhook_id": webhook_id,
                    "status": "sent",
                    "status_code": response.status_code,
                    "response_body": response.text,
                    "metadata": {
                        "duration_ms": duration_ms,
                        "idempotency_key": idempotency_key,
                        "timestamp": start_time.isoformat(),
                    },
                }

                self.logger.info(
                    "webhook_emit_success",
                    webhook_id=webhook_id,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                )

                return result

        except httpx.HTTPError as e:
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            self.logger.error(
                "webhook_emit_failed",
                webhook_id=webhook_id,
                url=url,
                error=str(e),
                duration_ms=duration_ms,
            )
            raise
