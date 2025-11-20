'use client';

import { ChevronDown, ChevronUp } from 'lucide-react';
import { StatusBadge } from './ui/status-badge';
import { Accordion } from './ui/accordion';
import { Button } from './ui/button';
import type { RunStep } from '@/lib/types';

interface StepCardProps {
  step: RunStep;
  number: number;
  isExpanded: boolean;
  isSelected: boolean;
  onToggle: () => void;
  onFocusLogs: () => void;
}

function formatDuration(ms?: number): string {
  if (!ms) return '-';
  if (ms < 1000) return `${ms}ms`;
  const seconds = (ms / 1000).toFixed(1);
  return `${seconds}s`;
}

function formatTime(timestamp?: string): string {
  if (!timestamp) return '-';
  const date = new Date(timestamp);
  return date.toLocaleTimeString('en-US', { hour12: false });
}

function formatCost(cost?: number): string {
  if (!cost) return '$0.0000';
  return `$${cost.toFixed(4)}`;
}

function extractSummary(output: any): string {
  if (!output) return 'No output';

  if (typeof output === 'string') {
    return output.slice(0, 120) + (output.length > 120 ? '...' : '');
  }

  // For AI extraction results
  if (output.category || output.inferred_impact) {
    const parts = [];
    if (output.category) parts.push(`category=${output.category}`);
    if (output.inferred_impact) parts.push(`impact=${output.inferred_impact}`);
    if (output.inferred_urgency) parts.push(`urgency=${output.inferred_urgency}`);
    return `Extracted: ${parts.join(', ')}`;
  }

  // For routing results
  if (output.route || output.team) {
    return `Routed to: ${output.route || output.team}`;
  }

  // For scoring results
  if (typeof output.score === 'number' || output.risk_score !== undefined) {
    const score = output.score ?? output.risk_score;
    return `Score: ${typeof score === 'number' ? score.toFixed(2) : score}`;
  }

  // For summaries/text generation
  if (output.summary) {
    return output.summary.slice(0, 150) + (output.summary.length > 150 ? '...' : '');
  }

  if (output.text || output.content) {
    const text = output.text || output.content;
    return text.slice(0, 150) + (text.length > 150 ? '...' : '');
  }

  // Generic fallback
  const keys = Object.keys(output);
  if (keys.length === 0) return 'Empty result';
  if (keys.length <= 3) {
    return keys.map(k => `${k}: ${JSON.stringify(output[k]).slice(0, 30)}`).join(', ');
  }
  return `${keys.length} fields: ${keys.slice(0, 3).join(', ')}...`;
}

export function StepCard({
  step,
  number,
  isExpanded,
  isSelected,
  onToggle,
  onFocusLogs,
}: StepCardProps) {
  const summary = extractSummary(step.output);
  const hasError = step.status === 'failed' && step.error;

  return (
    <div
      className={`
        bg-white border rounded-lg p-4 mb-3 transition-all
        ${isSelected ? 'border-blue-500 shadow-md ring-2 ring-blue-100' : 'border-slate-200'}
        ${step.status === 'failed' ? 'border-l-4 border-l-red-500' : ''}
        ${step.status === 'completed' || step.status === 'success' ? 'border-l-4 border-l-green-500' : ''}
        ${step.status === 'running' ? 'border-l-4 border-l-blue-500' : ''}
      `}
      data-step-id={step.id}
    >
      {/* Header - always visible */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className="text-sm font-medium text-slate-500 flex-shrink-0">[{number}]</span>
          <StatusBadge status={step.status} />
          <span className="font-semibold text-slate-900 truncate">{step.name}</span>
        </div>
        <span className="text-sm font-medium text-slate-600 flex-shrink-0 ml-2">
          {formatDuration(step.duration_ms)}
        </span>
      </div>

      {/* Progress bar */}
      <div className="h-0.5 mb-3 bg-slate-100 rounded-full overflow-hidden">
        <div
          className={`h-full transition-all ${
            step.status === 'completed' || step.status === 'success'
              ? 'bg-green-500'
              : step.status === 'failed'
                ? 'bg-red-500'
                : step.status === 'running'
                  ? 'bg-blue-500 animate-pulse'
                  : 'bg-slate-300'
          }`}
          style={{
            width: step.status === 'completed' || step.status === 'success' || step.status === 'failed' ? '100%' : '50%',
          }}
        />
      </div>

      {/* Metadata */}
      <div className="flex items-center gap-2 text-xs text-slate-600 mb-3 flex-wrap">
        <span className="font-mono bg-slate-100 px-2 py-0.5 rounded">{step.step_type}</span>
        {step.tokens !== undefined && step.tokens > 0 && (
          <>
            <span className="text-slate-400">•</span>
            <span>{step.tokens.toLocaleString()} tokens</span>
            <span className="text-slate-400">•</span>
            <span>{formatCost(step.cost_usd)}</span>
          </>
        )}
      </div>

      {/* Summary - always visible */}
      <div className="text-sm text-slate-700 mb-3 leading-relaxed">
        {summary}
      </div>

      {/* Error preview */}
      {hasError && !isExpanded && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800">
          <p className="font-medium">Error: {step.error?.message || 'Unknown error'}</p>
        </div>
      )}

      {/* Expand toggle */}
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={onToggle}
          className="text-xs"
        >
          {isExpanded ? (
            <>
              Hide details <ChevronUp className="ml-1 h-3 w-3" />
            </>
          ) : (
            <>
              Show details <ChevronDown className="ml-1 h-3 w-3" />
            </>
          )}
        </Button>

        {isExpanded && (
          <Button
            variant="outline"
            size="sm"
            onClick={onFocusLogs}
            className="text-xs"
          >
            View logs for this step →
          </Button>
        )}
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div className="mt-4 space-y-3 pt-3 border-t border-slate-100">
          {/* Timestamps */}
          <div className="flex gap-4 text-xs text-slate-600">
            <span>
              <span className="font-medium">Started:</span> {formatTime(step.start_ts)}
            </span>
            <span>
              <span className="font-medium">Ended:</span> {formatTime(step.end_ts)}
            </span>
          </div>

          {/* Raw data accordions */}
          {step.input && Object.keys(step.input).length > 0 && (
            <Accordion title="Raw Input" defaultOpen={false}>
              <pre className="text-xs bg-slate-50 p-3 rounded overflow-x-auto font-mono">
                {JSON.stringify(step.input, null, 2)}
              </pre>
            </Accordion>
          )}

          {step.output && (
            <Accordion title="Raw Output" defaultOpen={false}>
              <pre className="text-xs bg-slate-50 p-3 rounded overflow-x-auto font-mono">
                {JSON.stringify(step.output, null, 2)}
              </pre>
            </Accordion>
          )}

          {hasError && (
            <Accordion title="Error Details" defaultOpen={true}>
              <div className="space-y-2">
                <p className="text-sm text-red-800">
                  <span className="font-medium">Message:</span> {step.error.message}
                </p>
                {step.error.type && (
                  <p className="text-xs text-red-700">
                    <span className="font-medium">Type:</span> {step.error.type}
                  </p>
                )}
                {step.error.traceback && (
                  <pre className="text-xs bg-red-50 p-3 rounded overflow-x-auto font-mono text-red-900 border border-red-200">
                    {step.error.traceback}
                  </pre>
                )}
              </div>
            </Accordion>
          )}
        </div>
      )}
    </div>
  );
}
