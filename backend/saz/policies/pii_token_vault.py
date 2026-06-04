"""PII Token Vault - Run-scoped, deterministic tokenization for privacy-by-default."""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Array-index segments (``to[0]``) are normalized away before allow-list
# matching so a list of values is covered by the same allow-list entry as a
# scalar (``to``). Compiled once, shared by every caller.
_ARRAY_INDEX_RE = re.compile(r"\[\d+\]")


def path_matches_allowed(path: str, allowed_paths: set[str]) -> bool:
    """Return True if ``path`` is covered by any entry in ``allowed_paths``.

    Single source of truth for PII allow-list matching, used by both the token
    vault (selective detokenization) and the policy engine (outbound PII
    gating). An allowed entry covers the path itself plus anything nested under
    it (``headers`` covers ``headers.Authorization``); array indices are
    stripped first so ``to[0]`` matches an allowed ``to``.
    """
    clean_path = _ARRAY_INDEX_RE.sub("", path)
    if clean_path in allowed_paths:
        return True
    return any(
        clean_path.startswith(allowed + ".") or clean_path == allowed for allowed in allowed_paths
    )


class PIITokenVault:
    """
    Run-scoped, in-memory token vault for PII handling.

    Provides deterministic, reversible tokenization of PII values within a workflow run.
    Tokens are safe for logs, artifacts, and LLM prompts.

    Key properties:
    - Run-scoped: One vault per workflow run
    - Deterministic: Same PII value → same token within a run
    - Reversible: Tokens can be mapped back to original values
    - Safe: Tokens are clearly identifiable (e.g., __PII_EMAIL_1__)
    - Ephemeral: Cleared when run completes
    """

    # Pattern to match generated tokens
    TOKEN_PATTERN = re.compile(r"__PII_([A-Z_]+)_(\d+)__")

    def __init__(self, run_id: str):
        """
        Initialize token vault for a workflow run.

        Args:
            run_id: Workflow run identifier
        """
        self.run_id = run_id

        # Bidirectional mappings
        # Map: (pii_type, pii_value) -> token
        self._value_to_token: dict[tuple[str, str], str] = {}
        # Map: token -> (pii_type, pii_value)
        self._token_to_value: dict[str, tuple[str, str]] = {}

        # Counters for deterministic token generation per type
        self._counters: dict[str, int] = {}

        self.logger = logger.bind(run_id=run_id, component="pii_token_vault")
        self.logger.info("token_vault_initialized")

    def tokenize(self, pii_type: str, pii_value: str) -> str:
        """
        Generate deterministic token for a PII value.

        Same value + type combination returns the same token within this run.

        Args:
            pii_type: Type of PII (e.g., "email", "ssn", "api_key")
            pii_value: The actual PII value to tokenize

        Returns:
            Deterministic token string (e.g., "__PII_EMAIL_1__")
        """
        key = (pii_type, pii_value)

        # Return existing token if already mapped
        if key in self._value_to_token:
            return self._value_to_token[key]

        # Generate new deterministic token
        counter = self._counters.get(pii_type, 0) + 1
        self._counters[pii_type] = counter
        token = f"__PII_{pii_type.upper()}_{counter}__"

        # Store bidirectional mapping
        self._value_to_token[key] = token
        self._token_to_value[token] = (pii_type, pii_value)

        self.logger.debug(
            "pii_tokenized",
            pii_type=pii_type,
            token=token,
            value_length=len(pii_value),
        )

        return token

    def detokenize(self, token: str) -> tuple[str, str] | None:
        """
        Restore PII value from token.

        Args:
            token: Token string (e.g., "__PII_EMAIL_1__")

        Returns:
            Tuple of (pii_type, pii_value) or None if token not found
        """
        result = self._token_to_value.get(token)
        if result:
            self.logger.debug(
                "pii_detokenized",
                token=token,
                pii_type=result[0],
            )
        return result

    def tokenize_text(self, text: str, findings: list[dict[str, Any]]) -> str:
        """
        Replace PII in text with tokens based on detection findings.

        Args:
            text: Original text containing PII
            findings: List of PII findings from PIIDetector.detect()
                     Each finding has: {type, value, start, end}

        Returns:
            Text with PII replaced by tokens
        """
        if not findings:
            return text

        # Sort findings by start position in reverse order for safe replacement
        sorted_findings = sorted(findings, key=lambda f: f["start"], reverse=True)

        result = text
        token_count = 0

        for finding in sorted_findings:
            token = self.tokenize(finding["type"], finding["value"])
            result = result[: finding["start"]] + token + result[finding["end"] :]
            token_count += 1

        if token_count > 0:
            self.logger.info(
                "text_tokenized",
                original_length=len(text),
                tokenized_length=len(result),
                pii_count=token_count,
            )

        return result

    def detokenize_text(self, text: str) -> str:
        """
        Restore all PII in text from tokens.

        Args:
            text: Text containing tokens

        Returns:
            Text with tokens replaced by original PII values
        """
        if not isinstance(text, str):
            return text

        token_count = 0

        def replace_token(match: re.Match) -> str:
            nonlocal token_count
            token = match.group(0)
            value_tuple = self.detokenize(token)
            if value_tuple:
                token_count += 1
                return value_tuple[1]  # return pii_value
            return token

        result = re.sub(self.TOKEN_PATTERN, replace_token, text)

        if token_count > 0:
            self.logger.info(
                "text_detokenized",
                token_count=token_count,
            )

        return result

    def tokenize_dict(self, data: dict[str, Any], pii_detector: Any) -> dict[str, Any]:
        """
        Recursively tokenize PII in a dictionary.

        Args:
            data: Dictionary potentially containing PII
            pii_detector: PIIDetector instance for detecting PII

        Returns:
            Dictionary with PII replaced by tokens
        """

        def _walk(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_walk(v) for v in obj]
            elif isinstance(obj, str):
                findings = pii_detector.detect(obj)
                if findings:
                    return self.tokenize_text(obj, findings)
                return obj
            else:
                return obj

        return _walk(data)

    def detokenize_dict(
        self, data: dict[str, Any], allowed_paths: set[str] | None = None
    ) -> dict[str, Any]:
        """
        Selectively detokenize PII in a dictionary based on allowed paths.

        If allowed_paths is None, detokenize everything.
        If allowed_paths is provided, only detokenize values at those paths.

        Args:
            data: Dictionary containing tokens
            allowed_paths: Set of dotted paths where detokenization is allowed
                          (e.g., {"to", "from", "headers.Authorization"})
                          If None, detokenize all paths.

        Returns:
            Dictionary with selective PII restoration
        """

        def _walk(obj: Any, path: str = "") -> Any:
            if isinstance(obj, dict):
                return {k: _walk(v, f"{path}.{k}" if path else k) for k, v in obj.items()}
            elif isinstance(obj, list):
                # For lists, detokenize if the parent path is allowed
                return [_walk(v, f"{path}[{i}]") for i, v in enumerate(obj)]
            elif isinstance(obj, str):
                # Check if this path is allowed for detokenization
                if allowed_paths is None or self._path_matches_allowed(path, allowed_paths):
                    return self.detokenize_text(obj)
                return obj
            else:
                return obj

        return _walk(data)

    def _path_matches_allowed(self, path: str, allowed_paths: set[str]) -> bool:
        """
        Check if a path matches any allowed path pattern.

        Supports exact matches and prefix matches.
        Examples:
          - "to" matches "to"
          - "headers.Authorization" matches "headers.Authorization"
          - "to" matches "to" even if actual path is "to" (exact match)

        Args:
            path: Current path being checked
            allowed_paths: Set of allowed path patterns

        Returns:
            True if path is allowed for detokenization
        """
        return path_matches_allowed(path, allowed_paths)

    def scan_for_tokens(self, data: dict[str, Any]) -> list[str]:
        """
        Scan dictionary for paths containing tokens.

        Args:
            data: Dictionary to scan

        Returns:
            List of dotted paths containing tokens
        """
        paths: list[str] = []

        def _walk(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _walk(v, f"{path}.{k}" if path else k)
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _walk(v, f"{path}[{i}]")
            elif isinstance(obj, str):
                if self.TOKEN_PATTERN.search(obj):
                    paths.append(path)

        _walk(data)
        return paths

    def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about tokenization.

        Returns:
            Dictionary with token vault statistics
        """
        return {
            "run_id": self.run_id,
            "total_tokens": len(self._token_to_value),
            "tokens_by_type": dict(self._counters),
            "unique_values": len(self._value_to_token),
        }

    def clear(self) -> None:
        """Clear all token mappings (called when run completes)."""
        token_count = len(self._token_to_value)
        self._value_to_token.clear()
        self._token_to_value.clear()
        self._counters.clear()
        self.logger.info("token_vault_cleared", tokens_cleared=token_count)
