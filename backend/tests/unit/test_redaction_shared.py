"""Shared redaction helper + audit sanitizer must catch sensitive key variants
by substring/suffix, not just an exact-match allowlist."""

import pytest

from saz.audit.sanitizer import AuditSanitizer
from saz.security.redaction import REDACTED, is_sensitive_key, redact_sensitive


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "passwd",
        "passphrase",
        "client_secret",
        "auth_token",
        "access_token",
        "refresh_token",
        "aws_secret_access_key",
        "db_password",
        "apikey",
        "api_key",
        "X-API-Key",
        "Authorization",
        "private_key",
        "session_cookie",
        "credential",
    ],
)
def test_is_sensitive_key_variants(key):
    assert is_sensitive_key(key), f"{key} should be detected as sensitive"


@pytest.mark.parametrize(
    "key",
    ["idempotency_key", "cache_key", "step_id", "url", "name", "username", "public_key_id"],
)
def test_non_sensitive_keys_not_flagged(key):
    # "public_key_id" intentionally not flagged: it contains no secret token.
    assert not is_sensitive_key(key), f"{key} should NOT be flagged"


def test_redact_sensitive_recurses_and_scrubs_values():
    obj = {
        "auth_token": "tok-1",
        "nested": {"aws_secret_access_key": "AKIA-secret", "ok": "visible"},
        "items": [{"db_password": "p"}, {"note": "contains tok-XYZ here"}],
    }
    out = redact_sensitive(obj, secret_values=["tok-XYZ"])
    assert out["auth_token"] == REDACTED
    assert out["nested"]["aws_secret_access_key"] == REDACTED
    assert out["nested"]["ok"] == "visible"
    assert out["items"][0]["db_password"] == REDACTED
    assert REDACTED in out["items"][1]["note"]  # value scrub


def test_audit_sanitizer_catches_key_variants():
    s = AuditSanitizer()
    payload = {
        "auth_token": "x",
        "client_secret": "y",
        "aws_secret_access_key": "z",
        "db_password": "w",
        "apikey": "k",
        "visible": "ok",
    }
    out = s.redact_payload(payload, pii_policy="redact")
    assert out["auth_token"] == "[REDACTED]"
    assert out["client_secret"] == "[REDACTED]"
    assert out["aws_secret_access_key"] == "[REDACTED]"
    assert out["db_password"] == "[REDACTED]"
    assert out["apikey"] == "[REDACTED]"
    assert out["visible"] == "ok"


def test_audit_sanitizer_redacts_ssn_in_text():
    s = AuditSanitizer()
    out = s.redact_payload({"note": "ssn 123-45-6789 here"}, pii_policy="redact")
    assert "[SSN]" in out["note"]
    assert "123-45-6789" not in out["note"]
