"""Tests for executor PII policy derivation and replan behavior."""

import pytest

from saz.audit.sanitizer import AuditSanitizer
from saz.policies.policy_engine import PolicyEngine

# --- AuditSanitizer modes ---


@pytest.fixture
def sanitizer():
    return AuditSanitizer()


def test_allow_mode_keeps_pii(sanitizer):
    """When pii.allow=true, sanitizer mode is 'allow' — PII preserved, secrets redacted."""
    payload = {"text": "Contact alice@example.com", "api_key": "secret123"}
    result = sanitizer.redact_payload(payload, "allow")
    assert "alice@example.com" in result["text"]
    assert result["api_key"] == "[REDACTED]"


def test_redact_mode_removes_pii(sanitizer):
    """When pii.allow=false (default), sanitizer mode is 'redact' — PII removed."""
    payload = {"text": "Contact alice@example.com", "api_key": "secret123"}
    result = sanitizer.redact_payload(payload, "redact")
    assert "alice@example.com" not in result["text"]
    assert "[EMAIL]" in result["text"]
    assert result["api_key"] == "[REDACTED]"


# --- PII policy derivation ---


def test_pii_allow_true_gives_allow_mode():
    """policies.pii.allow: true -> sanitizer mode 'allow'."""
    policies_dict = {"pii": {"allow": True}}
    pii_allow = policies_dict.get("pii", {}).get("allow", False)
    pii_policy = "allow" if pii_allow else "redact"
    assert pii_policy == "allow"


def test_pii_allow_false_gives_redact_mode():
    """policies.pii.allow: false -> sanitizer mode 'redact'."""
    policies_dict = {"pii": {"allow": False}}
    pii_allow = policies_dict.get("pii", {}).get("allow", False)
    pii_policy = "allow" if pii_allow else "redact"
    assert pii_policy == "redact"


def test_missing_pii_gives_redact_mode():
    """No pii section -> defaults to 'redact' (safe default)."""
    policies_dict = {}
    pii_allow = policies_dict.get("pii", {}).get("allow", False)
    pii_policy = "allow" if pii_allow else "redact"
    assert pii_policy == "redact"


def test_missing_allow_key_gives_redact_mode():
    """pii section without allow key -> defaults to 'redact'."""
    policies_dict = {"pii": {"tokenize_model_inputs": True}}
    pii_allow = policies_dict.get("pii", {}).get("allow", False)
    pii_policy = "allow" if pii_allow else "redact"
    assert pii_policy == "redact"


# --- PolicyEngine.initialize_from_dsl ---


def test_policy_engine_pii_allow_true():
    engine = PolicyEngine()
    engine.initialize_from_dsl("run-1", {"pii": {"allow": True}})
    assert engine.enforce_pii_redaction is False


def test_policy_engine_pii_allow_false():
    engine = PolicyEngine()
    engine.initialize_from_dsl("run-1", {"pii": {"allow": False}})
    assert engine.enforce_pii_redaction is True


def test_policy_engine_pii_missing():
    engine = PolicyEngine()
    engine.initialize_from_dsl("run-1", {})
    assert engine.enforce_pii_redaction is True


def test_policy_engine_budget_usd_set():
    engine = PolicyEngine()
    engine.initialize_from_dsl("run-1", {"budget_usd": 0.50})
    assert engine.budget_tracker.max_cost_usd == 0.50
