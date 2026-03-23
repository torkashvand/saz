// Optional Sentry integration for error tracking

import type { AppError } from './errors';

// Type definitions for Sentry (will be installed separately)
type SentryScope = any;
type SentryLevel = 'fatal' | 'error' | 'warning' | 'log' | 'info' | 'debug';

const SENTRY_DSN = process.env.NEXT_PUBLIC_SENTRY_DSN;
const SENTRY_ENABLED = process.env.NEXT_PUBLIC_SENTRY_ENABLED === 'true';
const ENVIRONMENT = process.env.NEXT_PUBLIC_ENVIRONMENT || 'development';

let Sentry: any = null;

/**
 * Lazy load Sentry only if enabled
 */
async function loadSentry() {
  if (!SENTRY_ENABLED || !SENTRY_DSN) {
    return null;
  }

  if (Sentry) {
    return Sentry;
  }

  try {
    Sentry = await import(/* webpackIgnore: true */ '@sentry/nextjs');
    return Sentry;
  } catch (error) {
    console.warn('[Monitoring] Failed to load Sentry:', error);
    return null;
  }
}

/**
 * Initialize Sentry only if configured
 */
export async function initSentry() {
  if (!SENTRY_ENABLED || !SENTRY_DSN) {
    console.info('[Monitoring] Sentry not configured, error tracking disabled');
    return;
  }

  try {
    const sentry = await loadSentry();
    if (!sentry) return;

    sentry.init({
      dsn: SENTRY_DSN,
      environment: ENVIRONMENT,

      // Performance monitoring
      tracesSampleRate: ENVIRONMENT === 'production' ? 0.1 : 1.0,

      // Reduce noise in development
      enabled: ENVIRONMENT !== 'development',

      // Don't send PII
      beforeSend(event: any, hint: any) {
        // Remove sensitive data from request bodies
        if (event.request?.data) {
          event.request.data = '[Filtered]';
        }

        // Remove query params that might contain tokens
        if (event.request?.query_string) {
          const params = new URLSearchParams(event.request.query_string);
          if (params.has('token') || params.has('key')) {
            event.request.query_string = '[Filtered]';
          }
        }

        return event;
      },

      // Filter out noisy errors
      ignoreErrors: [
        // Browser extensions
        'top.GLOBALS',
        'chrome-extension://',
        'moz-extension://',

        // Network errors (already handled in UI)
        'NetworkError',
        'Failed to fetch',

        // User cancellations
        'AbortError',
        'The user aborted a request',
      ],
    });

    console.info('[Monitoring] Sentry initialized');
  } catch (error) {
    console.warn('[Monitoring] Failed to initialize Sentry:', error);
  }
}

/**
 * Check if Sentry is available and configured
 */
export function isSentryEnabled(): boolean {
  return SENTRY_ENABLED && !!SENTRY_DSN;
}

/**
 * Capture AppError with structured context
 */
export async function captureAppError(error: AppError, context?: Record<string, any>) {
  if (!isSentryEnabled()) {
    // Fallback to console logging in development
    console.error('[Error]', error, context);
    return;
  }

  try {
    const sentry = await loadSentry();
    if (!sentry) {
      console.error('[Error]', error, context);
      return;
    }

    sentry.withScope((scope: SentryScope) => {
      // Set error kind as tag for filtering
      scope.setTag('error_kind', error.kind);

      // Set HTTP status if available
      if (error.status) {
        scope.setTag('http_status', error.status);
      }

      // Set error code if available
      if (error.code) {
        scope.setTag('error_code', error.code);
      }

      // Add validation errors as context
      if (error.validationErrors && error.validationErrors.length > 0) {
        scope.setContext('validation_errors', {
          fields: error.validationErrors.map(e => e.field),
          count: error.validationErrors.length,
        });
      }

      // Add custom context
      if (context) {
        scope.setContext('additional', context);
      }

      // Add error details without sensitive data
      if (error.details) {
        const sanitizedDetails = sanitizeDetails(error.details);
        scope.setContext('error_details', sanitizedDetails);
      }

      // Determine severity based on error kind
      const level = getErrorLevel(error.kind);
      scope.setLevel(level);

      // Capture the error
      if (error.raw instanceof Error) {
        sentry.captureException(error.raw);
      } else {
        sentry.captureMessage(error.message, level);
      }
    });
  } catch (err) {
    console.warn('[Monitoring] Failed to capture error:', err);
  }
}

/**
 * Capture exception directly
 */
export async function captureException(error: Error, context?: Record<string, any>) {
  if (!isSentryEnabled()) {
    console.error('[Error]', error, context);
    return;
  }

  try {
    const sentry = await loadSentry();
    if (!sentry) {
      console.error('[Error]', error, context);
      return;
    }

    sentry.withScope((scope: SentryScope) => {
      if (context) {
        scope.setContext('additional', context);
      }
      sentry.captureException(error);
    });
  } catch (err) {
    console.warn('[Monitoring] Failed to capture exception:', err);
  }
}

/**
 * Set user context for error tracking
 */
export async function setUserContext(user: { id: string; email?: string; username?: string }) {
  if (!isSentryEnabled()) return;

  try {
    const sentry = await loadSentry();
    if (!sentry) return;

    sentry.setUser({
      id: user.id,
      email: user.email,
      username: user.username,
    });
  } catch (err) {
    console.warn('[Monitoring] Failed to set user context:', err);
  }
}

/**
 * Clear user context (e.g., on logout)
 */
export async function clearUserContext() {
  if (!isSentryEnabled()) return;

  try {
    const sentry = await loadSentry();
    if (!sentry) return;

    sentry.setUser(null);
  } catch (err) {
    console.warn('[Monitoring] Failed to clear user context:', err);
  }
}

/**
 * Add breadcrumb for debugging
 */
export async function addBreadcrumb(
  message: string,
  category: string,
  data?: Record<string, any>
) {
  if (!isSentryEnabled()) return;

  try {
    const sentry = await loadSentry();
    if (!sentry) return;

    sentry.addBreadcrumb({
      message,
      category,
      data,
      level: 'info',
    });
  } catch (err) {
    console.warn('[Monitoring] Failed to add breadcrumb:', err);
  }
}

/**
 * Map error kind to Sentry severity level
 */
function getErrorLevel(kind: AppError['kind']): SentryLevel {
  switch (kind) {
    case 'validation':
      return 'warning';
    case 'auth':
    case 'permission':
      return 'info';
    case 'not_found':
      return 'info';
    case 'conflict':
      return 'warning';
    case 'rate_limit':
      return 'warning';
    case 'server':
      return 'error';
    case 'network':
      return 'warning';
    case 'unknown':
    default:
      return 'error';
  }
}

/**
 * Sanitize error details to remove sensitive data
 */
function sanitizeDetails(details: unknown): any {
  if (!details || typeof details !== 'object') {
    return details;
  }

  const sanitized: any = Array.isArray(details) ? [] : {};
  const sensitiveKeys = ['password', 'token', 'secret', 'key', 'authorization', 'auth'];

  for (const [key, value] of Object.entries(details)) {
    const lowerKey = key.toLowerCase();
    const isSensitive = sensitiveKeys.some(k => lowerKey.includes(k));

    if (isSensitive) {
      sanitized[key] = '[Redacted]';
    } else if (value && typeof value === 'object') {
      sanitized[key] = sanitizeDetails(value);
    } else {
      sanitized[key] = value;
    }
  }

  return sanitized;
}
