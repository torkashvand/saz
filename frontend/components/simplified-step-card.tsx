'use client';

import { useState } from 'react';
import { CheckCircle2, XCircle, Clock, Play, ChevronDown, ChevronRight, Eye, Copy, AlertCircle } from 'lucide-react';
import { Card, CardContent } from './ui/card';
import { Button } from './ui/button';
import { CollapsibleJson } from './json-view';
import type { StepStatus } from '@/lib/types';
import type { ErrorCategory } from '@/lib/types-enhanced';

interface SimplifiedStepCardProps {
  number: number;
  name: string;
  description?: string;
  status: StepStatus;
  durationMs?: number;
  input?: any;
  output?: any;
  failureReason?: string;
  errorCategory?: ErrorCategory;
  onViewLogs?: () => void;
}

/**
 * Get status configuration for step card.
 */
function getStepStatusConfig(status: StepStatus) {
  switch (status) {
    case 'completed':
    case 'success':
      return {
        icon: CheckCircle2,
        label: 'Completed',
        iconColor: 'text-green-500',
        bgColor: 'bg-green-50',
        borderColor: 'border-green-200',
      };
    case 'failed':
      return {
        icon: XCircle,
        label: 'Failed',
        iconColor: 'text-red-500',
        bgColor: 'bg-red-50',
        borderColor: 'border-red-300',
      };
    case 'running':
      return {
        icon: Play,
        label: 'Running',
        iconColor: 'text-blue-500 animate-pulse',
        bgColor: 'bg-blue-50',
        borderColor: 'border-blue-200',
      };
    case 'pending':
    case 'queued':
      return {
        icon: Clock,
        label: 'Queued',
        iconColor: 'text-slate-400',
        bgColor: 'bg-slate-50',
        borderColor: 'border-slate-200',
      };
    case 'suspended':
      return {
        icon: Clock,
        label: 'Suspended',
        iconColor: 'text-amber-500',
        bgColor: 'bg-amber-50',
        borderColor: 'border-amber-200',
      };
    default:
      return {
        icon: Clock,
        label: status,
        iconColor: 'text-slate-400',
        bgColor: 'bg-slate-50',
        borderColor: 'border-slate-200',
      };
  }
}

/**
 * Format duration for display.
 */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

/**
 * Copy text to clipboard.
 */
function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text);
}

/**
 * Individual step card for timeline view.
 *
 * Design principles:
 * - Compact summary by default
 * - Clear visual status indicator
 * - Human-friendly description
 * - Technical details hidden behind expand controls
 * - Failed steps get prominent error display
 */
export function SimplifiedStepCard({
  number,
  name,
  description,
  status,
  durationMs,
  input,
  output,
  failureReason,
  errorCategory,
  onViewLogs,
}: SimplifiedStepCardProps) {
  const [showInputOutput, setShowInputOutput] = useState(false);
  const [showRawDetails, setShowRawDetails] = useState(false);
  const statusConfig = getStepStatusConfig(status);
  const StatusIcon = statusConfig.icon;
  const isFailed = status === 'failed';

  return (
    <Card className={`${isFailed ? `border-2 ${statusConfig.borderColor}` : 'border-slate-200'}`}>
      <CardContent className="pt-4">
        {/* Header: status icon + step name + duration */}
        <div className="flex items-start gap-3 mb-2">
          {/* Status icon */}
          <div className={`flex-shrink-0 mt-0.5`}>
            <StatusIcon className={`h-5 w-5 ${statusConfig.iconColor}`} />
          </div>

          {/* Step info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2 mb-1 flex-wrap">
              <h3 className="text-base font-semibold text-slate-900">
                Step {number}: {name}
              </h3>
              <span className={`text-xs font-medium px-2 py-0.5 rounded ${statusConfig.bgColor} ${statusConfig.iconColor}`}>
                {statusConfig.label}
              </span>
            </div>

            {/* Description */}
            {description && (
              <p className="text-sm text-slate-600 mb-2">
                {description}
              </p>
            )}

            {/* Duration */}
            {durationMs != null && (
              <p className="text-xs text-slate-500">
                Duration: {formatDuration(durationMs)}
              </p>
            )}
          </div>
        </div>

        {/* Failure reason (if failed) */}
        {isFailed && failureReason && (
          <div className="mt-3 mb-3 p-3 bg-red-50 border border-red-200 rounded-lg">
            <div className="flex items-start gap-2">
              <AlertCircle className="h-4 w-4 text-red-600 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm font-medium text-red-900 mb-1">Error</p>
                <p className="text-sm text-red-700">{failureReason}</p>
              </div>
            </div>
          </div>
        )}

        {/* Action buttons */}
        <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-slate-200">
          {/* View input/output */}
          {(input || output) && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowInputOutput(!showInputOutput)}
              className="gap-2"
            >
              {showInputOutput ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
              View Input/Output
            </Button>
          )}

          {/* View logs */}
          {onViewLogs && (
            <Button
              variant="outline"
              size="sm"
              onClick={onViewLogs}
              className="gap-2"
            >
              <Eye className="h-4 w-4" />
              View Logs for This Step
            </Button>
          )}
        </div>

        {/* Input/Output panel (expanded) */}
        {showInputOutput && (
          <div className="mt-4 space-y-3">
            {/* Input */}
            {input && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium text-slate-700">Input</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => copyToClipboard(JSON.stringify(input, null, 2))}
                    className="h-7 gap-1 text-xs"
                  >
                    <Copy className="h-3 w-3" />
                    Copy
                  </Button>
                </div>
                <CollapsibleJson data={input} maxHeight={200} />
              </div>
            )}

            {/* Output */}
            {output && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-medium text-slate-700">Output</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => copyToClipboard(JSON.stringify(output, null, 2))}
                    className="h-7 gap-1 text-xs"
                  >
                    <Copy className="h-3 w-3" />
                    Copy
                  </Button>
                </div>
                <CollapsibleJson data={output} maxHeight={200} />
              </div>
            )}

            {/* Show raw details toggle */}
            <div>
              <button
                onClick={() => setShowRawDetails(!showRawDetails)}
                className="flex items-center gap-2 text-xs text-slate-600 hover:text-slate-900 transition-colors"
              >
                {showRawDetails ? (
                  <ChevronDown className="h-3 w-3" />
                ) : (
                  <ChevronRight className="h-3 w-3" />
                )}
                Show raw JSON
              </button>

              {showRawDetails && (
                <div className="mt-2 space-y-2">
                  {input && (
                    <div>
                      <p className="text-xs font-medium text-slate-700 mb-1">Raw Input:</p>
                      <div className="bg-slate-900 rounded p-3 overflow-x-auto">
                        <pre className="text-xs text-slate-200 whitespace-pre-wrap">
                          {JSON.stringify(input, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                  {output && (
                    <div>
                      <p className="text-xs font-medium text-slate-700 mb-1">Raw Output:</p>
                      <div className="bg-slate-900 rounded p-3 overflow-x-auto">
                        <pre className="text-xs text-slate-200 whitespace-pre-wrap">
                          {JSON.stringify(output, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
