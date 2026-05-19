"""Tests for PolicyEngine PII tokenization/detokenization."""

import pytest

from saz.policies.budget_tracker import BudgetTracker
from saz.policies.pii_detector import PIIDetector
from saz.policies.policy_engine import PolicyEngine, PolicyViolation
from saz.policies.rate_limiter import RateLimiter


@pytest.fixture
def policy_engine() -> PolicyEngine:
    """Create PolicyEngine with PII handling enabled."""
    return PolicyEngine(
        rate_limiter=RateLimiter(calls_per_minute=100, calls_per_hour=1000),
        pii_detector=PIIDetector(),
        budget_tracker=BudgetTracker(max_cost_usd=10.0),
        enforce_pii_redaction=False,  # Don't block, use tokenization instead
        tokenize_model_inputs=True,
        pii_allow_lists={
            "email_send": ["to", "from", "subject"],
            "http_request": ["headers.Authorization"],
        },
    )


# ------------------------------- Model Tool Tokenization -----------------------------------


def test_model_tool_arguments_tokenized():
    """Test that model tools get PII tokenized in arguments."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-001"

    arguments = {
        "instruction": "Extract email from text",
        "data": {"text": "Contact alice@example.com for help"},
    }

    # Tokenize for model tool
    tokenized = engine.tokenize_arguments(
        tool_name="ai.extract", arguments=arguments, run_id=run_id
    )

    # Email should be tokenized
    assert "__PII_EMAIL_" in tokenized["data"]["text"]
    assert "alice@example.com" not in str(tokenized)


def test_non_model_tool_arguments_not_tokenized():
    """Test that non-model tools don't get tokenized."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-002"

    arguments = {"url": "https://api.example.com", "body": {"email": "alice@example.com"}}

    # Should not tokenize for http_request (outbound tool)
    result = engine.tokenize_arguments(tool_name="http_request", arguments=arguments, run_id=run_id)

    # Should return unchanged (tokenization only for model tools)
    assert result["body"]["email"] == "alice@example.com"


def test_tokenization_disabled():
    """Test that tokenization can be disabled."""
    engine = PolicyEngine(tokenize_model_inputs=False)
    run_id = "test-run-003"

    arguments = {"instruction": "Extract data", "data": {"email": "alice@example.com"}}

    result = engine.tokenize_arguments(tool_name="ai.extract", arguments=arguments, run_id=run_id)

    # Should not tokenize when disabled
    assert result["data"]["email"] == "alice@example.com"


def test_tokenization_deterministic_across_steps():
    """Test that same PII value gets same token across multiple steps."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-004"

    email = "alice@example.com"

    # Step 1: tokenize
    args1 = {"data": {"email": email}}
    tokenized1 = engine.tokenize_arguments("ai.extract", args1, run_id)

    # Step 2: tokenize same email again
    args2 = {"data": {"contact": email}}
    tokenized2 = engine.tokenize_arguments("ai.generate", args2, run_id)

    # Should get same token
    token1 = tokenized1["data"]["email"]
    token2 = tokenized2["data"]["contact"]
    assert token1 == token2


# ------------------------------- Outbound Tool Detokenization ------------------------------


def test_outbound_tool_detokenization_allowed_paths():
    """Test selective detokenization for outbound tools."""
    engine = PolicyEngine(
        tokenize_model_inputs=True,
        pii_allow_lists={"http_request": ["headers.Authorization"]},
    )
    run_id = "test-run-005"

    # First tokenize (simulate model step output)
    vault = engine._get_token_vault(run_id)
    token_auth = vault.tokenize("api_key", "sk_test_secret123")

    # Prepare arguments with token only in allowed path
    arguments = {
        "url": "https://api.example.com",
        "headers": {"Authorization": f"Bearer {token_auth}", "Content-Type": "application/json"},
    }

    # Detokenize for outbound tool
    detokenized = engine.detokenize_arguments("http_request", arguments, run_id)

    # Authorization header should be detokenized (allowed path)
    assert "sk_test_secret123" in detokenized["headers"]["Authorization"]


def test_outbound_tool_disallowed_paths_raise_error():
    """Test that PII on disallowed paths raises PolicyViolation."""
    engine = PolicyEngine(
        tokenize_model_inputs=True,
        pii_allow_lists={"http_request": ["headers.Authorization"]},  # Only allow Authorization
    )
    run_id = "test-run-006"

    # Create token
    vault = engine._get_token_vault(run_id)
    token = vault.tokenize("api_key", "sk_test_secret123")

    # Put token in body (not allowed)
    arguments = {
        "url": "https://api.example.com",
        "body": {"secret_key": token},  # This path is not allowed
    }

    # Should raise PolicyViolation
    with pytest.raises(PolicyViolation) as exc_info:
        engine.detokenize_arguments("http_request", arguments, run_id)

    assert "non-approved paths" in str(exc_info.value).lower()
    assert "body.secret_key" in str(exc_info.value)


def test_outbound_tool_no_tokens_passes():
    """Test that outbound tools without tokens pass through."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-007"

    arguments = {"url": "https://api.example.com", "body": {"message": "Hello world"}}

    # Should pass through unchanged (no tokens present)
    result = engine.detokenize_arguments("http_request", arguments, run_id)
    assert result == arguments


def test_non_outbound_tool_detokenization_skipped():
    """Test that non-outbound tools skip detokenization."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-008"

    vault = engine._get_token_vault(run_id)
    token = vault.tokenize("email", "alice@example.com")

    arguments = {"email": token}

    # Model tools should not detokenize
    result = engine.detokenize_arguments("ai.extract", arguments, run_id)
    assert result["email"] == token  # Unchanged


# ------------------------------- Policy Check Integration ----------------------------------


def test_check_tool_call_model_tool_with_pii():
    """Test policy check allows model tools with PII (will be tokenized)."""
    engine = PolicyEngine(enforce_pii_redaction=False, tokenize_model_inputs=True)
    run_id = "test-run-009"

    engine.initialize_run(run_id)

    arguments = {"instruction": "Extract email", "data": {"text": "Email: alice@example.com"}}

    # Should pass (PII will be tokenized)
    allowed, reason = engine.check_tool_call("ai.extract", arguments, run_id)
    assert allowed is True


def test_check_tool_call_outbound_tool_with_pii_on_allowed_path():
    """Test policy check allows outbound tools with PII on allowed paths."""
    engine = PolicyEngine(
        enforce_pii_redaction=False,
        pii_allow_lists={"http_request": ["headers.Authorization"]},
    )
    run_id = "test-run-010"

    engine.initialize_run(run_id)

    arguments = {
        "url": "https://api.example.com",
        "headers": {"Authorization": "Bearer sk_test_secret"},
    }

    # Should pass (Authorization header is allowed)
    allowed, reason = engine.check_tool_call("http_request", arguments, run_id)
    assert allowed is True


def test_check_tool_call_outbound_tool_with_pii_on_disallowed_path():
    """Test policy check blocks outbound tools with PII on disallowed paths."""
    engine = PolicyEngine(
        enforce_pii_redaction=False,
        pii_allow_lists={"http_request": ["headers.Authorization"]},  # Only allow header
    )
    run_id = "test-run-011"

    engine.initialize_run(run_id)

    # Use longer API key (32+ chars) to ensure detection
    arguments = {
        "url": "https://api.example.com",
        "body": {"api_key": "sk_test_secretabcdefghijklmnopqrstuvwxyz1234"},  # Not allowed
    }

    # Should block (body.api_key is not allowed)
    allowed, reason = engine.check_tool_call("http_request", arguments, run_id)
    assert allowed is False
    assert "non-approved paths" in reason.lower()


# --------------------- artifact.store + other "non-outbound" tool PII allow-lists ----------
#
# These tests pin the regression where artifact.store was binary-blocking PII
# (e.g. requester emails) with no way to opt in. Audit artifacts are the run's
# permanent record of who requested / who approved a change — losing identity
# defeats the audit. The fix: extend the per-tool path allow-list mechanism
# (already used by outbound tools like http_request / ansible_run) to also
# apply to artifact.store and other "other tools" when pii.allow=false.


def test_check_tool_call_artifact_store_pii_blocked_without_allowlist():
    """Without a per-path exception, artifact.store must still block PII
    when pii.allow=false. Default behaviour is unchanged."""
    engine = PolicyEngine(enforce_pii_redaction=True)
    run_id = "test-artifact-deny"
    engine.initialize_run(run_id)

    args = {
        "name": "change_record",
        "content_type": "json",
        "content": {"requester": "alice@example.com", "title": "Rotate cert"},
    }
    allowed, reason = engine.check_tool_call("artifact.store", args, run_id)
    assert allowed is False
    assert "non-approved paths" in reason.lower()
    assert "content.requester" in reason


def test_check_tool_call_artifact_store_pii_allowed_on_listed_path():
    """When the YAML declares an exception for content.requester (or any
    other audit-identity path), artifact.store must accept the PII —
    audit artifacts legitimately need to preserve who requested what."""
    engine = PolicyEngine(
        enforce_pii_redaction=True,
        pii_allow_lists={"artifact.store": ["content.requester"]},
    )
    run_id = "test-artifact-allow"
    engine.initialize_run(run_id)

    args = {
        "name": "change_record",
        "content_type": "json",
        "content": {"requester": "alice@example.com", "title": "Rotate cert"},
    }
    allowed, reason = engine.check_tool_call("artifact.store", args, run_id)
    assert allowed, f"expected allowed, got reason: {reason}"


def test_check_tool_call_artifact_store_pii_allowed_on_nested_prefix():
    """A parent path in the allow-list must cover descendants — listing
    'content' should permit PII at 'content.requester', 'content.approval.by',
    etc. This is what makes the allow-list ergonomic for nested audit blobs."""
    engine = PolicyEngine(
        enforce_pii_redaction=True,
        pii_allow_lists={"artifact.store": ["content"]},
    )
    run_id = "test-artifact-nested"
    engine.initialize_run(run_id)

    args = {
        "name": "change_record",
        "content_type": "json",
        "content": {
            "requester": "alice@example.com",
            "approval": {"by": "bob@example.com"},
        },
    }
    allowed, _ = engine.check_tool_call("artifact.store", args, run_id)
    assert allowed


def test_check_tool_call_artifact_store_pii_partial_allowlist_blocks_unlisted_path():
    """If only some paths are listed, PII on an unlisted sibling path must
    still block. The allow-list is exact + descendants, not lax."""
    engine = PolicyEngine(
        enforce_pii_redaction=True,
        pii_allow_lists={"artifact.store": ["content.requester"]},
    )
    run_id = "test-artifact-partial"
    engine.initialize_run(run_id)

    args = {
        "name": "change_record",
        "content_type": "json",
        "content": {
            "requester": "alice@example.com",  # allowed
            "leaked_email": "eve@example.com",  # NOT allowed
        },
    }
    allowed, reason = engine.check_tool_call("artifact.store", args, run_id)
    assert allowed is False
    assert "content.leaked_email" in reason


# ------------------------------- DSL Initialization ----------------------------------------


def test_initialize_from_dsl_pii_config():
    """Test initializing PolicyEngine from DSL with PII config."""
    engine = PolicyEngine()
    run_id = "test-run-012"

    dsl_policies = {
        "budget_usd": 5.0,
        "pii": {
            "allow": False,
            "tokenize_model_inputs": True,
            "exceptions": {
                "tools": {
                    "http_request": {"allow": ["headers.Authorization", "headers.X-API-Key"]},
                    "email_send": ["to", "from", "subject", "body"],
                }
            },
        },
    }

    engine.initialize_from_dsl(run_id, dsl_policies)

    # Check PII config applied
    assert engine.enforce_pii_redaction is True  # allow=False means enforce
    assert engine.tokenize_model_inputs is True

    # Check allow-lists merged
    assert "http_request" in engine.pii_allow_lists
    assert "headers.Authorization" in engine.pii_allow_lists["http_request"]


def test_initialize_from_dsl_default_allow_lists():
    """Test that default allow-lists are applied."""
    engine = PolicyEngine()
    run_id = "test-run-013"

    dsl_policies = {"pii": {"allow": False}}

    engine.initialize_from_dsl(run_id, dsl_policies)

    # Should have defaults
    assert "email_send" in engine.pii_allow_lists
    assert "http_request" in engine.pii_allow_lists


def test_initialize_from_dsl_shorthand_array_format():
    """Test DSL with shorthand array format for allow-lists."""
    engine = PolicyEngine()
    run_id = "test-run-014"

    dsl_policies = {
        "pii": {
            "exceptions": {
                "tools": {
                    "http_request": ["headers.Authorization"],  # Shorthand array
                }
            }
        }
    }

    engine.initialize_from_dsl(run_id, dsl_policies)

    # Shorthand should be converted
    assert engine.pii_allow_lists["http_request"] == ["headers.Authorization"]


# ------------------------------- Token Vault Management ------------------------------------


def test_token_vault_created_per_run():
    """Test that each run gets its own token vault."""
    engine = PolicyEngine(tokenize_model_inputs=True)

    run_id_1 = "test-run-015"
    run_id_2 = "test-run-016"

    # Create vaults for different runs
    vault1 = engine._get_token_vault(run_id_1)
    vault2 = engine._get_token_vault(run_id_2)

    assert vault1 is not vault2
    assert vault1.run_id == run_id_1
    assert vault2.run_id == run_id_2


def test_token_vault_reused_within_run():
    """Test that same vault is reused within a run."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-017"

    vault1 = engine._get_token_vault(run_id)
    vault2 = engine._get_token_vault(run_id)

    assert vault1 is vault2


def test_clear_token_vault():
    """Test clearing token vault for a run."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-018"

    # Create vault and add tokens
    args = {"data": {"email": "alice@example.com"}}
    engine.tokenize_arguments("ai.extract", args, run_id)

    # Verify vault has tokens
    stats = engine.get_token_vault_stats(run_id)
    assert stats is not None
    assert stats["total_tokens"] > 0

    # Clear vault
    engine.clear_token_vault(run_id)

    # Vault should be gone
    stats_after = engine.get_token_vault_stats(run_id)
    assert stats_after is None


# ------------------------------- Compliance Report -----------------------------------------


def test_compliance_report_includes_tokenization():
    """Test that compliance report includes tokenization stats."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-019"

    engine.initialize_run(run_id)

    # Add some tokens
    args = {"data": {"email": "alice@example.com", "phone": "+1-555-1234"}}
    engine.tokenize_arguments("ai.extract", args, run_id)

    # Get compliance report
    report = engine.get_compliance_report(run_id)

    assert "pii_tokenization" in report
    assert report["pii_tokenization"] is not None
    assert report["policies_enforced"]["pii_tokenization"] is True


# ------------------------------- Edge Cases ------------------------------------------------


def test_multiple_pii_types_in_arguments():
    """Test handling multiple PII types in same arguments."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-020"

    arguments = {
        "data": {
            "email": "alice@example.com",
            "phone": "+1-555-1234",
            "card": "4111-1111-1111-1111",
            "ssn": "123-45-6789",
        }
    }

    tokenized = engine.tokenize_arguments("ai.extract", arguments, run_id)

    # All PII should be tokenized
    assert "__PII_EMAIL_" in str(tokenized)
    assert "__PII_PHONE_" in str(tokenized)
    assert "__PII_CREDIT_CARD_" in str(tokenized)
    assert "__PII_SSN_" in str(tokenized)

    # Original values should be gone
    assert "alice@example.com" not in str(tokenized)
    assert "4111-1111-1111-1111" not in str(tokenized)


def test_nested_pii_in_complex_structure():
    """Test PII handling in deeply nested structures."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-021"

    arguments = {
        "instruction": "Process ticket",
        "data": {
            "ticket": {
                "id": "T-001",
                "user": {"email": "alice@example.com", "profile": {"phone": "+1-555-1234"}},
                "comments": [
                    {"author": "bob@company.com", "text": "Contact me at +1-555-5678"},
                    {"author": "charlie@test.org", "text": "All good"},
                ],
            }
        },
    }

    tokenized = engine.tokenize_arguments("ai.assess", arguments, run_id)

    # All emails should be tokenized
    assert "alice@example.com" not in str(tokenized)
    assert "bob@company.com" not in str(tokenized)
    assert "charlie@test.org" not in str(tokenized)

    # Phones should be tokenized
    assert "+1-555-1234" not in str(tokenized)
    assert "+1-555-5678" not in str(tokenized)

    # Tokens should be present
    assert "__PII_EMAIL_" in str(tokenized)
    assert "__PII_PHONE_" in str(tokenized)


def test_empty_arguments():
    """Test handling empty arguments."""
    engine = PolicyEngine(tokenize_model_inputs=True)
    run_id = "test-run-022"

    arguments = {}

    tokenized = engine.tokenize_arguments("ai.extract", arguments, run_id)
    assert tokenized == {}

    detokenized = engine.detokenize_arguments("http_request", arguments, run_id)
    assert detokenized == {}
