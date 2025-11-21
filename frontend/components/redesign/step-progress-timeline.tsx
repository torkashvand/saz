'use client';

import { cn } from '@/lib/utils';
import type { PlannedStep, RunStep } from '@/lib/types';

interface StepProgressTimelineProps {
  plannedSteps: PlannedStep[];
  executedSteps: RunStep[];
  selectedStepIndex: number | null;
  onSelectStep: (index: number) => void;
}

type StepVisualStatus = 'not_started' | 'running' | 'completed' | 'failed';

function getStepStatus(planned: PlannedStep, executedSteps: RunStep[]): StepVisualStatus {
  const executed = executedSteps.find(s => s.number === planned.index);
  if (!executed) return 'not_started';

  if (executed.status === 'running') return 'running';
  if (executed.status === 'completed' || executed.status === 'success') return 'completed';
  if (executed.status === 'failed') return 'failed';
  return 'not_started';
}

export function StepProgressTimeline({
  plannedSteps,
  executedSteps,
  selectedStepIndex,
  onSelectStep,
}: StepProgressTimelineProps) {
  if (plannedSteps.length === 0) return null;

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <div className="flex items-center gap-1 relative">
        {/* Progress line */}
        <div className="absolute top-2 left-0 right-0 h-0.5 bg-slate-200" style={{ zIndex: 0 }} />

        {plannedSteps.map((planned, index) => {
          const status = getStepStatus(planned, executedSteps);
          const isSelected = selectedStepIndex === index;
          const executed = executedSteps.find(s => s.number === planned.index);

          // Dot colors
          const dotColor = {
            not_started: 'bg-slate-300',
            running: 'bg-blue-500 animate-pulse',
            completed: 'bg-green-500',
            failed: 'bg-red-500',
          }[status];

          return (
            <button
              key={planned.id}
              onClick={() => executed && onSelectStep(index)}
              disabled={!executed}
              className={cn(
                'flex-1 flex flex-col items-center gap-1.5 relative group',
                executed && 'cursor-pointer',
                !executed && 'cursor-default'
              )}
              style={{ zIndex: 1 }}
              title={`Step ${index + 1}: ${planned.name}`}
            >
              {/* Dot */}
              <div
                className={cn(
                  'w-4 h-4 rounded-full transition-all',
                  dotColor,
                  isSelected && 'ring-2 ring-blue-400 ring-offset-2',
                  executed && 'hover:scale-125'
                )}
              />

              {/* Label */}
              <div className="text-center">
                <div className="text-xs font-medium text-slate-700">
                  {index + 1}
                </div>
                {/* Show name on hover or for selected/failed steps */}
                {(isSelected || status === 'failed') && (
                  <div className="text-xs text-slate-500 max-w-[80px] truncate">
                    {planned.name.slice(0, 20)}
                  </div>
                )}
              </div>
            </button>
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
      </div>
    </div>
  );
}