'use client';

import { useParams, useRouter } from 'next/navigation';
import { useState, useMemo } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useRunDetails, useResumeRun } from '@/lib/hooks';
import { api, API_BASE_URL } from '@/lib/api';
import { useErrorToast } from '@/lib/use-error-toast';
import { useAuth } from '@/lib/auth';
import type { HumanApprovalError, WebhookWaitError } from '@/lib/types';
import { useRunEvents } from '@/lib/use-run-events';
import { useRunMetrics } from '@/lib/use-run-metrics';
import { ErrorBanner } from '@/components/ui/error-banner';
import { RunSummaryCards } from '@/components/runs/summary-cards';
import { RunHeader } from '@/components/runs/run-header';
import { StepProgressTimeline } from '@/components/runs/step-timeline';
import { CompactStepCard } from '@/components/runs/step-card';
import { BottomDrawer } from '@/components/common/bottom-drawer';
import { CostMetricsView } from '@/components/metrics/cost-view';
import { EnhancedConsolePanel } from '@/components/runs/console-panel';
import { ResizableSplit } from '@/components/ui/resizable-split';
import { HumanApprovalPanel } from '@/components/runs/human-approval-panel';
import { WebhookCallbackPanel } from '@/components/runs/webhook-callback-panel';
import { ArtifactsPanel } from '@/components/runs/artifacts-panel';
import { buildDisplaySteps } from '@/lib/runs/display-steps';
import {
  applyLiveOverlay,
  computeEffectiveRunningIndexes,
  deriveIsRunningFromEvents,
  deriveRunningIndexes,
} from '@/lib/runs/live-overlay';

type ViewMode = 'steps' | 'steps-console' | 'cost';

export default function RunDetailPageRedesign() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useErrorToast();
  const { canWrite } = useAuth();
  const { events, isConnected, connectionError, retry: retryStream } = useRunEvents(runId);
  // Fall back to polling while the live stream is down so the page can't freeze
  // on a stale snapshot when the WebSocket silently dies.
  const { data: run, isLoading, error } = useRunDetails(runId, isConnected ? false : 5000);
  const metrics = useRunMetrics(run);

  const [viewMode, setViewMode] = useState<ViewMode>('steps');
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(null);
  const [drawerStepId, setDrawerStepId] = useState<string | null>(null);

  // Derive running state from BOTH canonical data and live events.
  // Canonical run.status may still be "queued" for a brief period after
  // execution starts (until the cache invalidation refetch completes).
  // The live event stream tells us immediately that the run is active —
  // but a terminal canonical status always wins over the event buffer,
  // which is capped and may be missing the terminal event (see
  // lib/runs/live-overlay.ts).
  const isRunningCanonical = run?.status === 'running';
  const isRunningFromEvents = useMemo(
    () => deriveIsRunningFromEvents(events, run?.status),
    [events, run?.status],
  );
  const isRunning = isRunningCanonical || isRunningFromEvents;
  const isSuspended = run?.status === 'suspended';

  // Detect human approval requirement from run.error
  const approvalError: HumanApprovalError | null =
    isSuspended && run?.error?.type === 'HumanApprovalRequired'
      ? (run.error as HumanApprovalError)
      : null;

  // Detect webhook.wait suspension. The same callback_id mechanism powers
  // both human.approval and webhook.wait, but for webhook.wait there is no
  // approver workflow — operators (or external systems) just POST to the
  // callback URL to resume.
  const webhookError: WebhookWaitError | null =
    isSuspended && run?.error?.type === 'WebhookWait' ? (run.error as WebhookWaitError) : null;
  const webhookCallbackUrl = webhookError
    ? `${API_BASE_URL.replace(/\/$/, '')}/api/v1/webhooks/callback/${webhookError.callback_id}`
    : '';

  // Resume mutation
  const resumeMutation = useResumeRun(runId);

  // Webhook callback mutation — calls the webhook endpoint directly rather
  // than /resume, so duplicate callbacks are handled idempotently by the
  // backend and the audit trail records a webhook.callback_received event.
  const callbackMutation = useMutation({
    mutationFn: (body: {
      action: 'approve' | 'reject';
      reason?: string;
      data?: Record<string, unknown>;
    }) => {
      if (!webhookError) {
        return Promise.reject(new Error('No callback_id available'));
      }
      return api.sendWebhookCallback(webhookError.callback_id, body);
    },
    onSuccess: (resp) => {
      if (resp.status === 'rejected') {
        showSuccess('Callback rejected; run marked as failed.');
      } else if (resp.status === 'already_processed') {
        showSuccess(`Callback already processed (${resp.message}).`);
      } else {
        showSuccess('Callback accepted; run resuming.');
      }
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
    onError: showError,
  });

  // Track running steps from WebSocket events.
  // Resolves events to canonical planned-step positions by step NAME,
  // not by the local step_number in the event payload.  After resume,
  // step_number restarts from 0 for the remaining sub-plan, so using it
  // directly would incorrectly light up the first workflow bullet.
  const runningStepNumbers = useMemo(() => {
    if (!run?.planned_steps) return new Set<number>();
    return deriveRunningIndexes(events, run.steps, run.planned_steps, run.status);
  }, [events, run?.steps, run?.planned_steps, run?.status]);

  // When the run is active but no step.started event has arrived yet
  // (planner is generating the plan), infer which step will run next
  // so both the step cards AND the timeline show immediate feedback.
  const effectiveRunningIndexes = useMemo(() => {
    if (!run) return runningStepNumbers;
    return computeEffectiveRunningIndexes(
      runningStepNumbers,
      isRunningFromEvents,
      run.planner_mode,
      run.planned_steps,
      run.steps,
    );
  }, [runningStepNumbers, isRunningFromEvents, run]);

  // Build display steps based on planner mode, then overlay live running
  // state (effectiveRunningIndexes includes both confirmed step.started
  // events AND the inferred next-step during the planning gap).
  const displaySteps = useMemo(() => {
    if (!run) return [];
    const steps = buildDisplaySteps(run.planner_mode, run.planned_steps, run.steps);
    return applyLiveOverlay(steps, effectiveRunningIndexes);
  }, [run, effectiveRunningIndexes]);

  // Retry mutation (same-run semantics — stays on this page)
  const retryMutation = useMutation({
    mutationFn: () => api.retryRun(runId),
    onSuccess: () => {
      showSuccess('Retrying from failing step...');
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
    onError: showError,
  });

  const handleApprove = (data: { approved: true; approver?: string; comments?: string }) => {
    resumeMutation.mutate(
      { resume_data: data },
      {
        onSuccess: () => showSuccess('Run approved and resumed'),
        onError: showError,
      },
    );
  };

  const handleReject = (data: { approved: false; approver?: string; reason: string }) => {
    resumeMutation.mutate(
      { resume_data: data },
      {
        onSuccess: () => showSuccess('Run rejected'),
        onError: showError,
      },
    );
  };

  // Resolve a canonical display index to the executed step's DB id (if any).
  // buildDisplaySteps already maps canonical positions to the latest attempt,
  // so this is safe across resume — unlike run.steps.find(s.number === index),
  // where the segment-local number diverges from the canonical index.
  const executedStepIdByIndex = useMemo(() => {
    const map = new Map<number, string>();
    for (const ds of displaySteps) {
      if (ds.kind === 'executed') map.set(ds.index, ds.step.id);
    }
    return map;
  }, [displaySteps]);

  // The console filters by step id; resolve the selected canonical index to it.
  const selectedStepId = useMemo(
    () =>
      selectedStepIndex === null ? null : (executedStepIdByIndex.get(selectedStepIndex) ?? null),
    [selectedStepIndex, executedStepIdByIndex],
  );

  // A console step badge reports the step id; map it back to the canonical index.
  const handleConsoleSelectStep = (stepId: string) => {
    for (const [index, id] of executedStepIdByIndex) {
      if (id === stepId) {
        handleSelectStep(index);
        return;
      }
    }
  };

  // Scroll to step (handles both planned and executed)
  const scrollToStep = (index: number) => {
    setTimeout(() => {
      const stepId = executedStepIdByIndex.get(index) || `planned-${index}`;

      const element = document.querySelector(`[data-step-id="${stepId}"]`);
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
    // Toggle behavior: clicking the same step clears the filter
    if (selectedStepIndex === index) {
      setSelectedStepIndex(null);
    } else {
      setSelectedStepIndex(index);
      scrollToStep(index);
    }
  };

  const handleStepCardClick = (stepNumber: number) => {
    // Toggle behavior: clicking the same step clears the filter
    if (selectedStepIndex === stepNumber) {
      setSelectedStepIndex(null);
    } else {
      setSelectedStepIndex(stepNumber);
      // Optionally scroll wizard into view if needed
      const wizardElement = document.querySelector('[data-step-wizard]');
      if (wizardElement) {
        const rect = wizardElement.getBoundingClientRect();
        // Only scroll if wizard is out of view
        if (rect.top < 0 || rect.bottom > window.innerHeight) {
          wizardElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      }
    }
  };

  const handleClearStepFilter = () => {
    setSelectedStepIndex(null);
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

  const drawerStep = drawerStepId ? run.steps.find((s) => s.id === drawerStepId) : null;

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
          onRetry={canWrite ? () => retryMutation.mutate() : undefined}
          onConfigureCredential={() => router.push('/credentials')}
          isRetrying={retryMutation.isPending}
        />
      </div>

      {/* Live-stream disconnect notice. Without the stream the page relies on
          the polling fallback, so tell the operator the view may lag and let
          them force a reconnect. */}
      {connectionError && !isConnected && (
        <div className="mb-6 flex items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <span>Live updates disconnected — refreshing periodically instead.</span>
          <button
            onClick={retryStream}
            className="rounded border border-amber-300 bg-amber-100 px-3 py-1 font-medium hover:bg-amber-200"
          >
            Reconnect
          </button>
        </div>
      )}

      {/* Downloadable artifacts (rendered documents, audit records) */}
      <div className="mb-6">
        <ArtifactsPanel runId={run.id} />
      </div>

      {/* Human Approval Panel */}
      {approvalError && (
        <div className="mb-6">
          <HumanApprovalPanel
            approvalError={approvalError}
            run={run}
            onApprove={handleApprove}
            onReject={handleReject}
            isPending={resumeMutation.isPending}
          />
        </div>
      )}

      {/* Webhook Callback Panel — surfaces the callback URL and an in-UI
          send button when a run is suspended on a webhook.wait step. */}
      {webhookError && (
        <div className="mb-6">
          <WebhookCallbackPanel
            webhookError={webhookError}
            callbackUrl={webhookCallbackUrl}
            onSendCallback={async (body) => {
              await callbackMutation.mutateAsync(body);
            }}
            isPending={callbackMutation.isPending}
          />
        </div>
      )}

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
      {(viewMode === 'steps' || viewMode === 'steps-console') &&
        run.planned_steps &&
        run.planned_steps.length > 0 && (
          <div className="mb-6" data-step-wizard>
            <StepProgressTimeline
              plannedSteps={run.planned_steps}
              executedSteps={run.steps}
              runStatus={isRunning ? 'running' : run.status}
              selectedStepIndex={selectedStepIndex}
              onSelectStep={handleSelectStep}
              liveRunningIndexes={effectiveRunningIndexes}
            />
          </div>
        )}

      {/* Content area */}
      {viewMode === 'steps' && (
        <div className="space-y-3">
          {displaySteps.map((displayStep) => (
            <CompactStepCard
              key={
                displayStep.kind === 'executed'
                  ? displayStep.step.id
                  : `planned-${displayStep.index}`
              }
              displayStep={displayStep}
              isSelected={selectedStepIndex === displayStep.index}
              onViewLogs={
                displayStep.kind === 'executed'
                  ? () => setDrawerStepId(displayStep.step.id)
                  : undefined
              }
              onCardClick={() => handleStepCardClick(displayStep.index)}
            />
          ))}
        </div>
      )}

      {viewMode === 'steps-console' && (
        <div className="border rounded-lg overflow-hidden bg-white" style={{ height: '70vh' }}>
          <ResizableSplit
            left={
              <div className="h-full overflow-y-auto p-4 space-y-3 bg-slate-50">
                {displaySteps.map((displayStep) => (
                  <CompactStepCard
                    key={
                      displayStep.kind === 'executed'
                        ? displayStep.step.id
                        : `planned-${displayStep.index}`
                    }
                    displayStep={displayStep}
                    isSelected={selectedStepIndex === displayStep.index}
                    onViewLogs={
                      displayStep.kind === 'executed'
                        ? () => setSelectedStepIndex(displayStep.index)
                        : undefined
                    }
                    onCardClick={() => handleStepCardClick(displayStep.index)}
                  />
                ))}
              </div>
            }
            right={
              <EnhancedConsolePanel
                events={events}
                steps={run.steps}
                selectedStepId={selectedStepId}
                onSelectStep={handleConsoleSelectStep}
                onClearStepFilter={handleClearStepFilter}
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
            onClearStepFilter={() => setDrawerStepId(null)}
          />
        </BottomDrawer>
      )}
    </div>
  );
}
