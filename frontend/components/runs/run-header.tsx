'use client';

import { Button } from '@/components/ui/button';
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCw,
  Settings,
  PauseCircle,
} from 'lucide-react';
import type { RunDetailResponse } from '@/lib/types';
import { runStatusStyle } from '@/lib/runs/status-display';

interface RunHeaderProps {
  run: RunDetailResponse;
  onRetry?: () => void;
  onConfigureCredential?: () => void;
  isRetrying?: boolean;
}

const STATUS_ICON = {
  completed: CheckCircle2,
  failed: AlertCircle,
  running: Clock,
  suspended: PauseCircle,
  queued: Clock,
} as const;

export function RunHeader({ run, onRetry, onConfigureCredential, isRetrying }: RunHeaderProps) {
  const isFailed = run.status === 'failed';
  const style = runStatusStyle(run.status);
  const Icon = STATUS_ICON[run.status] ?? Clock;

  const errorSummary = run.error_summary;
  const failedStepName = errorSummary?.failed_step_name;
  const failedStepNumber = errorSummary?.failed_step_number;

  return (
    <div className="space-y-3">
      {/* Status badge */}
      <div className="flex items-center gap-3">
        <Icon
          className={`h-5 w-5 ${style.accent} ${run.status === 'running' ? 'animate-pulse' : ''}`}
        />

        <span className={`px-3 py-1 rounded-md text-sm font-medium border ${style.pill}`}>
          {style.label}
        </span>

        <span className="text-xs text-slate-500 font-mono">{run.id}</span>
      </div>

      {/* Error summary for failed runs */}
      {isFailed && errorSummary && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1 space-y-2">
              <p className="text-sm text-red-900">
                {errorSummary.message}
                {failedStepNumber != null && failedStepName && (
                  <span className="block mt-1 text-red-700">
                    Failed at step {failedStepNumber + 1}:{' '}
                    <span className="font-medium">{failedStepName}</span>
                  </span>
                )}
              </p>

              {/* Action buttons */}
              <div className="flex items-center gap-2">
                {onRetry && (
                  <Button onClick={onRetry} disabled={isRetrying} size="sm" className="h-8">
                    {isRetrying ? (
                      <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                    )}
                    {isRetrying ? 'Retrying...' : 'Retry from failing step'}
                  </Button>
                )}
                {errorSummary.remediation_actions?.includes('configure_credential') &&
                  onConfigureCredential && (
                    <Button
                      onClick={onConfigureCredential}
                      variant="outline"
                      size="sm"
                      className="h-8"
                    >
                      <Settings className="h-3.5 w-3.5 mr-1.5" />
                      Configure credential
                    </Button>
                  )}
              </div>

              {/* Technical details (collapsed by default) */}
              {errorSummary.technical_details &&
                Object.keys(errorSummary.technical_details).length > 0 && (
                  <details className="mt-3">
                    <summary className="text-xs text-red-700 cursor-pointer hover:underline select-none">
                      Technical details (for engineers)
                    </summary>
                    <div className="mt-2 p-3 bg-red-100 rounded border border-red-200 text-xs space-y-1">
                      {errorSummary.technical_details.error_type && (
                        <div>
                          <span className="font-medium text-red-900">Type:</span>{' '}
                          <span className="text-red-800 font-mono">
                            {errorSummary.technical_details.error_type}
                          </span>
                        </div>
                      )}
                      {errorSummary.technical_details.raw_error && (
                        <div>
                          <span className="font-medium text-red-900">Detail:</span>{' '}
                          <span className="text-red-800">
                            {typeof errorSummary.technical_details.raw_error === 'string'
                              ? errorSummary.technical_details.raw_error
                              : JSON.stringify(errorSummary.technical_details.raw_error)}
                          </span>
                        </div>
                      )}
                      <p className="text-red-600 italic mt-2">
                        Note: Stack traces are not included in API responses by default.
                      </p>
                    </div>
                  </details>
                )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
