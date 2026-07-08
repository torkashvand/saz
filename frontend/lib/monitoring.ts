// Client-side error reporting. Errors surface in the UI; this module keeps a
// single seam for logging them (console today, a real tracker if one is ever
// wired up).

import type { AppError } from './errors';

export function captureAppError(error: AppError, context?: Record<string, unknown>) {
  console.error('[Error]', error, context);
}

export function captureException(error: Error, context?: Record<string, unknown>) {
  console.error('[Error]', error, context);
}
