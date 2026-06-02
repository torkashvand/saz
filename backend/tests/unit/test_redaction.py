"""Unit tests for secret value redaction."""

import json

from saz.security.redaction import REDACTED, redact_secret_values


def test_redacts_exact_match() -> None:
    out = redact_secret_values({"token": "super-secret-value"}, {"super-secret-value"})
    assert out == {"token": REDACTED}


def test_redacts_substring_in_larger_string() -> None:
    out = redact_secret_values({"auth": "Bearer super-secret-value"}, {"super-secret-value"})
    assert out == {"auth": f"Bearer {REDACTED}"}


def test_recurses_into_nested_structures() -> None:
    payload = {
        "headers": {"Authorization": "Bearer tok-abcdef"},
        "list": ["tok-abcdef", "safe"],
        "nested": {"deep": {"k": "x tok-abcdef y"}},
    }
    out = redact_secret_values(payload, {"tok-abcdef"})
    blob = json.dumps(out)
    assert "tok-abcdef" not in blob
    assert out["list"][1] == "safe"


def test_non_secret_values_unchanged() -> None:
    payload = {"a": "hello", "n": 5, "b": True, "none": None}
    out = redact_secret_values(payload, {"some-secret-value"})
    assert out == payload


def test_short_secrets_not_substring_redacted() -> None:
    # A 1-char "secret" must not scrub every occurrence of that char.
    out = redact_secret_values({"text": "a1a1a1"}, {"1"})
    assert out == {"text": "a1a1a1"}


def test_empty_secret_set_is_noop() -> None:
    payload = {"a": "anything"}
    assert redact_secret_values(payload, set()) == payload


def test_multiple_secrets_longest_first() -> None:
    out = redact_secret_values({"v": "prefix-secret-suffix"}, {"secret", "prefix-secret-suffix"})
    assert out == {"v": REDACTED}
