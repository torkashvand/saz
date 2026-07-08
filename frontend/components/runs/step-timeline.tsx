'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import type { PlannedStep, RunStep } from '@/lib/types';
import { findExecutedStepForPlanned } from '@/lib/runs/display-steps';

interface StepProgressTimelineProps {
  plannedSteps: PlannedStep[];
  executedSteps: RunStep[];
  runStatus: string;
  selectedStepIndex: number | null;
  onSelectStep: (index: number) => void;
  /** Canonical step indexes currently running (from live WebSocket overlay) */
  liveRunningIndexes?: Set<number>;
}

type StepVisualStatus = 'not_started' | 'running' | 'completed' | 'failed' | 'suspended';

/**
 * Derive step states with run-started awareness.
 * When run has started but no steps executed yet, show first step as "running".
 *
 * Matches executed steps to planned steps by NAME (workflow step identifier),
 * not by number.  After resume, step.number is local to the execution segment
 * and does not correspond to the absolute workflow position.
 */
function deriveStepStates(
  plannedSteps: PlannedStep[],
  executedSteps: RunStep[],
  runStatus: string,
  liveRunningIndexes?: Set<number>,
): StepVisualStatus[] {
  // Check if any step has started executing
  const anyStepStarted = executedSteps.some(
    (s) =>
      s.status === 'running' ||
      s.status === 'completed' ||
      s.status === 'failed' ||
      s.status === 'suspended',
  );

  return plannedSteps.map((planned, index) => {
    // Live WebSocket overlay takes priority: if the live events say this
    // step is currently running, show it as running regardless of what the
    // (possibly stale) canonical data says. This is critical after retry
    // where the canonical step may still be "failed" (old attempt) while
    // a new attempt is actively executing.
    if (liveRunningIndexes?.has(index)) {
      return 'running';
    }

    const executed = findExecutedStepForPlanned(executedSteps, planned);

    // If we have an executed step, use its status
    if (executed) {
      if (executed.status === 'running') return 'running';
      if (executed.status === 'completed') return 'completed';
      if (executed.status === 'failed') return 'failed';
      if (executed.status === 'suspended') return 'suspended';
      return 'not_started';
    }

    // Special case: first step shows "running" when the run is actively
    // running but no step has persisted yet. Restricted to runStatus ===
    // 'running' so a run that failed/suspended before any step executed (e.g.
    // a planner/compile failure) does NOT render a live blue pulse under a red
    // "Failed" header — the live overlay must never contradict canonical state.
    if (index === 0 && runStatus === 'running' && !anyStepStarted) {
      return 'running';
    }

    return 'not_started';
  });
}

function formatDuration(ms?: number): string | null {
  if (!ms) return null;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function getStatusLabel(status: StepVisualStatus): string {
  return {
    not_started: 'Not started',
    running: 'Running',
    completed: 'Completed',
    failed: 'Failed',
    // Generic wording: a step suspends for approval OR a webhook wait, and
    // the timeline can't tell which — "Awaiting Approval" was wrong for the
    // latter.
    suspended: 'Suspended',
  }[status];
}

export function StepProgressTimeline({
  plannedSteps,
  executedSteps,
  runStatus,
  selectedStepIndex,
  onSelectStep,
  liveRunningIndexes,
}: StepProgressTimelineProps) {
  const [expandedStepIndex, setExpandedStepIndex] = useState<number | null>(null);

  if (plannedSteps.length === 0) return null;

  // Derive all step states once (considers run-started state + live overlay)
  const stepStates = deriveStepStates(plannedSteps, executedSteps, runStatus, liveRunningIndexes);

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <div className="flex items-center gap-1 relative pb-16">
        {/* Progress line */}
        <div className="absolute top-2 left-0 right-0 h-0.5 bg-slate-200" style={{ zIndex: 0 }} />

        {plannedSteps.map((planned, index) => {
          const status = stepStates[index];
          const isExpanded = expandedStepIndex === index;
          const isSelected = selectedStepIndex === index;
          const executed = findExecutedStepForPlanned(executedSteps, planned);

          // Dot colors
          const dotColor = {
            not_started: 'bg-slate-300',
            running: 'bg-blue-500 animate-pulse',
            completed: 'bg-green-500',
            failed: 'bg-red-500',
            suspended: 'bg-amber-500 animate-pulse',
          }[status];

          return (
            <div
              key={planned.id}
              className="flex-1 flex flex-col items-center gap-1.5 relative"
              style={{ zIndex: isExpanded ? 10 : 1 }}
            >
              <button
                onClick={() => {
                  if (executed) {
                    // Toggle behavior: clicking same step clears selection
                    onSelectStep(index);
                    setExpandedStepIndex(isExpanded ? null : index);
                  }
                }}
                disabled={!executed}
                className={cn(
                  'flex flex-col items-center gap-1.5',
                  executed && 'cursor-pointer',
                  !executed && 'cursor-default',
                )}
                aria-label={`Step ${index + 1}: ${planned.name}. Status: ${getStatusLabel(status)}`}
              >
                {/* Dot */}
                <div
                  className={cn(
                    'w-4 h-4 rounded-full transition-all',
                    dotColor,
                    isSelected && 'ring-2 ring-blue-400 ring-offset-2',
                    executed && 'hover:scale-125',
                  )}
                />

                {/* Step number label */}
                <div className="text-xs font-medium text-slate-700">{index + 1}</div>
              </button>

              {/* Info box on click */}
              {isExpanded && (
                <div className="absolute top-full mt-2 px-3 py-2 bg-white border border-slate-300 rounded-md shadow-md min-w-[160px] max-w-[240px] animate-in fade-in slide-in-from-top-2 duration-200">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1">
                      <div className="text-xs font-bold text-slate-900">Step {index + 1}</div>
                      <div className="text-xs text-slate-700 mt-1">{planned.name}</div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedStepIndex(null);
                      }}
                      className="text-slate-400 hover:text-slate-600 transition-colors"
                      aria-label="Close"
                    >
                      <svg
                        className="w-3 h-3"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M6 18L18 6M6 6l12 12"
                        />
                      </svg>
                    </button>
                  </div>
                  {/* Arrow */}
                  <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-white border-l border-t border-slate-300 rotate-45" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-4 mt-3 text-xs text-slate-600">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-slate-300" />
          <span>Not started</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-blue-500" />
          <span>Running</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-green-500" />
          <span>Completed</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-red-500" />
          <span>Failed</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-amber-500" />
          <span>Suspended</span>
        </div>
      </div>
    </div>
  );
}
