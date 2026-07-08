// Unified error handling for Saz GUI

export type ErrorKind =
  | 'validation' // 400, 422 - with field-level errors
  | 'auth' // 401 - not authenticated
  | 'permission' // 403 - not authorized
  | 'not_found' // 404
  | 'conflict' // 409
  | 'rate_limit' // 429
  | 'server' // 500-599
  | 'network' // Network/timeout errors
  | 'unknown'; // Unexpected/unclassified

export interface ValidationError {
  field: string;
  message: string;
}

export interface AppError {
  kind: ErrorKind;
  status?: number;
  code?: string; // Backend error code if available
  message: string; // User-facing message
  validationErrors?: ValidationError[];
  details?: unknown; // Structured details from backend
  raw?: unknown; // Original error (for logging/debugging)
}

/**
 * Default user-facing messages for each error kind
 */
const ERROR_MESSAGES: Record<ErrorKind, string> = {
  validation: 'Please check your input and try again',
  auth: 'You need to log in to continue',
  permission: "You don't have permission to perform this action",
  not_found: 'The requested resource was not found',
  conflict: 'This operation conflicts with existing data',
  rate_limit: 'Too many requests. Please slow down and try again',
  server: 'Something went wrong on our end. Please try again',
  network: 'Connection issue. Please check your network and try again',
  unknown: 'An unexpected error occurred',
};

/**
 * Map HTTP status to error kind
 */
function statusToKind(status: number): ErrorKind {
  if (status === 400 || status === 422) return 'validation';
  if (status === 401) return 'auth';
  if (status === 403) return 'permission';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 429) return 'rate_limit';
  if (status >= 500) return 'server';
  return 'unknown';
}

/**
 * Extract validation errors from common backend shapes
 */
function extractValidationErrors(data: any): ValidationError[] | undefined {
  // FastAPI validation error shape
  if (Array.isArray(data?.detail)) {
    return data.detail
      .filter((err: any) => err.loc && err.msg)
      .map((err: any) => ({
        field: Array.isArray(err.loc) ? err.loc.join('.') : String(err.loc),
        message: err.msg,
      }));
  }

  // Generic {field: message} shape
  if (data?.errors && typeof data.errors === 'object') {
    return Object.entries(data.errors).map(([field, message]) => ({
      field,
      message: String(message),
    }));
  }

  return undefined;
}

/**
 * Create AppError from HTTP response
 */
export async function fromHttpError(
  response: Response,
  fallbackMessage?: string,
): Promise<AppError> {
  const status = response.status;
  const kind = statusToKind(status);

  let data: any;
  let message = fallbackMessage || ERROR_MESSAGES[kind];
  let code: string | undefined;
  let validationErrors: ValidationError[] | undefined;

  try {
    const text = await response.text();
    if (text) {
      data = JSON.parse(text);

      // Extract backend message if available and safe
      if (typeof data?.message === 'string') {
        message = data.message;
      } else if (typeof data?.detail === 'string') {
        message = data.detail;
      }

      // Extract error code
      if (typeof data?.code === 'string') {
        code = data.code;
      }

      // Extract validation errors
      validationErrors = extractValidationErrors(data);
    }
  } catch {
    // Failed to parse response, use defaults
  }

  return {
    kind,
    status,
    code,
    message,
    validationErrors,
    details: data,
    raw: response,
  };
}

/**
 * Create AppError from network/timeout error
 */
export function fromNetworkError(error: unknown): AppError {
  const message =
    error instanceof Error && error.name === 'AbortError'
      ? 'Request timed out. Please try again'
      : ERROR_MESSAGES.network;

  return {
    kind: 'network',
    message,
    raw: error,
  };
}

/**
 * Create AppError from unknown error
 */
export function fromUnknownError(error: unknown): AppError {
  let message = ERROR_MESSAGES.unknown;

  if (error instanceof Error) {
    message = error.message || message;
  }

  return {
    kind: 'unknown',
    message,
    raw: error,
  };
}

/**
 * Get validation error for a specific field
 */
export function getFieldError(
  error: AppError | null | undefined,
  fieldName: string,
): string | undefined {
  return error?.validationErrors?.find((e) => e.field === fieldName)?.message;
}
