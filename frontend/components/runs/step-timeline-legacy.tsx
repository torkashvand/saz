'use client';

import { useState, useMemo, useEffect, useRef } from 'react';
import { Filter, ChevronDown, ChevronUp } from 'lucide-react';
import { CompactStepCard } from './step-card';
import { Button } from '@/components/ui/button';
import { StatusPill } from '@/components/ui/status-badge';
import { PlannedStepPill } from './planned-step-pill';
import type { RunStep, StepStatus, PlannedStep } from '@/lib/types';

interface StepTimelineProps {
  steps: RunStep[];
  plannedSteps: PlannedStep[];
  selectedStepId: string | null;
  expandedSteps: Set<string>;
  onSelectStep: (stepId: string | null) => void;
  onToggleStep: (stepId: string) => void;
}

type FilterType = 'all' | 'completed' | 'failed' | 'running';

export function StepTimeline({
  steps,
  plannedSteps,
  selectedStepId,
  expandedSteps,
  onSelectStep,
  onToggleStep,
}: StepTimelineProps) {
  const [filter, setFilter] = useState<FilterType>('all');

  // Use planned steps if available, fallback to executed steps
  const displaySteps = plannedSteps.length > 0 ? plannedSteps : [];
  const totalSteps = displaySteps.length || steps.length;

  // Filter steps based on selected filter
  const filteredSteps = useMemo(() => {
    if (filter === 'all') return steps;

    return steps.filter((step) => {
      if (filter === 'completed') {
        return step.status === 'completed';
      }
      if (filter === 'failed') {
        return step.status === 'failed';
      }
      if (filter === 'running') {
        return step.status === 'running';
      }
      return true;
    });
  }, [steps, filter]);

  // Calculate stats for filter pills
  const stats = useMemo(() => {
    const completed = steps.filter((s) => s.status === 'completed').length;
    const failed = steps.filter((s) => s.status === 'failed').length;
    const running = steps.filter((s) => s.status === 'running').length;

    return { completed, failed, running, total: steps.length };
  }, [steps]);

  const handleExpandAll = () => {
    const allStepIds = new Set(steps.map((s) => s.id));
    steps.forEach((step) => {
      if (!expandedSteps.has(step.id)) {
        onToggleStep(step.id);
      }
    });
  };

  const handleCollapseAll = () => {
    steps.forEach((step) => {
      if (expandedSteps.has(step.id)) {
        onToggleStep(step.id);
      }
    });
  };

  const handleStepClick = (stepId: string) => {
    onSelectStep(selectedStepId === stepId ? null : stepId);

    // Expand the step if not already expanded
    if (!expandedSteps.has(stepId)) {
      onToggleStep(stepId);
    }

    // Scroll to the step card
    setTimeout(() => {
      const element = document.querySelector(`[data-step-id="${stepId}"]`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 100);
  };

  return (
    <div className="flex flex-col h-full bg-slate-50">
      {/* Mini step navigator */}
      <div className="p-4 bg-white border-b border-slate-200">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-slate-900">Steps ({stats.total})</h2>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleExpandAll}
              className="text-xs"
            >
              <ChevronDown className="h-3 w-3 mr-1" />
              Expand all
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCollapseAll}
              className="text-xs"
            >
              <ChevronUp className="h-3 w-3 mr-1" />
              Collapse all
            </Button>
          </div>
        </div>

        {/* Mini overview - show all planned steps from the start */}
        <div className="grid grid-cols-6 gap-2">
          {displaySteps.length > 0 ? (
            displaySteps.map((planned) => {
              // Find matching executed step by index
              const executedStep = steps.find(s => s.number === planned.index);
              const isSelected = executedStep ? executedStep.id === selectedStepId : false;

              return (
                <PlannedStepPill
                  key={planned.id}
                  planned={planned}
                  executedStep={executedStep}
                  isSelected={isSelected}
                  onClick={() => {
                    if (executedStep) {
                      handleStepClick(executedStep.id);
                    }
                  }}
                />
              );
            })
          ) : (
            // Fallback for agentic mode or when planned_steps not available
            steps.map((step, idx) => {
              const isSelected = step.id === selectedStepId;
              const statusColor =
                step.status === 'completed'
                  ? 'bg-green-500'
                  : step.status === 'failed'
                    ? 'bg-red-500'
                    : step.status === 'running'
                      ? 'bg-blue-500'
                      : 'bg-slate-300';

              return (
                <button
                  key={step.id}
                  onClick={() => handleStepClick(step.id)}
                  className={`
                    h-8 rounded text-xs font-medium transition-all
                    ${isSelected ? 'ring-2 ring-blue-400 ring-offset-2' : ''}
                    ${statusColor} text-white hover:opacity-90
                  `}
                  title={`${idx + 1}. ${step.name} (${step.status})`}
                >
                  {idx + 1}
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="p-4 bg-white border-b border-slate-200">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-medium text-slate-700">Filter:</span>
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => setFilter('all')}
              className={`
                px-3 py-1 rounded-full text-xs font-medium transition-colors
                ${
                  filter === 'all'
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }
              `}
            >
              All ({stats.total})
            </button>
            <button
              onClick={() => setFilter('completed')}
              className={`
                px-3 py-1 rounded-full text-xs font-medium transition-colors
                ${
                  filter === 'completed'
                    ? 'bg-green-600 text-white'
                    : 'bg-green-50 text-green-700 hover:bg-green-100'
                }
              `}
            >
              Completed ({stats.completed})
            </button>
            <button
              onClick={() => setFilter('failed')}
              className={`
                px-3 py-1 rounded-full text-xs font-medium transition-colors
                ${
                  filter === 'failed'
                    ? 'bg-red-600 text-white'
                    : 'bg-red-50 text-red-700 hover:bg-red-100'
                }
              `}
            >
              Failed ({stats.failed})
            </button>
            <button
              onClick={() => setFilter('running')}
              className={`
                px-3 py-1 rounded-full text-xs font-medium transition-colors
                ${
                  filter === 'running'
                    ? 'bg-blue-600 text-white'
                    : 'bg-blue-50 text-blue-700 hover:bg-blue-100'
                }
              `}
            >
              Running ({stats.running})
            </button>
          </div>
        </div>

        {filter !== 'all' && (
          <p className="text-xs text-slate-500 mt-2">
            Showing {filteredSteps.length} of {stats.total} steps
          </p>
        )}
      </div>

      {/* Steps list */}
      <div className="flex-1 overflow-y-auto p-4">
        {filteredSteps.length === 0 ? (
          <div className="text-center py-12 text-slate-500">
            <p className="text-sm">No steps match the current filter</p>
          </div>
        ) : (
          filteredSteps.map((step, idx) => (
            <CompactStepCard
              key={step.id}
              step={step}
              isSelected={step.id === selectedStepId}
            />
          ))
        )}
      </div>
    </div>
  );
}
