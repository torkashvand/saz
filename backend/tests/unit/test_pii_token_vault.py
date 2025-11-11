"""Tests for PII Token Vault - deterministic tokenization/detokenization."""

import pytest

from saz.policies.pii_detector import PIIDetector
from saz.policies.pii_token_vault import PIITokenVault


@pytest.fixture
def detector() -> PIIDetector:
    """Create PIIDetector instance."""
    return PIIDetector()


@pytest.fixture
def vault() -> PIITokenVault:
    """Create PIITokenVault instance."""
    return PIITokenVault(run_id="test-run-123")


# ------------------------------- Basic Tokenization ----------------------------------------


def test_tokenize_deterministic(vault: PIITokenVault):
    """Test that same PII value produces same token."""
    token1 = vault.tokenize("email", "shahpoor@example.com")
    token2 = vault.tokenize("email", "shahpoor@example.com")

    assert token1 == token2
    assert token1.startswith("__PII_EMAIL_")
    assert token1.endswith("__")


def test_tokenize_different_values_get_different_tokens(vault: PIITokenVault):
    """Test that different PII values get different tokens."""
    token1 = vault.tokenize("email", "shahpoor@example.com")
    token2 = vault.tokenize("email", "bob@example.com")

    assert token1 != token2
    assert "__PII_EMAIL_1__" in [token1, token2]
    assert "__PII_EMAIL_2__" in [token1, token2]


def test_tokenize_different_types_same_value(vault: PIITokenVault):
    """Test that same value with different types gets different tokens."""
    token1 = vault.tokenize("email", "test@example.com")
    token2 = vault.tokenize("api_key", "test@example.com")

    assert token1 != token2
    assert "EMAIL" in token1
    assert "API_KEY" in token2


def test_detokenize_roundtrip(vault: PIITokenVault):
    """Test that tokenization can be reversed."""
    original_value = "shahpoor@example.com"
    original_type = "email"

    token = vault.tokenize(original_type, original_value)
    result = vault.detokenize(token)

    assert result is not None
    assert result == (original_type, original_value)


def test_detokenize_unknown_token(vault: PIITokenVault):
    """Test that unknown tokens return None."""
    result = vault.detokenize("__PII_EMAIL_999__")
    assert result is None


# ------------------------------- Text Tokenization -----------------------------------------


def test_tokenize_text_with_findings(vault: PIITokenVault, detector: PIIDetector):
    """Test tokenizing text with PII findings."""
    text = "Contact shahpoor@example.com or bob@company.com for details."
    findings = detector.detect(text)

    tokenized = vault.tokenize_text(text, findings)

    # Original emails should be gone
    assert "shahpoor@example.com" not in tokenized
    assert "bob@company.com" not in tokenized

    # Tokens should be present
    assert "__PII_EMAIL_1__" in tokenized
    assert "__PII_EMAIL_2__" in tokenized


def test_tokenize_text_no_findings(vault: PIITokenVault):
    """Test tokenizing text without PII."""
    text = "No PII here, just plain text."
    tokenized = vault.tokenize_text(text, [])

    assert tokenized == text


def test_tokenize_text_preserves_order(vault: PIITokenVault, detector: PIIDetector):
    """Test that tokenization preserves text structure."""
    text = "Send email to shahpoor@example.com and cc bob@company.com"
    findings = detector.detect(text)

    tokenized = vault.tokenize_text(text, findings)

    # Structure should be preserved
    assert "Send email to" in tokenized
    assert "and cc" in tokenized


def test_detokenize_text_roundtrip(vault: PIITokenVault, detector: PIIDetector):
    """Test full text tokenization/detokenization roundtrip."""
    original = "Contact shahpoor@example.com for help."
    findings = detector.detect(original)

    tokenized = vault.tokenize_text(original, findings)
    detokenized = vault.detokenize_text(tokenized)

    assert detokenized == original


# ------------------------------- Dict Tokenization -----------------------------------------


def test_tokenize_dict_simple(vault: PIITokenVault, detector: PIIDetector):
    """Test tokenizing dictionary with PII."""
    data = {
        "email": "shahpoor@example.com",
        "name": "shahpoor Smith",
        "message": "Contact me at bob@company.com",
    }

    tokenized = vault.tokenize_dict(data, detector)

    # PII should be tokenized
    assert "__PII_EMAIL_" in tokenized["email"]
    assert "shahpoor@example.com" not in str(tokenized)

    # Message with embedded PII should also be tokenized
    assert "__PII_EMAIL_" in tokenized["message"]
    assert "bob@company.com" not in tokenized["message"]

    # Non-PII should remain unchanged
    assert tokenized["name"] == "shahpoor Smith"


def test_tokenize_dict_nested(vault: PIITokenVault, detector: PIIDetector):
    """Test tokenizing nested dictionary."""
    data = {
        "user": {"email": "shahpoor@example.com", "phone": "+1-555-123-4567"},
        "metadata": {"source": "webhook", "ip": "192.168.1.1"},
    }

    tokenized = vault.tokenize_dict(data, detector)

    # Email should be tokenized
    assert "__PII_EMAIL_" in tokenized["user"]["email"]

    # Phone should be tokenized
    assert "__PII_PHONE_" in tokenized["user"]["phone"]

    # Private IP should not be redacted by default
    assert tokenized["metadata"]["ip"] == "192.168.1.1"


def test_tokenize_dict_with_lists(vault: PIITokenVault, detector: PIIDetector):
    """Test tokenizing dictionary containing lists."""
    data = {
        "recipients": ["shahpoor@example.com", "bob@company.com"],
        "message": "Please respond to charlie@test.org",
    }

    tokenized = vault.tokenize_dict(data, detector)

    # Emails in list should be tokenized
    assert all("__PII_EMAIL_" in email for email in tokenized["recipients"])
    assert "shahpoor@example.com" not in str(tokenized)

    # Email in message should be tokenized
    assert "__PII_EMAIL_" in tokenized["message"]


# ------------------------------- Selective Detokenization ----------------------------------


def test_detokenize_dict_all_paths(vault: PIITokenVault, detector: PIIDetector):
    """Test detokenizing all paths (allowed_paths=None)."""
    original = {"email": "shahpoor@example.com", "message": "Contact bob@company.com"}

    tokenized = vault.tokenize_dict(original, detector)
    detokenized = vault.detokenize_dict(tokenized, allowed_paths=None)

    assert detokenized["email"] == "shahpoor@example.com"
    assert "bob@company.com" in detokenized["message"]


def test_detokenize_dict_specific_paths(vault: PIITokenVault, detector: PIIDetector):
    """Test selective detokenization based on allowed paths."""
    original = {
        "to": "shahpoor@example.com",
        "from": "bob@company.com",
        "body": "Email me at charlie@test.org",
    }

    tokenized = vault.tokenize_dict(original, detector)

    # Only detokenize "to" and "from", not "body"
    allowed_paths = {"to", "from"}
    detokenized = vault.detokenize_dict(tokenized, allowed_paths=allowed_paths)

    # "to" and "from" should be restored
    assert detokenized["to"] == "shahpoor@example.com"
    assert detokenized["from"] == "bob@company.com"

    # "body" should still contain token
    assert "__PII_EMAIL_" in detokenized["body"]
    assert "charlie@test.org" not in detokenized["body"]


def test_detokenize_dict_nested_paths(vault: PIITokenVault, detector: PIIDetector):
    """Test selective detokenization with nested paths."""
    # Use longer API keys (32+ chars) to ensure detection
    original = {
        "headers": {"Authorization": "Bearer sk_test_abcdefghijklmnopqrstuvwxyz123456"},
        "body": {"api_key": "sk_live_secretabcdefghijklmnopqrstuvwxyz789"},
    }

    tokenized = vault.tokenize_dict(original, detector)

    # Only allow headers.Authorization
    allowed_paths = {"headers.Authorization"}
    detokenized = vault.detokenize_dict(tokenized, allowed_paths=allowed_paths)

    # Authorization header should be restored
    assert "sk_test_abcdefghijklmnopqrstuvwxyz123456" in detokenized["headers"]["Authorization"]

    # Body api_key should still be tokenized
    assert "__PII_" in str(detokenized["body"]["api_key"])


def test_detokenize_dict_empty_allowed_paths(vault: PIITokenVault, detector: PIIDetector):
    """Test that empty allow-list keeps everything tokenized."""
    original = {"email": "shahpoor@example.com", "phone": "+1-555-1234"}

    tokenized = vault.tokenize_dict(original, detector)
    detokenized = vault.detokenize_dict(tokenized, allowed_paths=set())

    # Nothing should be detokenized
    assert "__PII_EMAIL_" in detokenized["email"]
    assert "__PII_PHONE_" in detokenized["phone"]


# ------------------------------- Path Matching ---------------------------------------------


def test_path_matches_exact(vault: PIITokenVault):
    """Test exact path matching."""
    allowed = {"to", "from"}

    assert vault._path_matches_allowed("to", allowed)
    assert vault._path_matches_allowed("from", allowed)
    assert not vault._path_matches_allowed("body", allowed)


def test_path_matches_nested(vault: PIITokenVault):
    """Test nested path matching."""
    allowed = {"headers.Authorization", "body.email"}

    assert vault._path_matches_allowed("headers.Authorization", allowed)
    assert vault._path_matches_allowed("body.email", allowed)
    assert not vault._path_matches_allowed("headers.Content-Type", allowed)


def test_path_matches_with_array_indices(vault: PIITokenVault):
    """Test path matching with array indices."""
    allowed = {"recipients"}

    # Array indices should be stripped for matching
    assert vault._path_matches_allowed("recipients[0]", allowed)
    assert vault._path_matches_allowed("recipients[1]", allowed)


# ------------------------------- Scan for Tokens -------------------------------------------


def test_scan_for_tokens_finds_all(vault: PIITokenVault, detector: PIIDetector):
    """Test scanning dict for token locations."""
    original = {
        "to": "shahpoor@example.com",
        "from": "bob@company.com",
        "body": "Contact charlie@test.org",
    }

    tokenized = vault.tokenize_dict(original, detector)
    paths = vault.scan_for_tokens(tokenized)

    assert "to" in paths
    assert "from" in paths
    assert "body" in paths


def test_scan_for_tokens_nested(vault: PIITokenVault, detector: PIIDetector):
    """Test scanning nested dict for tokens."""
    # Use longer API key (32+ chars) to ensure detection
    original = {
        "user": {"email": "shahpoor@example.com"},
        "settings": {"api_key": "sk_test_abcdefghijklmnopqrstuvwxyz123"},
    }

    tokenized = vault.tokenize_dict(original, detector)
    paths = vault.scan_for_tokens(tokenized)

    assert "user.email" in paths
    assert "settings.api_key" in paths


def test_scan_for_tokens_none_present(vault: PIITokenVault):
    """Test scanning dict without tokens."""
    data = {"name": "shahpoor", "age": 30}

    paths = vault.scan_for_tokens(data)
    assert len(paths) == 0


# ------------------------------- Vault Statistics ------------------------------------------


def test_get_stats_empty(vault: PIITokenVault):
    """Test stats for empty vault."""
    stats = vault.get_stats()

    assert stats["run_id"] == "test-run-123"
    assert stats["total_tokens"] == 0
    assert stats["unique_values"] == 0


def test_get_stats_with_tokens(vault: PIITokenVault):
    """Test stats after tokenization."""
    vault.tokenize("email", "shahpoor@example.com")
    vault.tokenize("email", "bob@company.com")
    vault.tokenize("api_key", "sk_test_123")

    stats = vault.get_stats()

    assert stats["total_tokens"] == 3
    assert stats["unique_values"] == 3
    assert stats["tokens_by_type"]["email"] == 2
    assert stats["tokens_by_type"]["api_key"] == 1


def test_get_stats_deterministic_tokens(vault: PIITokenVault):
    """Test stats count deterministic tokens only once."""
    # Same value tokenized multiple times
    vault.tokenize("email", "shahpoor@example.com")
    vault.tokenize("email", "shahpoor@example.com")
    vault.tokenize("email", "shahpoor@example.com")

    stats = vault.get_stats()

    # Should only count once
    assert stats["total_tokens"] == 1
    assert stats["unique_values"] == 1
    assert stats["tokens_by_type"]["email"] == 1


# ------------------------------- Vault Clearing --------------------------------------------


def test_clear_vault(vault: PIITokenVault):
    """Test clearing vault removes all mappings."""
    vault.tokenize("email", "shahpoor@example.com")
    vault.tokenize("api_key", "sk_test_123")

    stats_before = vault.get_stats()
    assert stats_before["total_tokens"] == 2

    vault.clear()

    stats_after = vault.get_stats()
    assert stats_after["total_tokens"] == 0
    assert stats_after["unique_values"] == 0


def test_tokenize_after_clear(vault: PIITokenVault):
    """Test tokenization after clearing vault."""
    # First tokenization
    token1 = vault.tokenize("email", "shahpoor@example.com")
    assert token1 == "__PII_EMAIL_1__"

    vault.clear()

    # After clear, counter should reset
    token2 = vault.tokenize("email", "bob@company.com")
    assert token2 == "__PII_EMAIL_1__"  # Counter reset


# ------------------------------- Complex Scenarios -----------------------------------------


def test_multiple_pii_types_in_text(vault: PIITokenVault, detector: PIIDetector):
    """Test handling multiple PII types in one text."""
    text = "Email: shahpoor@example.com, Phone: +1-555-1234, Card: 4111111111111111"
    findings = detector.detect(text)

    tokenized = vault.tokenize_text(text, findings)

    # All PII should be tokenized
    assert "shahpoor@example.com" not in tokenized
    assert "+1-555-1234" not in tokenized
    assert "4111111111111111" not in tokenized

    # Different token types should be present
    assert "__PII_EMAIL_" in tokenized
    assert "__PII_PHONE_" in tokenized
    assert "__PII_CREDIT_CARD_" in tokenized


def test_overlapping_findings_handled(vault: PIITokenVault, detector: PIIDetector):
    """Test that overlapping PII findings are handled correctly."""
    # JWT tokens might overlap with other patterns
    text = (
        "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiO"
        "iIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    )
    findings = detector.detect(text)

    tokenized = vault.tokenize_text(text, findings)

    # Original token should be gone
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in tokenized
    # Some form of token should be present
    assert "__PII_" in tokenized


def test_detokenization_idempotent(vault: PIITokenVault, detector: PIIDetector):
    """Test that detokenization is idempotent."""
    original = {"email": "shahpoor@example.com"}

    tokenized = vault.tokenize_dict(original, detector)
    detokenized1 = vault.detokenize_dict(tokenized, allowed_paths=None)
    detokenized2 = vault.detokenize_dict(detokenized1, allowed_paths=None)

    assert detokenized1 == detokenized2
    assert detokenized2["email"] == "shahpoor@example.com"


def test_tokenization_preserves_non_string_types(vault: PIITokenVault, detector: PIIDetector):
    """Test that tokenization preserves non-string data types."""
    data = {
        "email": "shahpoor@example.com",
        "age": 30,
        "active": True,
        "balance": 123.45,
        "tags": None,
    }

    tokenized = vault.tokenize_dict(data, detector)

    # Email should be tokenized
    assert "__PII_EMAIL_" in tokenized["email"]

    # Other types should be unchanged
    assert tokenized["age"] == 30
    assert tokenized["active"] is True
    assert tokenized["balance"] == 123.45
    assert tokenized["tags"] is None
