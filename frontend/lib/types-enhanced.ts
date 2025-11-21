/**
 * Enhanced type definitions for improved Run Details UX.
 *
 * These types extend the base API types to support:
 * - Human-readable error summaries
 * - Categorized failure reasons
 * - Step-level failure context
 * - Suggested remediation actions
 */

import type { RunDetailResponse, RunStep, Event, StepStatus } from './types';

// ========== Error Handling Types ==========

export type ErrorCategory =
  | 'missing_credential'
  | 'http_error'
  | 'validation_error'
  | 'timeout'
  | 'rate_limit'
  | 'permission_denied'
  | 'internal_error'
  | 'user_error'
  | 'unknown';

export type RemediationAction =
  | 'configure_credential'
  | 'check_api_status'
  | 'fix_input_data'
  | 'retry'
  | 'contact_support'
  | 'check_permissions'
  | 'view_logs';

export interface ErrorSummary {
  // Human-readable summary (one line)
  message: string;

  // Category for UI presentation
  category: ErrorCategory;

  // Step where error occurred (null for run-level errors)
  failed_step_number: number | null;
  failed_step_name: string | null;

  // Suggested actions
  remediation_actions: RemediationAction[];

  // Technical details (hidden by default)
  technical_details: {
    error_type?: string;
    stack_trace?: string;
    raw_error?: any;
    http_status?: number;
    api_endpoint?: string;
  };
}

// ========== Enhanced Run Types ==========

export interface EnhancedRunDetail extends RunDetailResponse {
  // Human-friendly error summary (if failed)
  error_summary?: ErrorSummary;

  // Triggered by user or system
  triggered_by?: {
    type: 'user' | 'system' | 'schedule' | 'webhook';
    user_id?: string;
    user_name?: string;
  };

  // Enhanced metadata
  metadata?: {
    total_steps: number;
    succeeded_steps: number;
    failed_steps: number;
    running_steps: number;
    skipped_steps: number;
  };
}

export interface EnhancedRunStep extends RunStep {
  // Short description for non-technical users
  description?: string;

  // Human-readable failure reason (if failed)
  failure_reason?: string;

  // Categorized error
  error_category?: ErrorCategory;
}

// ========== UI State Types ==========

export interface RunHeaderData {
  flow_name: string;
  run_id: string;
  status: StepStatus;
  triggered_by: string;
  started_at: string;
  duration_ms: number | null;

  // Summary stats
  total_steps: number;
  succeeded_steps: number;
  failed_steps: number;
  running_steps: number;

  // Error info (if failed)
  error_summary?: ErrorSummary;
}

export interface StepCardData {
  id: string;
  number: number;
  name: string;
  description?: string;
  status: StepStatus;
  duration_ms?: number;

  // Expand/collapse state
  show_input_output: boolean;
  show_logs: boolean;

  // Data
  input?: any;
  output?: any;

  // Error info
  failure_reason?: string;
  error_category?: ErrorCategory;
}

export interface TimelineViewConfig {
  show_logs_panel: boolean;
  selected_step_id: string | null;
  logs_filter_level: 'all' | 'info' | 'warning' | 'error';
  logs_search_query: string;
}

// ========== Backend Data Shape Recommendations ==========

/**
 * Recommended shape for GET /api/v1/runs/{id} response.
 *
 * The backend should provide:
 * 1. High-level error summary with human-readable message
 * 2. Categorized error type
 * 3. Suggested remediation actions
 * 4. Aggregated metadata (step counts)
 * 5. Per-step failure reasons
 */
export interface RecommendedRunDetailResponse {
  // Existing fields
  id: string;
  flow_id: string;
  flow_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'suspended';
  planner_mode: string;
  payload: Record<string, any>;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  total_tokens: number;
  total_cost_usd: number;

  // NEW: Triggered by
  triggered_by?: {
    type: 'user' | 'system' | 'schedule' | 'webhook';
    user_id?: string;
    user_name?: string;
  };

  // NEW: Aggregated metadata (note: field name is run_metadata in API to avoid SQLAlchemy reserved word)
  run_metadata: {
    total_steps: number;
    succeeded_steps: number;
    failed_steps: number;
    running_steps: number;
    skipped_steps: number;
  };

  // NEW: Human-readable error summary
  error_summary?: {
    message: string; // e.g., "Missing credential: ivanti_api_token is not configured"
    category: ErrorCategory;
    failed_step_number: number | null;
    failed_step_name: string | null;
    remediation_actions: RemediationAction[];
    technical_details: {
      error_type?: string;
      stack_trace?: string;
      raw_error?: any;
      http_status?: number;
      api_endpoint?: string;
    };
  };

  // Existing steps array, enhanced
  steps: Array<{
    id: string;
    number: number;
    name: string;
    step_type?: string;
    description?: string; // NEW: Short, user-friendly description
    status: 'queued' | 'running' | 'suspended' | 'failed' | 'completed';
    start_ts?: string;
    end_ts?: string;
    duration_ms?: number;
    retry_count: number;
    tokens?: number;
    cost_usd?: number;
    input?: any;
    output?: any;
    error?: any;
    failure_reason?: string; // NEW: e.g., "HTTP 500 from inventory API"
    error_category?: ErrorCategory; // NEW
  }>;

  artifacts?: string[];
}

/**
 * Example backend error categorization logic:
 *
 * ```python
 * def categorize_error(error: Exception) -> ErrorCategory:
 *     if isinstance(error, CredentialNotFoundError):
 *         return "missing_credential"
 *     elif isinstance(error, requests.HTTPError):
 *         if error.response.status_code >= 500:
 *             return "http_error"
 *         elif error.response.status_code == 429:
 *             return "rate_limit"
 *         elif error.response.status_code in (401, 403):
 *             return "permission_denied"
 *     elif isinstance(error, ValidationError):
 *         return "validation_error"
 *     elif isinstance(error, TimeoutError):
 *         return "timeout"
 *     else:
 *         return "internal_error"
 *
 * def generate_error_summary(run: Run, failed_step: Step | None) -> ErrorSummary:
 *     category = categorize_error(run.error or failed_step.error)
 *
 *     # Generate human-readable message
 *     if category == "missing_credential":
 *         cred_name = extract_credential_name(run.error)
 *         message = f"Missing credential: {cred_name} is not configured"
 *         actions = ["configure_credential"]
 *     elif category == "http_error":
 *         status = run.error.response.status_code
 *         endpoint = run.error.request.url
 *         message = f"HTTP {status} from {endpoint}"
 *         actions = ["check_api_status", "retry", "view_logs"]
 *     # ... etc
 *
 *     return ErrorSummary(
 *         message=message,
 *         category=category,
 *         failed_step_number=failed_step.number if failed_step else None,
 *         failed_step_name=failed_step.name if failed_step else None,
 *         remediation_actions=actions,
 *         technical_details={
 *             "error_type": type(run.error).__name__,
 *             "stack_trace": traceback.format_exc(),
 *             "raw_error": str(run.error),
 *             ...
 *         }
 *     )
 * ```
 */
