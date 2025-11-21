'use client';

import { CheckCircle2, XCircle, Clock, Play, User, Calendar, Timer, TrendingUp } from 'lucide-react';
import { Card, CardContent } from './ui/card';
import type { StepStatus } from '@/lib/types';

interface RunHeaderProps {
  flowName: string;
  runId: string;
  status: StepStatus;
  triggeredBy?: string;
  startedAt?: string;
  durationMs: number | null;
  totalSteps: number;
  succeededSteps: number;
  failedSteps: number;
  runningSteps: number;
}

/**
 * Get status badge configuration.
 */
function getStatusConfig(status: StepStatus) {
  switch (status) {
    case 'completed':
    case 'success':
      return {
        label: 'Succeeded',
        icon: CheckCircle2,
        className: 'bg-green-100 text-green-800 border-green-200',
        iconClassName: 'text-green-600',
      };
    case 'failed':
      return {
        label: 'Failed',
        icon: XCircle,
        className: 'bg-red-100 text-red-800 border-red-200',
        iconClassName: 'text-red-600',
      };
    case 'running':
      return {
        label: 'Running',
        icon: Play,
        className: 'bg-blue-100 text-blue-800 border-blue-200',
        iconClassName: 'text-blue-600 animate-pulse',
      };
    case 'pending':
    case 'queued':
      return {
        label: 'Pending',
        icon: Clock,
        className: 'bg-slate-100 text-slate-800 border-slate-200',
        iconClassName: 'text-slate-600',
      };
    case 'suspended':
      return {
        label: 'Suspended',
        icon: Clock,
        className: 'bg-amber-100 text-amber-800 border-amber-200',
        iconClassName: 'text-amber-600',
      };
    default:
      return {
        label: status,
        icon: Clock,
        className: 'bg-slate-100 text-slate-800 border-slate-200',
        iconClassName: 'text-slate-600',
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
 * Format timestamp for display.
 */
function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

/**
 * Run summary header.
 *
 * Design principles:
 * - At-a-glance status understanding
 * - Clear, non-technical language
 * - Visual hierarchy: status > metadata > details
 */
export function RunHeader({
  flowName,
  runId,
  status,
  triggeredBy = 'System',
  startedAt,
  durationMs,
  totalSteps,
  succeededSteps,
  failedSteps,
  runningSteps,
}: RunHeaderProps) {
  const statusConfig = getStatusConfig(status);
  const StatusIcon = statusConfig.icon;

  return (
    <Card className="border-slate-200">
      <CardContent className="pt-6">
        {/* Flow name and status */}
        <div className="flex items-start justify-between mb-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 mb-2">
              {flowName}
            </h1>
            <p className="text-sm text-slate-500 font-mono">
              Run ID: {runId}
            </p>
          </div>

          {/* Status badge */}
          <div className={`flex items-center gap-2 px-4 py-2 rounded-lg border-2 ${statusConfig.className}`}>
            <StatusIcon className={`h-5 w-5 ${statusConfig.iconClassName}`} />
            <span className="font-semibold text-sm">
              {statusConfig.label}
            </span>
          </div>
        </div>

        {/* Metadata grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-slate-200">
          {/* Triggered by */}
          <div className="flex items-center gap-2">
            <User className="h-4 w-4 text-slate-400" />
            <div>
              <p className="text-xs text-slate-500">Triggered by</p>
              <p className="text-sm font-medium text-slate-900">{triggeredBy}</p>
            </div>
          </div>

          {/* Started at */}
          {startedAt && (
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-slate-400" />
              <div>
                <p className="text-xs text-slate-500">Started</p>
                <p className="text-sm font-medium text-slate-900">
                  {formatTimestamp(startedAt)}
                </p>
              </div>
            </div>
          )}

          {/* Duration */}
          <div className="flex items-center gap-2">
            <Timer className="h-4 w-4 text-slate-400" />
            <div>
              <p className="text-xs text-slate-500">Duration</p>
              <p className="text-sm font-medium text-slate-900">
                {durationMs != null ? formatDuration(durationMs) : 'Not started'}
              </p>
            </div>
          </div>

          {/* Steps summary */}
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-slate-400" />
            <div>
              <p className="text-xs text-slate-500">Steps</p>
              <p className="text-sm font-medium text-slate-900">
                {totalSteps} total
                {succeededSteps > 0 && (
                  <span className="text-green-600"> • {succeededSteps} done</span>
                )}
                {failedSteps > 0 && (
                  <span className="text-red-600"> • {failedSteps} failed</span>
                )}
                {runningSteps > 0 && (
                  <span className="text-blue-600"> • {runningSteps} running</span>
                )}
              </p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
