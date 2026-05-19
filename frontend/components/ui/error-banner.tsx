'use client';

import { AlertCircle, WifiOff, ShieldAlert, Server } from 'lucide-react';
import { Button } from './button';
import type { AppError } from '@/lib/errors';

interface ErrorBannerProps {
  error: AppError | Error | null;
  title?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export function ErrorBanner({ error, title, onRetry, onDismiss }: ErrorBannerProps) {
  if (!error) return null;

  // Convert to AppError if needed
  const appError: AppError = 'kind' in error ? error : { kind: 'unknown', message: error.message };

  const { kind, message } = appError;

  // Icon based on error kind
  const Icon =
    {
      network: WifiOff,
      auth: ShieldAlert,
      permission: ShieldAlert,
      server: Server,
      validation: AlertCircle,
      not_found: AlertCircle,
      conflict: AlertCircle,
      rate_limit: AlertCircle,
      unknown: AlertCircle,
    }[kind] || AlertCircle;

  // Color scheme based on error kind
  const colorClass = {
    validation: 'border-yellow-300 bg-yellow-50 text-yellow-900',
    auth: 'border-blue-300 bg-blue-50 text-blue-900',
    permission: 'border-orange-300 bg-orange-50 text-orange-900',
    network: 'border-purple-300 bg-purple-50 text-purple-900',
    server: 'border-red-300 bg-red-50 text-red-900',
    not_found: 'border-slate-300 bg-slate-50 text-slate-900',
    conflict: 'border-orange-300 bg-orange-50 text-orange-900',
    rate_limit: 'border-yellow-300 bg-yellow-50 text-yellow-900',
    unknown: 'border-red-300 bg-red-50 text-red-900',
  }[kind];

  return (
    <div className={`border-l-4 p-4 rounded ${colorClass}`}>
      <div className="flex items-start gap-3">
        <Icon className="h-5 w-5 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          {title && <h3 className="font-semibold mb-1">{title}</h3>}
          <p className="text-sm">{message}</p>

          {appError.validationErrors && appError.validationErrors.length > 0 && (
            <ul className="mt-2 text-sm space-y-1">
              {appError.validationErrors.map((err, idx) => (
                <li key={idx}>
                  <strong>{err.field}:</strong> {err.message}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex gap-2">
          {onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          )}
          {onDismiss && (
            <Button variant="ghost" size="sm" onClick={onDismiss}>
              Dismiss
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
