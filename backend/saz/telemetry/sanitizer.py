"""Telemetry sanitization - Safe summaries without PII/secrets."""

from typing import Any

import structlog

from saz.policies.pii_detector import PIIDetector

logger = structlog.get_logger(__name__)


class TelemetrySanitizer:
    """
    Sanitizes data for telemetry emission.

    Ensures no raw PII, secrets, or prompts leak through telemetry.
    Generates safe summaries with schema views and truncated text.
    """

    MAX_SUMMARY_LENGTH = 160
    MAX_ARRAY_ITEMS = 5

    def __init__(self, pii_detector: PIIDetector | None = None):
        """
        Initialize sanitizer.

        Args:
            pii_detector: PII detector instance (uses default if None)
        """
        self.pii_detector = pii_detector or PIIDetector()
        self.logger = logger.bind(component="telemetry_sanitizer")

    def sanitize_input_summary(self, arguments: dict[str, Any]) -> str:
        """
        Generate safe input summary from tool arguments.

        Returns schema view with counts, not values.

        Args:
            arguments: Tool arguments

        Returns:
            Safe summary string (≤160 chars)
        """
        try:
            summary_parts = []

            for key, value in arguments.items():
                if isinstance(value, dict):
                    summary_parts.append(f"{key}:dict[{len(value)}]")
                elif isinstance(value, list):
                    summary_parts.append(f"{key}:list[{len(value)}]")
                elif isinstance(value, str):
                    # Truncate and redact
                    redacted = self.pii_detector.redact(value, replacement="<REDACTED>")
                    truncated = self._truncate(redacted, 40)
                    summary_parts.append(f"{key}={truncated}")
                elif isinstance(value, int | float | bool):
                    summary_parts.append(f"{key}={value}")
                else:
                    summary_parts.append(f"{key}:{type(value).__name__}")

            summary = ", ".join(summary_parts)
            return self._truncate(summary, self.MAX_SUMMARY_LENGTH)

        except Exception as e:
            self.logger.warning("input_summary_failed", error=str(e))
            return "<summary failed>"

    def sanitize_output_summary(self, result: Any) -> str:
        """
        Generate safe output summary.

        Args:
            result: Tool output

        Returns:
            Safe summary string (≤160 chars)
        """
        try:
            if isinstance(result, dict):
                keys = list(result.keys())[: self.MAX_ARRAY_ITEMS]
                return f"dict[{len(result)}]: {{{', '.join(keys)}}}"
            elif isinstance(result, list):
                return f"list[{len(result)}]"
            elif isinstance(result, str):
                redacted = self.pii_detector.redact(result, replacement="<REDACTED>")
                return self._truncate(redacted, self.MAX_SUMMARY_LENGTH)
            elif result is None:
                return "null"
            else:
                return f"{type(result).__name__}"

        except Exception as e:
            self.logger.warning("output_summary_failed", error=str(e))
            return "<summary failed>"

    def sanitize_intent(self, step: Any) -> str:
        """
        Extract safe intent description from step.

        Args:
            step: Plan step

        Returns:
            Intent string (≤160 chars)
        """
        try:
            if hasattr(step, "description") and step.description:
                desc = str(step.description)
                redacted = self.pii_detector.redact(desc, replacement="<REDACTED>")
                return self._truncate(redacted, self.MAX_SUMMARY_LENGTH)

            if hasattr(step, "action"):
                action = str(step.action)
                if hasattr(step, "tool_name"):
                    return f"{action}: {step.tool_name}"
                return action

            return "<no intent>"

        except Exception as e:
            self.logger.warning("intent_extraction_failed", error=str(e))
            return "<unknown>"

    def sanitize_critique_summary(self, critique: dict[str, Any]) -> str:
        """
        Generate safe critique summary.

        Args:
            critique: Critique result

        Returns:
            Safe summary string (≤160 chars)
        """
        try:
            verdict = critique.get("verdict", "unknown")
            confidence = critique.get("confidence", 0.0)
            issues = critique.get("issues", [])

            parts = [f"{verdict} ({confidence:.0%})"]

            if issues:
                first_issue = str(issues[0])[:60]
                parts.append(f"issue: {first_issue}")

            summary = " | ".join(parts)
            return self._truncate(summary, self.MAX_SUMMARY_LENGTH)

        except Exception as e:
            self.logger.warning("critique_summary_failed", error=str(e))
            return "<summary failed>"

    def sanitize_route_signal(self, signal: Any) -> str:
        """
        Sanitize route decision signal.

        Args:
            signal: Route signal/rationale

        Returns:
            Safe summary (≤80 chars)
        """
        try:
            if isinstance(signal, str):
                redacted = self.pii_detector.redact(signal, replacement="<REDACTED>")
                return self._truncate(redacted, 80)
            elif isinstance(signal, dict):
                return f"dict[{len(signal)}]"
            else:
                return str(type(signal).__name__)

        except Exception as e:
            self.logger.warning("route_signal_sanitization_failed", error=str(e))
            return "<signal>"

    def get_schema_view(self, data: dict[str, Any]) -> dict[str, str]:
        """
        Generate schema view showing keys and types, not values.

        Args:
            data: Dictionary to analyze

        Returns:
            Schema view dict
        """
        try:
            schema = {}

            for key, value in data.items():
                if isinstance(value, dict):
                    schema[key] = f"dict[{len(value)}]"
                elif isinstance(value, list):
                    schema[key] = f"list[{len(value)}]"
                else:
                    schema[key] = type(value).__name__

            return schema

        except Exception as e:
            self.logger.warning("schema_view_failed", error=str(e))
            return {}

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        """Truncate text with ellipsis if too long."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 1] + "…"
