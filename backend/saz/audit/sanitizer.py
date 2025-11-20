"""Audit sanitizer for PII and secret redaction."""

import re
from typing import Any


class AuditSanitizer:
    """
    Sanitize events before persistence to remove PII/secrets.

    Ensures audit logs are safe to store and query without exposing
    sensitive personal information or credentials.
    """

    # PII patterns (simplified - use comprehensive library in production)
    EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
    IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b")

    # Fields that should never be stored raw
    SENSITIVE_KEYS: set[str] = {
        "password",
        "token",
        "api_key",
        "api_token",
        "secret",
        "credential",
        "authorization",
        "cookie",
        "session_id",
        "access_token",
        "refresh_token",
        "private_key",
        "passphrase",
    }

    def sanitize_event(
        self, event_data: dict[str, Any], pii_policy: str = "redact"
    ) -> dict[str, Any]:
        """
        Sanitize an event dict according to PII policy.

        Args:
            event_data: Event data to sanitize
            pii_policy: Policy mode - "allow", "redact", or "block"

        Returns:
            Sanitized event data
        """
        if pii_policy == "allow":
            # Still redact secrets even if PII is allowed
            return self._redact_secrets(event_data)
        elif pii_policy == "redact":
            # Redact both secrets and PII
            return self._redact_all(event_data)
        elif pii_policy == "block":
            # Strict - redact everything sensitive
            return self._redact_all(event_data)

        return event_data

    def _redact_secrets(self, obj: Any) -> Any:
        """
        Remove credentials but allow PII.

        Args:
            obj: Object to sanitize (dict, list, str, or primitive)

        Returns:
            Sanitized object
        """
        if isinstance(obj, dict):
            return {
                (k if k.lower() not in self.SENSITIVE_KEYS else k): (
                    "[REDACTED]" if k.lower() in self.SENSITIVE_KEYS else self._redact_secrets(v)
                )
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [self._redact_secrets(item) for item in obj]
        elif isinstance(obj, str):
            # Redact tokens in strings
            if any(key in obj.lower() for key in ["bearer ", "token=", "api_key=", "secret="]):
                return "[REDACTED_TOKEN]"
        return obj

    def _redact_all(self, obj: Any) -> Any:
        """
        Remove both credentials and PII.

        Args:
            obj: Object to sanitize (dict, list, str, or primitive)

        Returns:
            Sanitized object
        """
        if isinstance(obj, dict):
            return {
                (k if k.lower() not in self.SENSITIVE_KEYS else k): (
                    "[REDACTED]" if k.lower() in self.SENSITIVE_KEYS else self._redact_all(v)
                )
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [self._redact_all(item) for item in obj]
        elif isinstance(obj, str):
            # Redact PII patterns
            text = obj

            # Email addresses
            text = self.EMAIL_PATTERN.sub("[EMAIL]", text)

            # IP addresses
            text = self.IP_PATTERN.sub("[IP]", text)

            # Phone numbers
            text = self.PHONE_PATTERN.sub("[PHONE]", text)

            # Tokens in strings
            if any(key in text.lower() for key in ["bearer ", "token=", "api_key=", "secret="]):
                text = "[REDACTED_TOKEN]"

            return text
        return obj

    def redact_payload(self, payload: dict[str, Any], pii_policy: str = "redact") -> dict[str, Any]:
        """
        Redact sensitive data from an event payload.

        Args:
            payload: Event payload dict
            pii_policy: Policy mode

        Returns:
            Sanitized payload
        """
        return self.sanitize_event(payload, pii_policy)
