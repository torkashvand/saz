'use client';

import { useParams, useRouter } from 'next/navigation';
import { useState, useRef, useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useRunDetails } from '@/lib/hooks';
import { api } from '@/lib/api';
import { useErrorToast } from '@/lib/use-error-toast';
import { useRunEvents } from '@/lib/use-run-events';
import { useRunMetrics } from '@/lib/use-run-metrics';
import { buildErrorSummary } from '@/lib/error-enrichment';
import { ErrorBanner } from '@/components/ui/error-banner';
import { RunSummaryCards } from '@/components/runs/summary-cards';
import { RunHeader } from '@/components/runs/run-header';
import { StepProgressTimeline } from '@/components/runs/step-timeline';
import { CompactStepCard } from '@/components/runs/step-card';
import { BottomDrawer } from '@/components/common/bottom-drawer';
import { CostMetricsView } from '@/components/metrics/cost-view';
import { EnhancedConsolePanel } from '@/components/runs/console-panel';
import { ResizableSplit } from '@/components/ui/resizable-split';

type ViewMode = 'steps' | 'steps-console' | 'cost';

export default function RunDetailPageRedesign() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;
  const { showError, showSuccess } = useErrorToast();
  const { data: run, isLoading, error } = useRunDetails(runId);
  const { events } = useRunEvents(runId);
  const metrics = useRunMetrics(run);

  const [viewMode, setViewMode] = useState<ViewMode>('steps');
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(null);
  const [drawerStepId, setDrawerStepId] = useState<string | null>(null);

  const stepRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const isRunning = run?.status === 'running' || run?.status === 'pending';

  // Retry mutation
  const retryMutation = useMutation({
    mutationFn: () => api.retryRun(runId),
    onSuccess: (data) => {
      showSuccess(`New run created: ${data.new_run_id.slice(0, 8)}...`);
      router.push(`/runs/${data.new_run_id}`);
    },
    onError: showError,
  });

  // Replay mutation
  const replayMutation = useMutation({
    mutationFn: (fromStep: number) => api.replayRun(runId, fromStep),
    onSuccess: (data) => {
      showSuccess(`New run created: ${data.new_run_id.slice(0, 8)}...`);
      router.push(`/runs/${data.new_run_id}`);
    },
    onError: showError,
  });

  // Scroll to step
  const scrollToStep = (index: number) => {
    const step = run?.steps.find(s => s.number === index);
    if (!step) return;

    setTimeout(() => {
      const element = document.querySelector(`[data-step-id="${step.id}"]`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // Brief highlight
        element.classList.add('ring-2', 'ring-blue-400');
        setTimeout(() => {
          element.classList.remove('ring-2', 'ring-blue-400');
        }, 1500);
      }
    }, 100);
  };

  const handleSelectStep = (index: number) => {
    setSelectedStepIndex(index);
    scrollToStep(index);
  };

  const handleReplay = () => {
    const step = prompt(`Enter step number to replay from (1-${run?.steps.length || 0}):`);
    if (step) {
      const stepNum = parseInt(step, 10);
      if (!isNaN(stepNum) && stepNum >= 1 && stepNum <= (run?.steps.length || 0)) {
        replayMutation.mutate(stepNum - 1);
      } else {
        showError(`Please enter a number between 1 and ${run?.steps.length || 0}`);
      }
    }
  };

  const handleCostRowClick = (stepNumber: number) => {
    setViewMode('steps');
    setTimeout(() => {
      setSelectedStepIndex(stepNumber);
      scrollToStep(stepNumber);
    }, 100);
  };

  if (isLoading) {
    return (
      <div className="container mx-auto px-4 py-12 flex justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (error || !run) {
    return (
      <div className="container mx-auto px-4 py-12">
        <ErrorBanner
          error={error || new Error('Run not found')}
          title="Failed to Load Run"
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  const drawerStep = drawerStepId ? run.steps.find(s => s.id === drawerStepId) : null;

  return (
    <div className="container mx-auto px-4 py-6">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-3">
          <h1 className="text-2xl font-bold text-slate-900">Run Details</h1>
          {isRunning && (
            <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 border border-blue-200">
              <div className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-500"></span>
              </div>
              <span className="text-sm font-medium text-blue-700">Live</span>
            </div>
          )}
        </div>
        <RunHeader
          run={run}
          onRetry={() => retryMutation.mutate()}
          onReplay={handleReplay}
          onConfigureCredential={() => router.push('/credentials')}
          isRetrying={retryMutation.isPending}
        />
      </div>

      {/* Summary Cards */}
      <div className="mb-6">
        <RunSummaryCards metrics={metrics} isRunning={isRunning} />
      </div>

      {/* Mode switcher */}
      <div className="mb-6">
        <div className="inline-flex items-center rounded-lg border border-slate-200 p-1 bg-white">
          <button
            onClick={() => setViewMode('steps')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              viewMode === 'steps'
                ? 'bg-slate-900 text-white'
                : 'text-slate-700 hover:text-slate-900'
            }`}
          >
            Steps
          </button>
          <button
            onClick={() => setViewMode('steps-console')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              viewMode === 'steps-console'
                ? 'bg-slate-900 text-white'
                : 'text-slate-700 hover:text-slate-900'
            }`}
          >
            Steps + Console
          </button>
          <button
            onClick={() => setViewMode('cost')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              viewMode === 'cost'
                ? 'bg-slate-900 text-white'
                : 'text-slate-700 hover:text-slate-900'
            }`}
          >
            Cost & Metrics
          </button>
        </div>
      </div>

      {/* Timeline (for Steps and Steps+Console modes) */}
      {(viewMode === 'steps' || viewMode === 'steps-console') && run.planned_steps && run.planned_steps.length > 0 && (
        <div className="mb-6">
          <StepProgressTimeline
            plannedSteps={run.planned_steps}
            executedSteps={run.steps}
            selectedStepIndex={selectedStepIndex}
            onSelectStep={handleSelectStep}
          />
        </div>
      )}

      {/* Content area */}
      {viewMode === 'steps' && (
        <div className="space-y-3">
          {run.steps.map((step) => (
            <CompactStepCard
              key={step.id}
              step={step}
              isSelected={selectedStepIndex === step.number}
              onViewLogs={() => setDrawerStepId(step.id)}
            />
          ))}
        </div>
      )}

      {viewMode === 'steps-console' && (
        <div className="border rounded-lg overflow-hidden bg-white" style={{ height: '70vh' }}>
          <ResizableSplit
            left={
              <div className="h-full overflow-y-auto p-4 space-y-3 bg-slate-50">
                {run.steps.map((step) => (
                  <CompactStepCard
                    key={step.id}
                    step={step}
                    isSelected={selectedStepIndex === step.number}
                    onViewLogs={() => setSelectedStepIndex(step.number)}
                  />
                ))}
              </div>
            }
            right={
              <EnhancedConsolePanel
                events={events}
                steps={run.steps}
                selectedStepId={selectedStepIndex !== null ? run.steps.find(s => s.number === selectedStepIndex)?.id || null : null}
                onSelectStep={(stepId) => {
                  const step = run.steps.find(s => s.id === stepId);
                  if (step) setSelectedStepIndex(step.number);
                }}
              />
            }
            defaultLeftWidth={45}
            minLeftWidth={30}
            minRightWidth={40}
            storageKey={`run-split-${runId}`}
          />
        </div>
      )}

      {viewMode === 'cost' && (
        <CostMetricsView
          steps={run.steps}
          totalTokens={metrics.totalTokens || 0}
          totalCost={metrics.totalCost || 0}
          onSelectStep={handleCostRowClick}
        />
      )}

      {/* Bottom drawer for logs (Steps mode only) */}
      {viewMode === 'steps' && (
        <BottomDrawer
          isOpen={!!drawerStepId}
          onClose={() => setDrawerStepId(null)}
          title={drawerStep ? `Logs: Step ${drawerStep.number + 1} - ${drawerStep.name}` : 'Logs'}
        >
          <EnhancedConsolePanel
            events={events}
            steps={run.steps}
            selectedStepId={drawerStepId}
            onSelectStep={() => {}}
          />
        </BottomDrawer>
      )}
    </div>
  );
}