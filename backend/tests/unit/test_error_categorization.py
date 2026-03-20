"""Tests for error categorization and enrichment."""

from saz.domain.error_categorization import (
    ErrorCategory,
    RemediationAction,
    categorize_error,
    extract_api_endpoint,
    extract_credential_name,
    extract_field_name,
    extract_http_status,
    generate_error_message,
    get_remediation_actions,
)

# --- Error categorization ---


def test_categorize_missing_credential():
    """Test categorizing missing credential errors."""
    error_dict = {
        "type": "CredentialNotFoundError",
        "message": "Credential 'ivanti_api_token' not found in database",
    }
    assert categorize_error(error_dict) == ErrorCategory.MISSING_CREDENTIAL


def test_categorize_http_error_500():
    """Test categorizing HTTP 500 errors."""
    error_dict = {"type": "HTTPError", "message": "HTTP 500 from api.example.com/tickets"}
    assert categorize_error(error_dict) == ErrorCategory.HTTP_ERROR


def test_categorize_permission_denied():
    """Test categorizing permission denied errors."""
    error_dict = {
        "type": "HTTPError",
        "message": "HTTP 403 Forbidden: insufficient permissions",
    }
    assert categorize_error(error_dict) == ErrorCategory.PERMISSION_DENIED


def test_categorize_rate_limit():
    """Test categorizing rate limit errors."""
    error_dict = {
        "type": "HTTPError",
        "message": "HTTP 429 Too Many Requests: rate limit exceeded",
    }
    assert categorize_error(error_dict) == ErrorCategory.RATE_LIMIT


def test_categorize_validation_error():
    """Test categorizing validation errors."""
    error_dict = {"type": "ValidationError", "message": "required field 'ticket_id' is missing"}
    assert categorize_error(error_dict) == ErrorCategory.VALIDATION_ERROR


def test_categorize_timeout():
    """Test categorizing timeout errors."""
    error_dict = {"type": "TimeoutError", "message": "Request timed out after 30 seconds"}
    assert categorize_error(error_dict) == ErrorCategory.TIMEOUT


def test_categorize_unknown():
    """Test categorizing unknown errors."""
    error_dict = {"type": "UnexpectedError", "message": "Something went wrong"}
    assert categorize_error(error_dict) == ErrorCategory.UNKNOWN


# --- Remediation actions ---


def test_missing_credential_actions():
    """Test remediation actions for missing credential."""
    actions = get_remediation_actions(ErrorCategory.MISSING_CREDENTIAL)
    assert RemediationAction.CONFIGURE_CREDENTIAL in actions
    assert RemediationAction.RETRY in actions


def test_http_error_actions():
    """Test remediation actions for HTTP errors."""
    actions = get_remediation_actions(ErrorCategory.HTTP_ERROR)
    assert RemediationAction.CHECK_API_STATUS in actions
    assert RemediationAction.VIEW_LOGS in actions


def test_validation_error_actions():
    """Test remediation actions for validation errors."""
    actions = get_remediation_actions(ErrorCategory.VALIDATION_ERROR)
    assert RemediationAction.FIX_INPUT_DATA in actions
    assert RemediationAction.VIEW_LOGS in actions


# --- Error message generation ---


def test_generate_missing_credential_message():
    """Test generating message for missing credential."""
    error_dict = {
        "type": "CredentialNotFoundError",
        "message": "Credential 'ivanti_api_token' not found",
    }
    message = generate_error_message(ErrorCategory.MISSING_CREDENTIAL, error_dict)
    assert "ivanti_api_token" in message
    assert "not configured" in message.lower()


def test_generate_http_error_message():
    """Test generating message for HTTP error."""
    error_dict = {
        "type": "HTTPError",
        "message": "HTTP 500 from https://api.example.com/tickets",
    }
    message = generate_error_message(ErrorCategory.HTTP_ERROR, error_dict)
    assert "500" in message
    assert "api.example.com" in message


def test_generate_validation_error_message():
    """Test generating message for validation error."""
    error_dict = {"type": "ValidationError", "message": "required field 'ticket_id' is missing"}
    message = generate_error_message(ErrorCategory.VALIDATION_ERROR, error_dict)
    assert "ticket_id" in message
    assert "validation" in message.lower()


# --- Extraction helpers ---


def test_extract_credential_name():
    """Test extracting credential name from error message."""
    message = "Credential 'ivanti_api_token' not found in database"
    assert extract_credential_name(message) == "ivanti_api_token"


def test_extract_http_status():
    """Test extracting HTTP status code."""
    message = "HTTP 500 Internal Server Error"
    assert extract_http_status(message) == "500"


def test_extract_api_endpoint():
    """Test extracting and sanitizing API endpoint."""
    message = "Error from https://api.example.com/v1/tickets?token=secret"
    endpoint = extract_api_endpoint(message)
    assert endpoint == "api.example.com/v1/tickets"
    assert "token" not in endpoint
    assert "secret" not in endpoint


def test_extract_field_name():
    """Test extracting field name from validation error."""
    message = "required field 'ticket_id' is missing"
    assert extract_field_name(message) == "ticket_id"


def test_extract_credential_name_none():
    """Test that None is returned when no credential name found."""
    message = "Some generic error"
    assert extract_credential_name(message) is None


def test_extract_http_status_none():
    """Test that None is returned when no HTTP status found."""
    message = "Some generic error"
    assert extract_http_status(message) is None
