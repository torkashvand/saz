"""Error categorization and human-readable message generation for improved UX."""

import re
import urllib.parse
from enum import Enum
from typing import Any


class ErrorCategory(str, Enum):
    """Categories of errors for UI presentation."""

    MISSING_CREDENTIAL = "missing_credential"
    HTTP_ERROR = "http_error"
    VALIDATION_ERROR = "validation_error"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    PERMISSION_DENIED = "permission_denied"
    INTERNAL_ERROR = "internal_error"
    USER_ERROR = "user_error"
    UNKNOWN = "unknown"


class RemediationAction(str, Enum):
    """Suggested actions to remediate errors."""

    CONFIGURE_CREDENTIAL = "configure_credential"
    CHECK_API_STATUS = "check_api_status"
    FIX_INPUT_DATA = "fix_input_data"
    RETRY = "retry"
    CONTACT_SUPPORT = "contact_support"
    CHECK_PERMISSIONS = "check_permissions"
    VIEW_LOGS = "view_logs"


def categorize_error(error_dict: dict[str, Any] | None) -> ErrorCategory:
    """
    Categorize an error for UI presentation.

    Args:
        error_dict: Error dictionary from Step.error or Run.error

    Returns:
        ErrorCategory enum value
    """
    if not error_dict:
        return ErrorCategory.UNKNOWN

    error_type = error_dict.get("type", "")
    error_message = error_dict.get("message", "").lower()
    traceback = error_dict.get("traceback", "").lower()

    # Missing credential
    if "credential" in error_message and (
        "not found" in error_message or "missing" in error_message
    ):
        return ErrorCategory.MISSING_CREDENTIAL
    if "credentialnotfounderror" in error_type.lower():
        return ErrorCategory.MISSING_CREDENTIAL

    # HTTP errors (check for status codes or http-related keywords)
    if "http" in error_type.lower() or "httperror" in error_type.lower():
        # Check for specific HTTP status codes in message
        if any(code in error_message for code in ["401", "403"]):
            return ErrorCategory.PERMISSION_DENIED
        if "429" in error_message or "rate limit" in error_message:
            return ErrorCategory.RATE_LIMIT
        if any(code in error_message for code in ["400", "422"]):
            return ErrorCategory.VALIDATION_ERROR
        if any(code in error_message for code in ["500", "502", "503", "504"]):
            return ErrorCategory.HTTP_ERROR
        # Generic HTTP error
        return ErrorCategory.HTTP_ERROR

    # Timeout errors
    if "timeout" in error_type.lower() or "timeout" in error_message:
        return ErrorCategory.TIMEOUT

    # Rate limiting
    if "rate" in error_message and "limit" in error_message:
        return ErrorCategory.RATE_LIMIT
    if "too many requests" in error_message:
        return ErrorCategory.RATE_LIMIT

    # Permission/authorization errors
    if any(
        word in error_message
        for word in ["forbidden", "unauthorized", "permission denied", "access denied"]
    ):
        return ErrorCategory.PERMISSION_DENIED

    # Validation errors
    if "validation" in error_type.lower() or "validation" in error_message:
        return ErrorCategory.VALIDATION_ERROR
    if any(
        word in error_message for word in ["invalid", "required field", "missing field", "must be"]
    ):
        return ErrorCategory.VALIDATION_ERROR
    if "valueerror" in error_type.lower() or "typeerror" in error_type.lower():
        return ErrorCategory.VALIDATION_ERROR

    # User input errors
    if "userinput" in error_type.lower() or "user input" in error_message:
        return ErrorCategory.USER_ERROR

    # Internal/platform errors
    if any(word in error_type.lower() for word in ["database", "config", "internal"]):
        return ErrorCategory.INTERNAL_ERROR

    return ErrorCategory.UNKNOWN


def get_remediation_actions(category: ErrorCategory) -> list[RemediationAction]:
    """
    Get suggested remediation actions based on error category.

    Args:
        category: Error category

    Returns:
        List of remediation actions
    """
    actions_map = {
        ErrorCategory.MISSING_CREDENTIAL: [
            RemediationAction.CONFIGURE_CREDENTIAL,
            RemediationAction.RETRY,
        ],
        ErrorCategory.HTTP_ERROR: [
            RemediationAction.CHECK_API_STATUS,
            RemediationAction.VIEW_LOGS,
            RemediationAction.RETRY,
        ],
        ErrorCategory.VALIDATION_ERROR: [
            RemediationAction.FIX_INPUT_DATA,
            RemediationAction.VIEW_LOGS,
        ],
        ErrorCategory.TIMEOUT: [
            RemediationAction.RETRY,
            RemediationAction.CHECK_API_STATUS,
        ],
        ErrorCategory.RATE_LIMIT: [
            RemediationAction.RETRY,
            RemediationAction.CHECK_API_STATUS,
        ],
        ErrorCategory.PERMISSION_DENIED: [
            RemediationAction.CHECK_PERMISSIONS,
            RemediationAction.CONFIGURE_CREDENTIAL,
        ],
        ErrorCategory.USER_ERROR: [
            RemediationAction.FIX_INPUT_DATA,
            RemediationAction.VIEW_LOGS,
        ],
        ErrorCategory.INTERNAL_ERROR: [
            RemediationAction.CONTACT_SUPPORT,
            RemediationAction.VIEW_LOGS,
        ],
        ErrorCategory.UNKNOWN: [
            RemediationAction.VIEW_LOGS,
            RemediationAction.CONTACT_SUPPORT,
        ],
    }

    return actions_map.get(category, [RemediationAction.VIEW_LOGS])


def generate_error_message(
    category: ErrorCategory,
    error_dict: dict[str, Any] | None,
    step_name: str | None = None,
) -> str:
    """
    Generate a human-readable error message.

    Args:
        category: Error category
        error_dict: Error dictionary
        step_name: Optional step name for context

    Returns:
        Human-readable error message
    """
    if not error_dict:
        return "An unexpected error occurred"

    error_message = error_dict.get("message", "")

    if category == ErrorCategory.MISSING_CREDENTIAL:
        # Extract credential name if possible
        cred_name = extract_credential_name(error_message)
        if cred_name:
            return f"Missing credential: {cred_name} is not configured"
        return "Required credential is missing or not configured"

    elif category == ErrorCategory.HTTP_ERROR:
        # Extract HTTP status and endpoint if possible
        status = extract_http_status(error_message)
        endpoint = extract_api_endpoint(error_message)

        if status and endpoint:
            return f"HTTP {status} from {endpoint}"
        elif status:
            return f"HTTP {status} error from external API"
        elif endpoint:
            return f"HTTP error from {endpoint}"
        return "External API request failed"

    elif category == ErrorCategory.VALIDATION_ERROR:
        # Extract field name if possible
        field = extract_field_name(error_message)
        if field:
            return f"Validation error: required field '{field}' is missing or invalid"
        return f"Validation error: {error_message[:150]}"

    elif category == ErrorCategory.TIMEOUT:
        # Extract timeout duration if possible
        duration = extract_timeout_duration(error_message)
        if duration:
            return f"Request timed out after {duration}"
        return "Request timed out"

    elif category == ErrorCategory.RATE_LIMIT:
        # Extract retry-after if possible
        retry_after = extract_retry_after(error_message)
        if retry_after:
            return f"Rate limit exceeded. Retry after {retry_after} seconds"
        return "Rate limit exceeded"

    elif category == ErrorCategory.PERMISSION_DENIED:
        # Extract resource if possible
        resource = extract_resource(error_message)
        if resource:
            return f"Permission denied: insufficient access to {resource}"
        return "Permission denied: insufficient access rights"

    elif category == ErrorCategory.USER_ERROR:
        return f"Invalid input: {error_message[:150]}"

    elif category == ErrorCategory.INTERNAL_ERROR:
        # Don't leak internal details to end users
        return "Internal platform error occurred"

    else:
        # Generic fallback - limit message length
        return error_message[:200] if error_message else "An unexpected error occurred"


def extract_credential_name(message: str) -> str | None:
    """Extract credential name from error message."""
    # Pattern: "credential 'name'" or "credential: name" or "'name' not found"
    patterns = [
        r"credential ['\"]([a-zA-Z0-9_\-]+)['\"]",
        r"credential:\s*([a-zA-Z0-9_\-]+)",
        r"['\"]([a-zA-Z0-9_\-]+)['\"].*not found",
        r"([a-zA-Z0-9_\-]+).*not configured",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_http_status(message: str) -> str | None:
    """Extract HTTP status code from error message."""
    # Pattern: "HTTP 500" or "status: 404" or "error 401"
    patterns = [
        r"HTTP\s+(\d{3})",
        r"status:?\s*(\d{3})",
        r"error\s+(\d{3})",
        r"(\d{3})\s+error",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_api_endpoint(message: str) -> str | None:
    """Extract API endpoint from error message and sanitize."""
    # Pattern: URLs or API paths
    url_pattern = r"https?://([a-zA-Z0-9\-\.]+(?:/[a-zA-Z0-9\-_/]*)?)"
    match = re.search(url_pattern, message)

    if match:
        url = match.group(0)
        # Sanitize: remove query params and keep only domain + path
        parsed = urllib.parse.urlparse(url)
        sanitized = f"{parsed.netloc}{parsed.path}"
        # Truncate long paths
        if len(sanitized) > 50:
            sanitized = sanitized[:47] + "..."
        return sanitized

    return None


def extract_field_name(message: str) -> str | None:
    """Extract field name from validation error message."""
    # Pattern: "field 'name'" or "'name' is required" or "missing field: name"
    patterns = [
        r"field ['\"]([a-zA-Z0-9_\-]+)['\"]",
        r"['\"]([a-zA-Z0-9_\-]+)['\"].*required",
        r"missing.*?['\"]([a-zA-Z0-9_\-]+)['\"]",
        r"invalid.*?['\"]([a-zA-Z0-9_\-]+)['\"]",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_timeout_duration(message: str) -> str | None:
    """Extract timeout duration from error message."""
    # Pattern: "30 seconds" or "5s" or "2000ms"
    patterns = [
        r"(\d+)\s*seconds?",
        r"(\d+)\s*s\b",
        r"(\d+)\s*ms\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            value = match.group(1)
            if "ms" in match.group(0):
                return f"{value}ms"
            return f"{value}s"

    return None


def extract_retry_after(message: str) -> str | None:
    """Extract retry-after duration from rate limit error."""
    # Pattern: "retry after 30 seconds" or "retry in 60s"
    patterns = [
        r"retry.*?(\d+)\s*seconds?",
        r"retry.*?(\d+)\s*s\b",
        r"wait\s*(\d+)\s*seconds?",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_resource(message: str) -> str | None:
    """Extract resource name from permission error message."""
    # Pattern: "access to 'resource'" or "permission denied for resource"
    patterns = [
        r"access.*?['\"]([a-zA-Z0-9_\-/]+)['\"]",
        r"permission.*?['\"]([a-zA-Z0-9_\-/]+)['\"]",
        r"denied.*?['\"]([a-zA-Z0-9_\-/]+)['\"]",
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)

    return None
