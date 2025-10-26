"""PII Detector - Detects and redacts personally identifiable information."""
import re
import structlog
from typing import Any, Dict, List

logger = structlog.get_logger(__name__)


class PIIDetector:
    """
    PII detection and redaction using regex patterns.

    Detects:
    - Email addresses
    - Phone numbers (US/international)
    - Credit card numbers
    - SSN (US Social Security Numbers)
    - API keys (common patterns)
    - IP addresses
    """

    # Regex patterns for common PII
    PATTERNS = {
        "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        "phone_us": r'\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
        "credit_card": r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
        "api_key": r'\b[A-Za-z0-9_-]{32,}\b',  # Common API key length
        "ipv4": r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        "jwt": r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'
    }

    def __init__(self, enabled_detectors: List[str] = None):
        """
        Initialize PII detector.

        Args:
            enabled_detectors: List of detector names to enable (default: all)
        """
        if enabled_detectors is None:
            enabled_detectors = list(self.PATTERNS.keys())

        self.enabled_detectors = enabled_detectors
        self.logger = logger.bind(policy="pii_detector")

    def detect(self, text: str) -> List[Dict[str, Any]]:
        """
        Detect PII in text.

        Args:
            text: Text to scan

        Returns:
            List of detected PII items with type and location
        """
        detections = []

        for detector_name in self.enabled_detectors:
            if detector_name not in self.PATTERNS:
                continue

            pattern = self.PATTERNS[detector_name]
            matches = re.finditer(pattern, text)

            for match in matches:
                detections.append({
                    "type": detector_name,
                    "value": match.group(),
                    "start": match.start(),
                    "end": match.end()
                })

        if detections:
            self.logger.warning(
                "pii_detected",
                count=len(detections),
                types=[d["type"] for d in detections]
            )

        return detections

    def redact(self, text: str, replacement: str = "***REDACTED***") -> str:
        """
        Redact PII from text.

        Args:
            text: Text to redact
            replacement: Replacement string

        Returns:
            Text with PII redacted
        """
        redacted = text

        for detector_name in self.enabled_detectors:
            if detector_name not in self.PATTERNS:
                continue

            pattern = self.PATTERNS[detector_name]
            redacted = re.sub(pattern, replacement, redacted)

        return redacted

    def scan_dict(self, data: Dict[str, Any]) -> List[str]:
        """
        Recursively scan dictionary for PII.

        Args:
            data: Dictionary to scan

        Returns:
            List of paths where PII was found (e.g., ["user.email", "contact.phone"])
        """
        pii_paths = []

        def _scan_recursive(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    new_path = f"{path}.{key}" if path else key
                    _scan_recursive(value, new_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    new_path = f"{path}[{i}]"
                    _scan_recursive(item, new_path)
            elif isinstance(obj, str):
                detections = self.detect(obj)
                if detections:
                    pii_paths.append(path)

        _scan_recursive(data)

        if pii_paths:
            self.logger.warning(
                "pii_found_in_dict",
                paths=pii_paths
            )

        return pii_paths

    def redact_dict(
        self,
        data: Dict[str, Any],
        replacement: str = "***REDACTED***"
    ) -> Dict[str, Any]:
        """
        Recursively redact PII from dictionary.

        Args:
            data: Dictionary to redact
            replacement: Replacement string

        Returns:
            Dictionary with PII redacted
        """
        def _redact_recursive(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {
                    key: _redact_recursive(value)
                    for key, value in obj.items()
                }
            elif isinstance(obj, list):
                return [_redact_recursive(item) for item in obj]
            elif isinstance(obj, str):
                return self.redact(obj, replacement)
            else:
                return obj

        return _redact_recursive(data)

    def add_custom_pattern(self, name: str, pattern: str) -> None:
        """
        Add custom PII detection pattern.

        Args:
            name: Pattern name
            pattern: Regex pattern
        """
        self.PATTERNS[name] = pattern
        if name not in self.enabled_detectors:
            self.enabled_detectors.append(name)

        self.logger.info("custom_pii_pattern_added", name=name)
