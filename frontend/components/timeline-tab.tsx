'use client';

import { useState } from 'react';
import { Eye, EyeOff, LayoutPanelLeft } from 'lucide-react';
import { Button } from './ui/button';
import { SimplifiedStepCard } from './simplified-step-card';
import { EnhancedConsolePanel } from './enhanced-console-panel';
import { ResizableSplit } from './ui/resizable-split';
import type { RunStep, Event } from '@/lib/types';

interface TimelineTabProps {
  steps: RunStep[];
  events: Event[];
  runId: string;
}

/**
 * Timeline tab with optional split view for logs.
 *
 * Design principles:
 * - Steps list is primary content (non-technical friendly)
 * - Logs panel is optional and can be toggled on/off
 * - When logs panel is visible, use resizable split view
 * - Clicking "View logs for this step" filters logs to that step
 */
export function TimelineTab({ steps, events, runId }: TimelineTabProps) {
  const [showLogsPanel, setShowLogsPanel] = useState(false);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);

  const handleViewStepLogs = (stepId: string) => {
    setSelectedStepId(stepId);
    setShowLogsPanel(true);
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            Execution Timeline
          </h2>
          <p className="text-sm text-slate-500 mt-1">
            {steps.length} step{steps.length !== 1 ? 's' : ''} in this run
          </p>
        </div>

        {/* Toggle logs panel */}
        <Button
          variant={showLogsPanel ? 'default' : 'outline'}
          onClick={() => setShowLogsPanel(!showLogsPanel)}
          className="gap-2"
        >
          {showLogsPanel ? (
            <>
              <EyeOff className="h-4 w-4" />
              Hide Logs Panel
            </>
          ) : (
            <>
              <Eye className="h-4 w-4" />
              Show Logs Panel
            </>
          )}
        </Button>
      </div>

      {/* Content */}
      {showLogsPanel ? (
        /* Split view: steps on left, logs on right */
        <div className="border rounded-lg overflow-hidden" style={{ height: 'calc(100vh - 450px)', minHeight: '600px' }}>
          <ResizableSplit
            left={
              <div className="h-full overflow-y-auto p-4 space-y-3">
                {steps.map((step) => (
                  <SimplifiedStepCard
                    key={step.id}
                    number={step.number}
                    name={step.name}
                    description={step.step_type}
                    status={step.status}
                    durationMs={step.duration_ms}
                    input={step.input}
                    output={step.output}
                    failureReason={step.error?.message}
                    onViewLogs={() => handleViewStepLogs(step.id)}
                  />
                ))}
              </div>
            }
            right={
              <EnhancedConsolePanel
                events={events}
                steps={steps}
                selectedStepId={selectedStepId}
                onSelectStep={setSelectedStepId}
              />
            }
            defaultLeftWidth={40}
            minLeftWidth={30}
            minRightWidth={40}
            storageKey={`timeline-split-${runId}`}
          />
        </div>
      ) : (
        /* Steps-only view */
        <div className="space-y-3">
          {steps.map((step) => (
            <SimplifiedStepCard
              key={step.id}
              number={step.number}
              name={step.name}
              description={step.step_type}
              status={step.status}
              durationMs={step.duration_ms}
              input={step.input}
              output={step.output}
              failureReason={step.error?.message}
              onViewLogs={() => handleViewStepLogs(step.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
