"""Tests for AuditSanitizer."""

from saz.audit.sanitizer import AuditSanitizer


def test_redact_secrets():
    """Sanitizer redacts common secret field names."""
    sanitizer = AuditSanitizer()

    payload = {
        "username": "john",
        "password": "secret123",
        "api_key": "sk_12345",
        "token": "bearer_xyz",
        "secret": "confidential",
        "credential": "cred_abc",
        "normal_field": "visible",
    }

    result = sanitizer.redact_payload(payload, pii_policy="redact")

    assert result["username"] == "john"
    assert result["password"] == "[REDACTED]"
    assert result["api_key"] == "[REDACTED]"
    assert result["token"] == "[REDACTED]"
    assert result["secret"] == "[REDACTED]"
    assert result["credential"] == "[REDACTED]"
    assert result["normal_field"] == "visible"


def test_redact_pii_email():
    """Sanitizer redacts email addresses."""
    sanitizer = AuditSanitizer()

    payload = {
        "email": "user@example.com",
        "contact": "sales@company.co.uk",
        "message": "Contact us at support@acme.org",
    }

    result = sanitizer.redact_payload(payload, pii_policy="redact")

    assert result["email"] == "[EMAIL]"
    assert result["contact"] == "[EMAIL]"
    assert "[EMAIL]" in result["message"]


def test_redact_pii_ip():
    """Sanitizer redacts IP addresses."""
    sanitizer = AuditSanitizer()

    payload = {
        "ip": "192.168.1.1",
        "source_ip": "10.0.0.1",
        "log": "Connection from 172.16.0.50",
    }

    result = sanitizer.redact_payload(payload, pii_policy="redact")

    assert result["ip"] == "[IP]"
    assert result["source_ip"] == "[IP]"
    assert "[IP]" in result["log"]


def test_policy_allow():
    """Policy 'allow' redacts secrets but allows PII."""
    sanitizer = AuditSanitizer()

    payload = {
        "password": "secret123",
        "email": "user@example.com",
        "ip": "192.168.1.1",
    }

    result = sanitizer.redact_payload(payload, pii_policy="allow")

    # Secrets still redacted, but PII allowed
    assert result["password"] == "[REDACTED]"
    assert result["email"] == "user@example.com"
    assert result["ip"] == "192.168.1.1"


def test_nested_dicts():
    """Sanitizer handles nested dictionaries."""
    sanitizer = AuditSanitizer()

    payload = {
        "user": {
            "name": "John",
            "password": "secret",
            "email": "john@example.com",
        },
        "config": {
            "api_key": "sk_12345",
            "endpoint": "https://api.example.com",
        },
    }

    result = sanitizer.redact_payload(payload, pii_policy="redact")

    assert result["user"]["name"] == "John"
    assert result["user"]["password"] == "[REDACTED]"
    assert result["user"]["email"] == "[EMAIL]"
    assert result["config"]["api_key"] == "[REDACTED]"
    assert result["config"]["endpoint"] == "https://api.example.com"


def test_lists():
    """Sanitizer handles lists."""
    sanitizer = AuditSanitizer()

    payload = {
        "users": [
            {"name": "Alice", "password": "secret1"},
            {"name": "Bob", "email": "bob@example.com"},
        ],
        "ips": ["192.168.1.1", "10.0.0.1"],
    }

    result = sanitizer.redact_payload(payload, pii_policy="redact")

    assert result["users"][0]["name"] == "Alice"
    assert result["users"][0]["password"] == "[REDACTED]"
    assert result["users"][1]["name"] == "Bob"
    assert result["users"][1]["email"] == "[EMAIL]"
    assert result["ips"][0] == "[IP]"
    assert result["ips"][1] == "[IP]"


def test_empty_payload():
    """Sanitizer handles empty payload."""
    sanitizer = AuditSanitizer()

    result = sanitizer.redact_payload({}, pii_policy="redact")

    assert result == {}


def test_non_dict_values():
    """Sanitizer handles non-dict values safely."""
    sanitizer = AuditSanitizer()

    payload = {
        "count": 42,
        "active": True,
        "data": None,
        "tags": ["a", "b", "c"],
    }

    result = sanitizer.redact_payload(payload, pii_policy="redact")

    assert result["count"] == 42
    assert result["active"] is True
    assert result["data"] is None
    assert result["tags"] == ["a", "b", "c"]
