"""Webhook Tool - Emit webhooks and wait for callbacks."""
import httpx
import structlog
from typing import Dict, Any, Optional
from datetime import datetime, UTC
from uuid import uuid4

logger = structlog.get_logger(__name__)


class WebhookTool:
    """
    MCP-style webhook tool for emit and wait patterns.

    Supports:
    - Emitting webhooks to external systems
    - Generating callback URLs for workflow suspension
    - Validating webhook signatures (future)
    """

    def __init__(self, callback_base_url: str, timeout: int = 30):
        self.callback_base_url = callback_base_url
        self.timeout = timeout
        self.logger = logger.bind(tool="webhook")

    @property
    def emit_spec(self) -> Dict[str, Any]:
        """MCP spec for webhook emission"""
        return {
            "name": "webhook_emit",
            "description": "Send webhook to external system",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "format": "uri",
                        "description": "Webhook destination URL"
                    },
                    "payload": {
                        "type": "object",
                        "description": "Webhook payload"
                    },
                    "headers": {
                        "type": "object",
                        "description": "Custom headers",
                        "additionalProperties": {"type": "string"}
                    },
                    "callback_url": {
                        "type": "string",
                        "format": "uri",
                        "description": "Optional callback URL for responses"
                    }
                },
                "required": ["url", "payload"]
            }
        }

    @property
    def wait_spec(self) -> Dict[str, Any]:
        """MCP spec for webhook wait"""
        return {
            "name": "webhook_wait",
            "description": "Generate callback URL and suspend until webhook received",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "Name of event to wait for"
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Max wait time (default 3600)",
                        "default": 3600
                    }
                },
                "required": ["event_name"]
            }
        }

    async def emit(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        callback_url: Optional[str] = None,
        idempotency_key: str = ""
    ) -> Dict[str, Any]:
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

        # Add callback URL to payload if provided
        if callback_url:
            payload = {
                **payload,
                "callback_url": callback_url
            }

        self.logger.info(
            "webhook_emit_start",
            webhook_id=webhook_id,
            url=url,
            has_callback=callback_url is not None,
            idempotency_key=idempotency_key
        )

        start_time = datetime.now(UTC)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url=url,
                    json=payload,
                    headers=headers or {}
                )

                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

                result = {
                    "webhook_id": webhook_id,
                    "status": "sent",
                    "status_code": response.status_code,
                    "response_body": response.text,
                    "metadata": {
                        "duration_ms": duration_ms,
                        "idempotency_key": idempotency_key,
                        "timestamp": start_time.isoformat()
                    }
                }

                self.logger.info(
                    "webhook_emit_success",
                    webhook_id=webhook_id,
                    status_code=response.status_code,
                    duration_ms=duration_ms
                )

                return result

        except httpx.HTTPError as e:
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            self.logger.error(
                "webhook_emit_failed",
                webhook_id=webhook_id,
                url=url,
                error=str(e),
                duration_ms=duration_ms
            )
            raise

    def generate_callback_url(
        self,
        run_id: str,
        step_id: str,
        event_name: str
    ) -> str:
        """
        Generate callback URL for webhook suspension.

        Args:
            run_id: Current run ID
            step_id: Current step ID
            event_name: Name of event to wait for

        Returns:
            Callback URL
        """
        callback_token = str(uuid4())
        callback_url = (
            f"{self.callback_base_url}/webhooks/callback"
            f"/{run_id}/{step_id}/{event_name}?token={callback_token}"
        )

        self.logger.info(
            "callback_url_generated",
            run_id=run_id,
            step_id=step_id,
            event_name=event_name,
            callback_url=callback_url
        )

        return callback_url

    async def wait_for_webhook(
        self,
        event_name: str,
        timeout_seconds: int = 3600,
        run_id: str = "",
        step_id: str = ""
    ) -> Dict[str, Any]:
        """
        Generate callback URL and indicate workflow should suspend.

        NOTE: This doesn't actually block - it returns a special marker
        that tells the workflow engine to suspend until the webhook is received.

        Args:
            event_name: Name of event to wait for
            timeout_seconds: Max wait time
            run_id: Current run ID
            step_id: Current step ID

        Returns:
            Dict with callback URL and suspension marker
        """
        callback_url = self.generate_callback_url(run_id, step_id, event_name)

        return {
            "action": "suspend",
            "reason": f"waiting_for_webhook:{event_name}",
            "callback_url": callback_url,
            "timeout_seconds": timeout_seconds,
            "metadata": {
                "event_name": event_name,
                "run_id": run_id,
                "step_id": step_id
            }
        }
