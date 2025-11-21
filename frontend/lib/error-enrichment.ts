/**
 * Error enrichment utilities for Run Details UX.
 *
 * These utilities transform raw backend error data into human-readable
 * error summaries with categorization and suggested actions.
 */

import type { ErrorSummary, ErrorCategory, RemediationAction } from './types-enhanced';
import type { RunDetailResponse, RunStep } from './types';

/**
 * Build error summary from run data.
 *
 * This is a client-side fallback for when the backend doesn't provide
 * error_summary. Ideally, the backend should do this categorization.
 */
export function buildErrorSummary(run: RunDetailResponse): ErrorSummary | null {
  // If backend already provided error_summary, use it
  if (run.error_summary) {
    return run.error_summary as ErrorSummary;
  }

  // No error to summarize
  if (!run.error && run.status !== 'failed') {
    return null;
  }

  // Find the failing step
  const failedStep = run.steps?.find((s) => s.status === 'failed');
  const error = run.error || failedStep?.error;

  if (!error) {
    // Failed status but no error object - generic message
    return {
      message: 'Run failed without detailed error information',
      category: 'unknown',
      failed_step_number: failedStep?.number || null,
      failed_step_name: failedStep?.name || null,
      remediation_actions: ['view_logs', 'contact_support'],
      technical_details: {},
    };
  }

  // Categorize error
  const category = categorizeError(error);
  const message = buildErrorMessage(error, category, failedStep);
  const actions = suggestRemediationActions(category, error);

  return {
    message,
    category,
    failed_step_number: failedStep?.number || null,
    failed_step_name: failedStep?.name || null,
    remediation_actions: actions,
    technical_details: {
      error_type: error.type || typeof error === 'string' ? 'string' : 'object',
      raw_error: error,
      ...(error.http_status && { http_status: error.http_status }),
      ...(error.api_endpoint && { api_endpoint: error.api_endpoint }),
    },
  };
}

/**
 * Categorize error based on its structure and content.
 */
function categorizeError(error: any): ErrorCategory {
  const errorMsg = typeof error === 'string' ? error : error.message || '';
  const errorType = error.type || '';

  // Check for credential errors
  if (
    errorMsg.toLowerCase().includes('credential') ||
    errorMsg.toLowerCase().includes('not found') ||
    errorType.toLowerCase().includes('credential')
  ) {
    return 'missing_credential';
  }

  // Check for HTTP errors
  if (error.http_status || errorType.toLowerCase().includes('http')) {
    const status = error.http_status;
    if (status >= 500) return 'http_error';
    if (status === 429) return 'rate_limit';
    if (status === 401 || status === 403) return 'permission_denied';
    return 'http_error';
  }

  // Check for timeout
  if (
    errorMsg.toLowerCase().includes('timeout') ||
    errorType.toLowerCase().includes('timeout')
  ) {
    return 'timeout';
  }

  // Check for validation errors
  if (
    errorMsg.toLowerCase().includes('validation') ||
    errorMsg.toLowerCase().includes('invalid') ||
    errorType.toLowerCase().includes('validation')
  ) {
    return 'validation_error';
  }

  // Check for permission errors
  if (
    errorMsg.toLowerCase().includes('permission') ||
    errorMsg.toLowerCase().includes('forbidden') ||
    errorMsg.toLowerCase().includes('unauthorized')
  ) {
    return 'permission_denied';
  }

  // Check for rate limiting
  if (
    errorMsg.toLowerCase().includes('rate limit') ||
    errorMsg.toLowerCase().includes('too many requests')
  ) {
    return 'rate_limit';
  }

  // Default to internal error
  return 'internal_error';
}

/**
 * Build human-readable error message.
 */
function buildErrorMessage(
  error: any,
  category: ErrorCategory,
  failedStep?: RunStep
): string {
  const errorMsg = typeof error === 'string' ? error : error.message || 'Unknown error';

  // Extract credential name from error message
  if (category === 'missing_credential') {
    const match = errorMsg.match(/credential[:\s]+['"]?(\w+)['"]?/i);
    const credName = match ? match[1] : 'required credential';
    return `Missing credential: "${credName}" is not configured`;
  }

  // HTTP errors
  if (category === 'http_error') {
    const status = error.http_status || 'unknown';
    const endpoint = error.api_endpoint || 'API';
    return `HTTP ${status} error from ${endpoint}`;
  }

  // Rate limiting
  if (category === 'rate_limit') {
    return 'API rate limit exceeded. Please wait before retrying';
  }

  // Timeout
  if (category === 'timeout') {
    return 'Operation timed out. The request took too long to complete';
  }

  // Validation error
  if (category === 'validation_error') {
    return `Validation error: ${errorMsg}`;
  }

  // Permission denied
  if (category === 'permission_denied') {
    return 'Permission denied. Check your credentials or access rights';
  }

  // Generic fallback
  return errorMsg.length > 150 ? errorMsg.slice(0, 150) + '...' : errorMsg;
}

/**
 * Suggest remediation actions based on error category.
 */
function suggestRemediationActions(
  category: ErrorCategory,
  error: any
): RemediationAction[] {
  switch (category) {
    case 'missing_credential':
      return ['configure_credential', 'view_logs'];

    case 'http_error':
      const status = error.http_status;
      if (status >= 500) {
        return ['check_api_status', 'retry', 'view_logs'];
      }
      return ['view_logs', 'check_api_status'];

    case 'rate_limit':
      return ['retry', 'view_logs'];

    case 'timeout':
      return ['retry', 'view_logs'];

    case 'validation_error':
    case 'user_error':
      return ['fix_input_data', 'view_logs'];

    case 'permission_denied':
      return ['check_permissions', 'configure_credential', 'view_logs'];

    case 'internal_error':
    case 'unknown':
    default:
      return ['view_logs', 'contact_support', 'retry'];
  }
}