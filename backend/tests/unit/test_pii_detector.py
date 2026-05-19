import base64
import re

import pytest

from saz.policies.pii_detector import PIIDetector


@pytest.fixture
def det() -> PIIDetector:
    return PIIDetector()


# ------------------------------- Email --------------------------------------------------


def test_email_detection_and_masking_auto(det: PIIDetector):
    text = "Contact me at alice.smith@example.org for details."
    findings = det.detect(text)
    types = {f["type"] for f in findings}
    assert "email" in types
    masked = det.redact(text, replacement="auto")
    assert masked.startswith("Contact me at a***@example.org")
    # original email should be gone
    assert "alice.smith@example.org" not in masked


def test_email_allowlist_blocks_detection():
    det = PIIDetector(email_allowlist_domains=["example.org"])
    text = "Allowlisted: alice@example.org; Non-allowlisted: bob@company.com"
    findings = det.detect(text)
    values = [f["value"] for f in findings if f["type"] == "email"]
    assert "alice@example.org" not in values
    assert "bob@company.com" in values


# ------------------------------- Credit cards / IBAN -----------------------------------


@pytest.mark.parametrize(
    "card",
    [
        "4111 1111 1111 1111",  # Visa test
        "4012-8888-8888-1881",  # Visa test (with dashes)
        "378282246310005",  # Amex
    ],
)
def test_credit_card_detection_and_masking(det: PIIDetector, card: str):
    text = f"card={card}"
    findings = det.detect(text)
    assert any(f["type"] == "credit_card" for f in findings)
    masked = det.redact(text, replacement="auto")
    # ensure last 4 digits remain, everything before is masked
    digits = re.sub(r"\D", "", card)
    assert digits[-4:] in masked
    assert digits[:-4] not in masked


def test_iban_detection_and_masking(det: PIIDetector):
    iban = "NL91ABNA0417164300"  # canonical example
    text = f"My IBAN: {iban}"
    findings = det.detect(text)
    assert any(f["type"] == "iban" and f["value"] == iban for f in findings)
    masked = det.redact(text, replacement="auto")
    # keeps first 4 and last 4
    assert masked.count("NL91") == 1
    assert masked.endswith("4300")
    assert iban not in masked


# ------------------------------- JWT ----------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def test_jwt_detection_and_masking(det: PIIDetector):
    header = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64url(b'{"sub":"1234567890","name":"John Doe"}')
    signature = _b64url(b"signature")
    jwt = f"{header}.{payload}.{signature}"
    text = f"Authorization: Bearer {jwt}"
    findings = det.detect(text)
    assert any(f["type"] == "jwt" and f["value"] == jwt for f in findings)
    masked = det.redact(text, replacement="auto")
    # header preserved 3 chars, rest collapsed
    assert masked.count("….…") or masked.count(".…")  # header….… or hhh.….… formatting
    assert jwt not in masked


# ------------------------------- Phones -------------------------------------------------


@pytest.mark.parametrize(
    "phone",
    [
        "+31 6 1234 5678",  # NL mobile style
        "+1 (415) 555-2671",  # US style
        "020-123-4567",  # Generic
    ],
)
def test_phone_detection_and_masking(det: PIIDetector, phone: str):
    text = f"Call me at {phone}"
    findings = det.detect(text)
    assert any(f["type"] == "phone" for f in findings)
    masked = det.redact(text, replacement="auto")
    assert "***" in masked
    assert re.sub(r"\D", "", phone)[-4:] in masked


@pytest.mark.parametrize(
    "ticket_id",
    [
        # Bare digit blobs — most common false-positive source.
        "1234567",
        "12345678",
        "9876543210",
        # Internal ticket / change / order ids — value passed to the
        # validator after the regex match is just the digit run.
        "INC-1234567",
        "CHG-2024-12345",
        "JIRA-12345678",
        "ORDER-9876543",
        "TICKET-7654321",
    ],
)
def test_ticket_id_shaped_strings_are_not_phones(ticket_id):
    """Regression: any 7+ digit blob with no separators / parens / `+`
    prefix used to pass the phone validator. Operational workflows carry
    ticket ids, change numbers, and order refs in audit artifacts — and
    treating them as phone PII redacted the audit trail and blocked
    artifact.store with a 'PII on disallowed paths' error."""
    det = PIIDetector()
    findings = det.detect(ticket_id)
    flagged_phones = [f for f in findings if f["type"] == "phone"]
    assert not flagged_phones, (
        f"ticket-id-shaped value {ticket_id!r} was flagged as phone; " f"findings={findings}"
    )


# ------------------------------- IPs ----------------------------------------------------


def test_ipv4_public_detected_private_skipped_by_default():
    det = PIIDetector()  # redact_private_ips=False (default)
    text = "Public DNS 8.8.8.8; loopback 127.0.0.1"
    findings = det.detect(text)
    values = [f["value"] for f in findings if f["type"] == "ipv4"]
    assert "8.8.8.8" in values
    assert "127.0.0.1" not in values  # private skipped
    masked = det.redact(text, replacement="auto")
    assert "<IP>" in masked
    assert "8.8.8.8" not in masked


def test_private_ips_detected_when_enabled():
    det = PIIDetector(redact_private_ips=True)
    text = "Local: 192.168.1.10; Loopback: 127.0.0.1"
    findings = det.detect(text)
    vals = {f["value"] for f in findings if f["type"] == "ipv4"}
    assert "192.168.1.10" in vals and "127.0.0.1" in vals
    masked = det.redact(text, replacement="auto")
    assert "<IP>" in masked
    assert "192.168.1.10" not in masked
    assert "127.0.0.1" not in masked


def test_ipv6_detected_and_masked(det: PIIDetector):
    # Use a public IPv6 address (Google Public DNS)
    v6 = "2001:4860:4860::8888"
    text = f"v6={v6}"
    findings = det.detect(text)
    assert any(f["type"] == "ipv6" for f in findings)
    masked = det.redact(text, replacement="auto")
    assert "<IP>" in masked
    assert v6 not in masked


# ------------------------------- Tokens / Secrets --------------------------------------


@pytest.mark.parametrize(
    "label,value",
    [
        ("google_api_key", "AIza" + "A" * 35),
        ("github_token", "ghp_" + "a" * 36),
        ("slack_token", "xoxb-" + "1234567890abcdef"),
        ("sendgrid", "SG." + "A" * 16 + "." + "b" * 16),
        ("stripe_sk", "sk_live_" + "x" * 30),
        ("twilio", "SK" + "a" * 32),
        ("aws_access_key_id", "AKIA" + "A" * 16),
        ("api_key", "A0b1C2d3E4f5G6h7I8j9K0L1M2N3O4P5"),
    ],
)
def test_vendor_and_generic_tokens_masked_tail_hint(det: PIIDetector, label: str, value: str):
    text = f"{label} = {value}"
    findings = det.detect(text)
    assert (
        any(f["type"] == label for f in findings)
        or label == "api_key"
        and any(f["type"] == "api_key" for f in findings)
    )
    masked = det.redact(text, replacement="auto")
    # tail hint keeps first/last 4 chars
    assert value[:4] in masked and value[-4:] in masked
    assert value not in masked


def test_entropy_token_threshold_toggle():
    low_thr = PIIDetector(entropy_threshold_bits_per_char=1.0)
    high_thr = PIIDetector(entropy_threshold_bits_per_char=5.0)
    token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-"
    assert any(f["type"] == "entropy_token" for f in low_thr.detect(token))
    assert not any(f["type"] == "entropy_token" for f in high_thr.detect(token))


@pytest.mark.parametrize(
    "identifier",
    [
        "maintenance_completion_record",
        "maintenance_prep_record",
        "change_dryrun_record",
        "incident_triage_record",
        "callback_driven_maintenance",
        "wait_for_completion_callback",
        "snake_case_with_underscores",
    ],
)
def test_snake_case_identifiers_are_not_entropy_tokens(identifier):
    """Pure-lowercase snake_case identifiers (workflow names, artifact
    names, step ids) must NEVER be flagged as entropy_token secrets,
    even when their Shannon entropy crosses the threshold.

    Regression: a literal artifact name like 'maintenance_completion_record'
    has ~3.56 bits/char and tripped the entropy detector with the
    default 3.5 threshold. That false-positive blocked artifact.store
    calls on every wedge demo. The fix: real secrets overwhelmingly
    contain mixed case OR digits; pure [a-z_-] strings are identifiers.
    """
    det = PIIDetector()
    findings = det.detect(identifier)
    assert not any(f["type"] == "entropy_token" for f in findings), (
        f"snake_case identifier {identifier!r} was flagged as entropy_token; "
        f"findings={findings}"
    )


@pytest.mark.parametrize(
    "identifier",
    [
        # bare canonical UUID v4
        "3f30b8be-8859-4a76-8f0a-576582bc08a7",
        # UUID + step suffix — Saz artifact_id shape
        "3f30b8be-8859-4a76-8f0a-576582bc08a7_ansible_check_ansible",
        # UUID + colon-delimited step id — Saz idempotency key shape
        "3f30b8be-8859-4a76-8f0a-576582bc08a7:ansible_check",
        # uppercase hex UUID (some libraries emit this)
        "3F30B8BE-8859-4A76-8F0A-576582BC08A7",
        # UUID embedded inside a longer correlation handle
        "run-3f30b8be-8859-4a76-8f0a-576582bc08a7-attempt-2",
        # uuid.uuid4().hex — compact 32-char lowercase hex (callback_id,
        # idempotency keys, internal correlation tokens).
        "3f30b8be88594a768f0a576582bc08a7",
        # compact UUID inside a callback URL fragment
        "/webhooks/callback/3f30b8be88594a768f0a576582bc08a7",
    ],
)
def test_uuid_shaped_identifiers_are_not_entropy_or_api_key(identifier):
    """Run/step/artifact UUIDs surface everywhere in Saz audit logs and
    tool outputs. They are correlation handles, not secrets.

    Regression: the change-approval demo's ansible_run result includes an
    artifact_id of shape '<run_uuid>_<step_name>_ansible' that was tripping
    BOTH the api_key (32+ alnum) and entropy_token (24+ alnum) detectors
    via _validate_entropy. The fix: contains-UUID is a precise rejection
    because real API keys/tokens essentially never adopt the 8-4-4-4-12
    hex-with-hyphens layout.
    """
    det = PIIDetector()
    findings = det.detect(identifier)
    flagged_types = {f["type"] for f in findings}
    assert "entropy_token" not in flagged_types, (
        f"UUID-shaped identifier {identifier!r} was flagged as entropy_token; "
        f"findings={findings}"
    )
    assert "api_key" not in flagged_types, (
        f"UUID-shaped identifier {identifier!r} was flagged as api_key; " f"findings={findings}"
    )


@pytest.mark.parametrize(
    "secret",
    [
        # mixed case + digits — real-shape tokens
        "AKIAIOSFODNN7EXAMPLE",
        "AbCdEfGh1234IjKlMn5678OpQrSt",
        "ghp_1A2B3C4D5E6F7G8H9I0J",
        # has digits, no mixed case — still suspicious
        "abc123def456ghi789jkl012mno345",
    ],
)
def test_real_secret_shapes_still_flagged(secret):
    """The snake_case guard must NOT make the entropy detector blind
    to real-shape secrets: anything with mixed case or digits must
    still flow through the threshold check."""
    det = PIIDetector(entropy_threshold_bits_per_char=3.5)
    findings = det.detect(secret)
    # Note: some of these may match more specific patterns (api_key,
    # aws_access_key_id, github_token) and not entropy_token — that is
    # also acceptable; the demo-critical invariant is that *something*
    # detected them as PII / secret.
    assert findings, f"expected {secret!r} to surface at least one finding"


def test_kv_secret_value_extraction_and_redaction(det: PIIDetector):
    text = "password=SuperSecretToken12345"
    findings = det.detect(text)
    # Value must be the right-hand side (named group)
    assert any(f["type"] == "kv_secret" and f["value"] == "SuperSecretToken12345" for f in findings)
    masked = det.redact(text, replacement="auto")
    # entire span replaced by tail-hint mask; original secret removed
    assert "SuperSecretToken12345" not in masked
    assert "password=" not in masked  # replaced span includes the key-value


# ------------------------------- Redaction behavior ------------------------------------


def test_literal_replacement(det: PIIDetector):
    text = "Email: user@site.com CC: 4111 1111 1111 1111"
    red = det.redact(text, replacement="[X]")
    assert "[X]" in red
    assert "user@site.com" not in red
    assert "4111" not in red  # all masked literally, no tail hint


def test_no_matches_returns_verbatim(det: PIIDetector):
    text = "Harmless string."
    assert det.redact(text) == text
    assert det.detect(text) == []


# ------------------------------- Nested dict scan/redact -------------------------------


def test_scan_dict_paths(det: PIIDetector):
    data = {
        "user": {"email": "a@b.com", "name": "Alice"},
        "contact": {"phone": "+31 6 1234 5678"},
        "nested": [{"iban": "NL91ABNA0417164300"}, {"notes": "ok"}],
    }
    paths = det.scan_dict(data)
    assert set(paths) >= {"user.email", "contact.phone", "nested[0].iban"}


def test_redact_dict_structure_preserved(det: PIIDetector):
    data = {
        "user": {"email": "a@b.com", "age": 33},
        "list": ["Call +31 6 1234 5678", 42, {"cc": "4111 1111 1111 1111"}],
    }
    red = det.redact_dict(data, replacement="auto")
    # structure unchanged
    assert isinstance(red, dict)
    assert isinstance(red["user"], dict)
    assert isinstance(red["list"], list)
    # redactions applied
    assert "a@b.com" not in str(red)
    assert "4111 1111 1111 1111" not in str(red)
    # age and non-PII untouched
    assert red["user"]["age"] == 33
    assert red["list"][1] == 42


# ------------------------------- Custom patterns & filtering ---------------------------


def test_add_custom_pattern_with_custom_masker(det: PIIDetector):
    det.add_custom_pattern(
        "animal",
        r"\bcatdog\b",
        masker=lambda _v: "<ANIMAL>",
    )
    text = "strange token catdog appears"
    findings = det.detect(text)
    assert any(f["type"] == "animal" and f["value"] == "catdog" for f in findings)
    masked = det.redact(text, replacement="auto")
    assert "<ANIMAL>" in masked
    assert "catdog" not in masked


def test_enabled_detectors_filters():
    det = PIIDetector(enabled_detectors=["email"])
    text = "user@site.com and 4111 1111 1111 1111"
    findings = det.detect(text)
    types = {f["type"] for f in findings}
    assert types == {"email"}
    # Ensure non-enabled detectors are ignored
    assert not any(f["type"] == "credit_card" for f in findings)


def test_large_input_is_finite(det: PIIDetector):
    blob = ("A" * 10_000) + " user@example.com " + ("B" * 10_000)
    out = det.redact(blob, replacement="auto")
    assert "user@example.com" not in out
