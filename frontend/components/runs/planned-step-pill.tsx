'use client';

import { cn } from '@/lib/utils';
import type { PlannedStep, RunStep } from '@/lib/types';

type StepVisualStatus = 'not_started' | 'running' | 'completed' | 'failed' | 'skipped';

interface PlannedStepPillProps {
  planned: PlannedStep;
  executedStep?: RunStep;
  isSelected: boolean;
  onClick: () => void;
}

function getVisualStatus(executedStep?: RunStep): StepVisualStatus {
  if (!executedStep) return 'not_started';

  switch (executedStep.status) {
    case 'running':
      return 'running';
    case 'completed':
      return 'completed';
    case 'failed':
      return 'failed';
    case 'queued':
      return 'not_started';
    case 'suspended':
      return 'skipped';
    default:
      return 'not_started';
  }
}

export function PlannedStepPill({
  planned,
  executedStep,
  isSelected,
  onClick,
}: PlannedStepPillProps) {
  const status = getVisualStatus(executedStep);

  // Status colors and styles
  const statusStyles = {
    not_started: 'bg-slate-100 text-slate-500 border-slate-200',
    running: 'bg-blue-100 text-blue-700 border-blue-300 animate-pulse',
    completed: 'bg-green-100 text-green-700 border-green-300',
    failed: 'bg-red-100 text-red-700 border-red-300',
    skipped: 'bg-slate-50 text-slate-400 border-slate-200 line-through',
  };

  return (
    <button
      onClick={onClick}
      title={`Step ${planned.index + 1}: ${planned.name}`}
      className={cn(
        'flex items-center justify-center',
        'w-8 h-8 rounded-md border',
        'text-xs font-medium',
        'transition-all duration-200',
        'hover:scale-110 hover:shadow-sm',
        'focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-1',
        statusStyles[status],
        isSelected && 'ring-2 ring-blue-500 ring-offset-2 scale-110'
      )}
      aria-label={`Step ${planned.index + 1}: ${planned.name} - ${status.replace('_', ' ')}`}
      aria-pressed={isSelected}
    >
      {planned.index + 1}
    </button>
  );
}