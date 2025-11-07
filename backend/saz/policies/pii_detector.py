"""PII Detector — Detects and redacts personally identifiable information & secrets."""

from __future__ import annotations

import base64
import ipaddress
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from math import log2
from re import Pattern
from typing import Any, cast

import structlog

logger = structlog.get_logger(__name__)

# Cross-type priority: higher number wins and keeps its span; lower overlapping spans are dropped.
_PRIORITY: dict[str, int] = {
    # Most structured / should dominate
    "credit_card": 90,
    "iban": 90,
    "jwt": 85,
    "email": 80,
    "ssn": 80,
    # Vendor tokens above generic/entropy
    "google_api_key": 75,
    "github_token": 75,
    "sendgrid": 75,
    "stripe_sk": 75,
    "slack_token": 75,
    "twilio": 75,
    "aws_access_key_id": 75,
    # Generic tokens
    "api_key": 72,
    # KV secrets before generic/entropy
    "kv_secret": 70,
    "entropy_token": 55,
    # IP/MAC/phone — lowest among overlaps with numbers
    "ipv6": 50,
    "ipv4": 50,
    "mac": 50,
    "phone": 40,
}
# ------------------------------ Data structures ---------------------------------------- #


@dataclass(frozen=True)
class Finding:
    type: str
    value: str
    start: int
    end: int
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "value": self.value,
            "start": self.start,
            "end": self.end,
            "note": self.note,
        }


@dataclass
class PatternSpec:
    pattern: Pattern[str]
    validator: Callable[[str], tuple[bool, str | None]] | None = None
    masker: Callable[[str], str] | None = None


# ------------------------------ Utility validators ------------------------------------- #


def _luhn_ok(digits: str) -> bool:
    s, alt = 0, False
    for d in reversed(digits):
        n = ord(d) - 48
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        s += n
        alt = not alt
    return s % 10 == 0


def _iban_ok(iban: str) -> bool:
    s = (iban.replace(" ", "")).upper()
    if not 15 <= len(s) <= 34:
        return False
    s = s[4:] + s[:4]
    converted = "".join(str(ord(c) - 55) if c.isalpha() else c for c in s)
    rem = 0
    for ch in converted:
        rem = (rem * 10 + int(ch)) % 97
    return rem == 1


def _jwt_like(token: str) -> bool:
    parts = token.split(".")
    if len(parts) != 3:
        return False
    try:
        for p in parts:
            pad = "=" * (-len(p) % 4)
            base64.urlsafe_b64decode(p + pad)
        return True
    except Exception:
        return False


def _entropy_bits_per_char(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * log2(c / n) for c in freq.values())


def _has_structured_sequences(s: str) -> bool:
    """Heuristic: penalize obvious alphabet/digit runs that inflate entropy."""
    low = s.lower()
    # Simple checks: full alpha run or long digit run or long repeated pattern
    if "abcdefghijklmnopqrstuvwxyz" in low or "0123456789" in s:
        return True
    # Any 6+ strictly increasing alnum sequence (cheap check)
    streak = 1
    last = None
    for ch in low:
        if last is not None and ch.isalnum() and last.isalnum() and (ord(ch) - ord(last) == 1):
            streak += 1
            if streak >= 6:
                return True
        else:
            streak = 1
        last = ch
    return False


# ------------------------------ Detector ------------------------------------------------ #


class PIIDetector:
    """
    PII/secret detection & redaction with validation and smart masking.

    Detectors (name → regex):
      - email, phone, ssn, credit_card, iban
      - ipv4, ipv6, mac
      - jwt
      - api_key (generic 32+), kv_secret (password|token=...), entropy_token
      - common cloud/dev tokens: aws_access_key_id, google_api_key, github_token,
        slack_token, stripe_sk, sendgrid, twilio
    """

    _BASE_FLAGS = re.IGNORECASE | re.MULTILINE
    _IPV6_RE = re.compile(
        r"""
        (?<![0-9A-Fa-f:])                              # no hex/colon just before
        (?:
            (?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}   # 8 hextets (no compression)
          | (?:[0-9A-Fa-f]{1,4}:){1,7}:                # :: trailing
          | :(?::[0-9A-Fa-f]{1,4}){1,7}                # :: leading
          | (?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}
          | (?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}
          | (?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}
          | (?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}
          | (?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}
          | [0-9A-Fa-f]{1,4}:(?:(?::[0-9A-Fa-f]{1,4}){1,6})
        )
        (?![0-9A-Fa-f:])                               # no hex/colon just after
        """,
        re.VERBOSE | re.IGNORECASE,
    )
    _DEFAULT_SPECS: dict[str, PatternSpec] = {
        "email": PatternSpec(
            re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", _BASE_FLAGS)
        ),
        "phone": PatternSpec(
            re.compile(r"\b(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,4}\)?[\s\-.]?)?\d{3,4}[\s\-.]?\d{4}\b")
        ),
        "ssn": PatternSpec(
            re.compile(r"\b(?!000|666|9\d\d)\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b")
        ),
        "credit_card": PatternSpec(re.compile(r"\b(?:\d[ -]?){13,19}\b")),
        "iban": PatternSpec(re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", _BASE_FLAGS)),
        "ipv4": PatternSpec(re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
        "ipv6": PatternSpec(_IPV6_RE),
        "mac": PatternSpec(re.compile(r"\b[0-9A-F]{2}(?:[:-][0-9A-F]{2}){5}\b", re.IGNORECASE)),
        "jwt": PatternSpec(
            re.compile(r"\beyJ[0-9A-Za-z_\-]+?\.[0-9A-Za-z_\-]+?\.[0-9A-Za-z_\-]+?\b")
        ),
        "aws_access_key_id": PatternSpec(re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
        "google_api_key": PatternSpec(re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
        "github_token": PatternSpec(re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36}\b")),
        "slack_token": PatternSpec(re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,48}\b")),
        "stripe_sk": PatternSpec(re.compile(r"\bsk_(?:live|test)_[0-9A-Za-z]{24,}\b")),
        "sendgrid": PatternSpec(re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\b")),
        "twilio": PatternSpec(re.compile(r"\bSK[0-9a-f]{32}\b", re.IGNORECASE)),
        "api_key": PatternSpec(re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")),  # generic
        "kv_secret": PatternSpec(
            re.compile(
                r"""(?ix)                             # ignorecase, verbose
        \b(                                   # key must be a standalone token
            password|passwd|pwd|secret|token|bearer|authorization|
            api[_-]?key|access[_-]?key|client[_-]?secret
        )\b
        \s*[:=]\s*
        (?P<val>[^\s'"]{8,})                  # capture only the value
        """
            )
        ),
        "entropy_token": PatternSpec(re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")),
    }

    def __init__(
        self,
        enabled_detectors: Iterable[str] | None = None,
        *,
        email_allowlist_domains: Iterable[str] | None = None,
        redact_private_ips: bool = False,
        entropy_threshold_bits_per_char: float = 3.5,
    ) -> None:
        self.logger = logger.bind(policy="pii_detector")

        # Options
        self.email_allowlist = {d.lower() for d in (email_allowlist_domains or [])}
        self.redact_private_ips = redact_private_ips
        self.entropy_threshold = entropy_threshold_bits_per_char

        # Clone default specs per instance
        self.specs: dict[str, PatternSpec] = {
            k: PatternSpec(v.pattern, v.validator, v.masker) for k, v in self._DEFAULT_SPECS.items()
        }

        # Validators
        self.specs["email"].validator = self._validate_email
        self.specs["credit_card"].validator = self._validate_credit_card
        self.specs["iban"].validator = self._validate_iban
        self.specs["ipv4"].validator = self._validate_ip
        self.specs["ipv6"].validator = self._validate_ip
        self.specs["jwt"].validator = lambda v: (_jwt_like(v), None)
        self.specs["phone"].validator = self._validate_phone
        self.specs["entropy_token"].validator = self._validate_entropy
        self.specs["kv_secret"].validator = lambda v: (True, None)
        self.specs[
            "api_key"
        ].validator = self._validate_entropy  # generic long tokens → entropy guard

        # Maskers (explicit where useful)
        self.specs["email"].masker = self._mask_email
        self.specs["credit_card"].masker = self._mask_credit_card
        self.specs["iban"].masker = self._mask_iban
        self.specs["jwt"].masker = self._mask_jwt
        for k in (
            "aws_access_key_id",
            "google_api_key",
            "github_token",
            "slack_token",
            "stripe_sk",
            "sendgrid",
            "twilio",
            "api_key",
            "kv_secret",
            "entropy_token",
        ):
            self.specs[k].masker = self._mask_tail_hint
        for k in ("ipv4", "ipv6"):
            self.specs[k].masker = lambda _v: "<IP>"
        self.specs["mac"].masker = lambda _v: "<MAC>"
        self.specs["ssn"].masker = self._mask_ssn
        self.specs["phone"].masker = self._mask_phone

        # Ensure every spec has a callable masker (bullet-proofing)
        for name, spec in self.specs.items():
            if not callable(spec.masker):
                spec.masker = self._default_masker(name)

        # Enabled list
        self.enabled = (
            list(enabled_detectors) if enabled_detectors is not None else list(self.specs.keys())
        )

    # ----------------------------------- Public API ------------------------------------ #

    def detect(self, text: str) -> list[dict[str, Any]]:
        """Detect PII; returns list of dicts with {type, value, start, end, note}."""
        findings: list[Finding] = []
        for name in self.enabled:
            spec = self.specs.get(name)
            if not spec:
                continue
            for m in spec.pattern.finditer(text):
                raw = (
                    m.group("val") if name == "kv_secret" and "val" in m.groupdict() else m.group(0)
                )
                ok, note = spec.validator(raw) if spec.validator else (True, None)
                if ok:
                    findings.append(Finding(name, raw, m.start(), m.end(), note))
        deduped = self._dedupe(findings)
        if deduped:
            self.logger.warning(
                "pii_detected", count=len(deduped), types=sorted({f.type for f in deduped})
            )
        return [f.to_dict() for f in deduped]

    def redact(self, text: str, replacement: str = "***REDACTED***") -> str:
        """
        Redact PII from text.
        If replacement == "auto", use per-type smart masking; otherwise use the provided literal.
        """
        findings = [Finding(**cast(dict, f)) for f in self.detect(text)]
        if not findings:
            return text
        findings.sort(key=lambda f: f.start, reverse=True)

        out = text
        for f in findings:
            mask = self._mask(f.type, f.value) if replacement == "auto" else replacement
            out = out[: f.start] + mask + out[f.end :]
        return out

    def scan_dict(self, data: dict[str, Any]) -> list[str]:
        """Recursively scan a mapping and return JSON-like paths that contain PII."""
        paths: list[str] = []

        def _walk(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _walk(v, f"{path}.{k}" if path else str(k))
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _walk(v, f"{path}[{i}]")
            elif isinstance(obj, str):
                if self.detect(obj):
                    paths.append(path)

        _walk(data)
        if paths:
            self.logger.warning("pii_found_in_dict", paths=paths)
        return paths

    def redact_dict(
        self, data: dict[str, Any], replacement: str = "***REDACTED***"
    ) -> dict[str, Any]:
        """Recursively redact PII within a mapping."""

        def _walk(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_walk(v) for v in obj]
            if isinstance(obj, str):
                return self.redact(obj, replacement=replacement)
            return obj

        return cast(dict[str, Any], _walk(data))

    def add_custom_pattern(
        self,
        name: str,
        pattern: str | Pattern[str],
        *,
        validator: Callable[[str], tuple[bool, str | None]] | None = None,
        masker: Callable[[str], str] | None = None,
    ) -> None:
        """Register a custom detector at runtime."""
        compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
        self.specs[name] = PatternSpec(compiled, validator, masker or self._default_masker(name))
        if name not in self.enabled:
            self.enabled.append(name)
        self.logger.info("custom_pii_pattern_added", name=name)

    # ----------------------------------- Validators ------------------------------------ #

    def _validate_email(self, value: str) -> tuple[bool, str | None]:
        dom = value.split("@")[-1].lower()
        if dom in self.email_allowlist:
            return False, "allowlisted"
        return True, None

    def _validate_credit_card(self, value: str) -> tuple[bool, str | None]:
        digits = re.sub(r"\D", "", value)
        if not (13 <= len(digits) <= 19):
            return False, "length"
        return (_luhn_ok(digits), None)

    def _validate_iban(self, value: str) -> tuple[bool, str | None]:
        return _iban_ok(value), None

    def _validate_ip(self, value: str) -> tuple[bool, str | None]:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            return False, "parse"
        if not self.redact_private_ips and (ip.is_private or ip.is_loopback or ip.is_link_local):
            return False, "non-public"
        return True, None

    def _validate_phone(self, value: str) -> tuple[bool, str | None]:
        """Basic check: at least 7 digits."""
        digits = re.sub(r"\D", "", value)
        return (len(digits) >= 7, None if len(digits) >= 7 else "too-short")

    def _validate_entropy(self, value: str) -> tuple[bool, str | None]:
        h = _entropy_bits_per_char(value)
        if _has_structured_sequences(value):
            h -= 1.0  # small penalty for obvious sequences
        return (
            h >= self.entropy_threshold,
            "high-entropy" if h >= self.entropy_threshold else "low-entropy",
        )

    # ----------------------------------- Maskers --------------------------------------- #

    def _default_masker(self, kind: str) -> Callable[[str], str]:
        mapping: dict[str, Callable[[str], str]] = {
            # Structured identifiers
            "email": self._mask_email,
            "credit_card": self._mask_credit_card,
            "iban": self._mask_iban,
            "jwt": self._mask_jwt,
            "ipv4": lambda _v: "<IP>",
            "ipv6": lambda _v: "<IP>",
            "mac": lambda _v: "<MAC>",
            "ssn": self._mask_ssn,
            "phone": self._mask_phone,
            # Secrets/tokens → tail hint
            "aws_access_key_id": self._mask_tail_hint,
            "google_api_key": self._mask_tail_hint,
            "github_token": self._mask_tail_hint,
            "slack_token": self._mask_tail_hint,
            "stripe_sk": self._mask_tail_hint,
            "sendgrid": self._mask_tail_hint,
            "twilio": self._mask_tail_hint,
            "api_key": self._mask_tail_hint,
            "kv_secret": self._mask_tail_hint,
            "entropy_token": self._mask_tail_hint,
        }
        return mapping.get(kind, lambda _v: "***REDACTED***")

    def _mask(self, kind: str, value: str) -> str:
        """Return per-type masked representation; fall back safely if no masker is set."""
        spec = self.specs.get(kind)
        masker = spec.masker if spec and callable(spec.masker) else self._default_masker(kind)
        try:
            return masker(value)
        except Exception as exc:
            self.logger.warning("masker_failed", type=kind, error=str(exc))
            return "***REDACTED***"

    @staticmethod
    def _mask_email(v: str) -> str:
        name, dom = v.split("@", 1)
        return f"{name[:1]}***@{dom}"

    @staticmethod
    def _mask_credit_card(v: str) -> str:
        d = re.sub(r"\D", "", v)
        return f"{'*' * (len(d) - 4)}{d[-4:]}" if len(d) >= 4 else "***"

    @staticmethod
    def _mask_iban(v: str) -> str:
        return v[:4] + "*" * (len(v) - 8) + v[-4:] if len(v) > 8 else "<IBAN>"

    @staticmethod
    def _mask_jwt(v: str) -> str:
        parts = v.split(".")
        return (parts[0][:3] + ".…" + ".…") if len(parts) == 3 else "<JWT>"

    @staticmethod
    def _mask_ssn(v: str) -> str:
        last4 = re.sub(r"\D", "", v)[-4:]
        return f"***-**-{last4}" if last4 else "<SSN>"

    @staticmethod
    def _mask_phone(v: str) -> str:
        d = re.sub(r"\D", "", v)
        return "***" + d[-4:] if len(d) >= 4 else "***"

    @staticmethod
    def _mask_tail_hint(v: str) -> str:
        return (v[:4] + "…" + v[-4:]) if len(v) >= 8 else "<SECRET>"

    # ----------------------------------- Helpers --------------------------------------- #

    @staticmethod
    def _dedupe(items: list[Finding]) -> list[Finding]:
        """Deduplicate & resolve overlapping findings based on priority & span."""
        if not items:
            return []

        def pri(t: str) -> int:
            return _PRIORITY.get(t, 50)

        # Higher priority first, then longer span, then earlier start
        items.sort(key=lambda f: (-pri(f.type), -(f.end - f.start), f.start))

        kept: list[Finding] = []
        for f in items:
            drop = False
            for k in kept:
                # exact same span but different type → keep both
                if f.start == k.start and f.end == k.end and f.type != k.type:
                    continue
                # fully contained in already-kept span → drop
                if f.start >= k.start and f.end <= k.end:
                    drop = True
                    break
            if not drop:
                kept.append(f)

        uniq: dict[tuple[str, int, int, str], Finding] = {}
        for f in kept:
            uniq[(f.type, f.start, f.end, f.value)] = f
        return sorted(uniq.values(), key=lambda f: f.start)
