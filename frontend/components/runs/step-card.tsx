'use client';

import { useState } from 'react';
import { ChevronDown, ChevronUp, Clock, DollarSign, FileText, AlertCircle, CheckCircle2, Play, Settings, Zap, Globe, X, Loader2, Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { CollapsibleJson } from '@/components/common/json-view';
import type { RunStep, PlannedStep } from '@/lib/types';
import type { DisplayStep } from '@/lib/runs/display-steps';
import { getStepHelpText } from '@/lib/runs/display-steps';

interface CompactStepCardProps {
  displayStep: DisplayStep;
  isSelected?: boolean;
  onViewLogs?: () => void;
  onCardClick?: () => void;
}

// Step type icon mapping
function getStepTypeIcon(stepType: string | null | undefined) {
  if (!stepType) return { Icon: Settings, color: 'text-slate-600', bg: 'bg-slate-100' }; // Fallback for null/undefined
  if (stepType.startsWith('ai.')) return { Icon: Zap, color: 'text-purple-600', bg: 'bg-purple-100' };
  if (stepType.startsWith('tool.') || stepType.startsWith('http')) return { Icon: Settings, color: 'text-blue-600', bg: 'bg-blue-100' };
  if (stepType === 'webhook.wait' || stepType === 'human.approval') return { Icon: Globe, color: 'text-green-600', bg: 'bg-green-100' };
  return { Icon: Play, color: 'text-slate-600', bg: 'bg-slate-100' }; // Default
}

export function CompactStepCard({ displayStep, isSelected, onViewLogs, onCardClick }: CompactStepCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const isPlanned = displayStep.kind === 'planned';
  const step = displayStep.kind === 'executed' ? displayStep.step : null;
  const planned = displayStep.kind === 'planned' ? displayStep.planned : displayStep.planned;

  // Step info
  const stepNumber = displayStep.index;
  const stepName = step?.name || planned?.name || 'Unknown';
  const stepType = step?.step_type || planned?.step_type;

  const isCompleted = step?.status === 'completed';
  const isFailed = step?.status === 'failed';
  const isRunning = step?.status === 'running';

  // Get step type icon
  const { Icon: StepIcon, color: iconColor, bg: iconBg } = getStepTypeIcon(stepType);

  const handleCardClick = (e: React.MouseEvent) => {
    // Only toggle if clicking the card header area, not inner content
    const target = e.target as HTMLElement;
    // Ignore clicks on buttons or interactive elements
    if (target.closest('button') && !target.closest('[data-card-header]')) {
      return;
    }

    // Toggle expand state
    setIsExpanded(!isExpanded);
    // Notify parent about card click (for wizard sync)
    if (onCardClick) {
      onCardClick();
    }
  };

  // Count log levels (if available from step metadata)
  const logCounts = {
    info: 0,
    warning: 0,
    error: isFailed ? 1 : 0,
  };

  const formatDuration = (ms?: number) => {
    if (!ms) return '-';
    if (ms < 1000) return `${ms}ms`;
    const seconds = (ms / 1000).toFixed(1);
    return `${seconds}s`;
  };

  const formatCost = (cost?: number) => {
    if (!cost) return null;
    return `$${cost.toFixed(4)}`;
  };

  const formatTime = (timestamp?: string) => {
    if (!timestamp) return null;
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', { hour12: false });
  };

  const timingInfo = step?.start_ts
    ? `Started ${formatTime(step.start_ts)} • Duration ${formatDuration(step.duration_ms)}`
    : isPlanned
    ? 'Not started'
    : 'Not started yet';

  // Help text for planned steps
  const helpText = planned ? getStepHelpText(planned) : null;

  return (
    <div
      data-step-id={step?.id || `planned-${stepNumber}`}
      className={cn(
        'border rounded-lg bg-white transition-all duration-200 shadow-sm',
        isSelected && 'ring-2 ring-blue-400 shadow-md',
        !isSelected && isPlanned && 'border-slate-100',
        !isSelected && !isPlanned && 'border-slate-200'
      )}
    >
      {/* Compact header */}
      <div
        data-card-header
        role="button"
        tabIndex={0}
        onClick={handleCardClick}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleCardClick(e as any);
          }
        }}
        className={cn(
          'p-4 cursor-pointer transition-colors',
          isPlanned ? 'hover:bg-slate-25' : 'hover:bg-slate-50'
        )}
      >
        <div className="flex items-start justify-between gap-3">
          {/* Left: Step info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1">
              {/* Step type icon with status badge */}
              <div className="relative flex-shrink-0">
                <div className={cn('p-1.5 rounded-full', iconBg, isPlanned && 'opacity-60')}>
                  <StepIcon className={cn('h-3.5 w-3.5', iconColor)} />
                </div>
                {/* Status badge overlay */}
                {!isPlanned && (
                  <div className="absolute -bottom-0.5 -right-0.5">
                    {isCompleted && (
                      <div className="bg-white rounded-full p-0.5">
                        <CheckCircle2 className="h-2.5 w-2.5 text-green-600" />
                      </div>
                    )}
                    {isFailed && (
                      <div className="bg-white rounded-full p-0.5">
                        <X className="h-2.5 w-2.5 text-red-600" />
                      </div>
                    )}
                    {isRunning && (
                      <div className="bg-white rounded-full p-0.5">
                        <Loader2 className="h-2.5 w-2.5 text-blue-600 animate-spin" />
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Step name */}
              <div className="flex-1 min-w-0">
                <h3 className={cn(
                  'font-medium text-sm truncate',
                  isPlanned ? 'text-slate-600' : 'text-slate-900'
                )}>
                  Step {stepNumber + 1}: {stepName}
                </h3>
              </div>

              {/* Status chip for planned steps */}
              {isPlanned && (
                <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 border border-slate-200">
                  <span className="text-xs font-medium text-slate-600">Not started</span>
                </div>
              )}
            </div>

            {/* Timing info */}
            <p className={cn(
              'text-xs ml-10',
              isPlanned ? 'text-slate-400' : 'text-slate-500'
            )}>
              {timingInfo}
            </p>
          </div>

          {/* Right: Chips */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {/* Cost chip */}
            {step?.cost_usd && step.cost_usd > 0 ? (
              <div className="flex items-center gap-1 px-2 py-1 rounded bg-amber-50 border border-amber-200">
                <DollarSign className="h-3 w-3 text-amber-700" />
                <span className="text-xs font-medium text-amber-900">
                  {step.tokens?.toLocaleString()} tokens • {formatCost(step.cost_usd)}
                </span>
              </div>
            ) : isPlanned ? (
              <div className="flex items-center gap-1 px-2 py-1 rounded bg-slate-50 border border-slate-100">
                <DollarSign className="h-3 w-3 text-slate-400" />
                <span className="text-xs font-medium text-slate-400">
                  –
                </span>
              </div>
            ) : null}

            {/* Logs chip */}
            {!isPlanned && onViewLogs ? (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onViewLogs();
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    e.stopPropagation();
                    onViewLogs();
                  }
                }}
                className="flex items-center gap-1 px-2 py-1 rounded bg-slate-50 border border-slate-200 hover:bg-slate-100 transition-colors"
              >
                <FileText className="h-3 w-3 text-slate-600" />
                <span className="text-xs font-medium text-slate-700">
                  Logs: {logCounts.info + logCounts.warning + logCounts.error}
                  {logCounts.error > 0 && (
                    <span className="text-red-600 ml-0.5">({logCounts.error} error)</span>
                  )}
                </span>
              </button>
            ) : isPlanned ? (
              <div
                className="flex items-center gap-1 px-2 py-1 rounded bg-slate-50 border border-slate-100 cursor-default"
                title="No logs yet"
              >
                <FileText className="h-3 w-3 text-slate-400" />
                <span className="text-xs font-medium text-slate-400">
                  Logs: 0
                </span>
              </div>
            ) : null}

            {/* Expand toggle */}
            <div className="h-7 w-7 flex items-center justify-center">
              {isExpanded ? (
                <ChevronUp className="h-4 w-4 text-slate-600" />
              ) : (
                <ChevronDown className="h-4 w-4 text-slate-600" />
              )}
            </div>
          </div>
        </div>

        {/* Error preview (if failed) */}
        {isFailed && step?.error && !isExpanded && (
          <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
            {typeof step.error === 'object' ? step.error.message : step.error}
          </div>
        )}

        {/* Help text preview for planned steps */}
        {isPlanned && !isExpanded && helpText && (
          <div className="mt-2 p-2 bg-blue-50 border border-blue-100 rounded text-xs text-blue-700 flex items-start gap-2">
            <Info className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
            <span>{helpText}</span>
          </div>
        )}
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div className="border-t border-slate-200 p-4 space-y-3 bg-slate-50">
          {/* Help text for planned steps (expanded view) */}
          {isPlanned && helpText && (
            <div className="p-3 bg-blue-50 border border-blue-100 rounded text-sm text-blue-800 flex items-start gap-2">
              <Info className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-medium mb-1">What this step will do:</div>
                <div>{helpText}</div>
              </div>
            </div>
          )}

          {/* Input (only for executed steps) */}
          {step?.input && Object.keys(step.input).length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-slate-700 mb-1.5">Input</h4>
              <CollapsibleJson label="View input" data={step.input} />
            </div>
          )}

          {/* Output (only for executed steps) */}
          {step?.output && Object.keys(step.output).length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-slate-700 mb-1.5">Output</h4>
              <CollapsibleJson label="View output" data={step.output} />
            </div>
          )}

          {/* Error details (only for executed steps) */}
          {step?.error && (
            <div>
              <h4 className="text-xs font-medium text-red-700 mb-1.5">Error Details</h4>
              <div className="p-3 bg-red-50 border border-red-200 rounded text-xs space-y-1">
                <div>
                  <span className="font-medium text-red-900">Message:</span>{' '}
                  <span className="text-red-800">
                    {typeof step.error === 'object' ? step.error.message : step.error}
                  </span>
                </div>
                {typeof step.error === 'object' && step.error.type && (
                  <div>
                    <span className="font-medium text-red-900">Type:</span>{' '}
                    <span className="text-red-800 font-mono">{step.error.type}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Metadata (only for executed steps) */}
          {step && (
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <span className="text-slate-500">Status:</span>{' '}
                <span className="font-medium text-slate-900">{step.status}</span>
              </div>
              <div>
                <span className="text-slate-500">Duration:</span>{' '}
                <span className="font-medium text-slate-900">{formatDuration(step.duration_ms)}</span>
              </div>
              {step.retry_count > 0 && (
                <div>
                  <span className="text-slate-500">Retries:</span>{' '}
                  <span className="font-medium text-slate-900">{step.retry_count}</span>
                </div>
              )}
              {step.tokens && (
                <div>
                  <span className="text-slate-500">Tokens:</span>{' '}
                  <span className="font-medium text-slate-900">{step.tokens.toLocaleString()}</span>
                </div>
              )}
            </div>
          )}

          {/* Planned step metadata */}
          {isPlanned && (
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <span className="text-slate-500">Status:</span>{' '}
                <span className="font-medium text-slate-600">Pending</span>
              </div>
              <div>
                <span className="text-slate-500">Step type:</span>{' '}
                <span className="font-medium text-slate-600 font-mono text-[10px]">{stepType || 'unknown'}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}