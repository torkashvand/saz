'use client';

import { useParams, useRouter } from 'next/navigation';
import { useState, useMemo } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useRunDetails, useResumeRun } from '@/lib/hooks';
import { api } from '@/lib/api';
import { useErrorToast } from '@/lib/use-error-toast';
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
import { buildDisplaySteps, resolveCanonicalStepIndex } from '@/lib/runs/display-steps';

type ViewMode = 'steps' | 'steps-console' | 'cost';

export default function RunDetailPageRedesign() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useErrorToast();
  const { data: run, isLoading, error } = useRunDetails(runId);
  const { events } = useRunEvents(runId);
  const metrics = useRunMetrics(run);

  const [viewMode, setViewMode] = useState<ViewMode>('steps');
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(null);
  const [drawerStepId, setDrawerStepId] = useState<string | null>(null);

  // Derive running state from BOTH canonical data and live events.
  // Canonical run.status may still be "queued" for a brief period after
  // execution starts (until the cache invalidation refetch completes).
  // The live event stream tells us immediately that the run is active.
  const isRunningCanonical = run?.status === 'running' || run?.status === 'pending';
  const isRunningFromEvents = useMemo(() => {
    // Walk events in order; the last run-lifecycle event determines state.
    let active = false;
    for (const e of events) {
      if (e.event_type === 'run.started' || e.event_type === 'run.resumed') {
        active = true;
      } else if (
        e.event_type === 'run.completed' ||
        e.event_type === 'run.failed' ||
        e.event_type === 'run.suspended'
      ) {
        active = false;
      }
    }
    return active;
  }, [events]);
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
    ? `${(process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')}/api/v1/webhooks/callback/${webhookError.callback_id}`
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
    const running = new Set<number>();
    if (!run?.planned_steps) return running;

    events.forEach((event) => {
      // Run-level terminal / pause events: clear ALL running indicators.
      // When a run suspends (approval gate), completes, or fails, no step
      // should remain in the live "running" set.  Without this, a step
      // that was started before suspension stays falsely lit as running,
      // and after retry/resume the UI shows two running steps at once.
      if (
        event.event_type === 'run.suspended' ||
        event.event_type === 'run.completed' ||
        event.event_type === 'run.failed'
      ) {
        running.clear();
        return;
      }

      // Step-level suspension (approval step marked suspended)
      if (event.event_type === 'step.suspended') {
        const idx = resolveCanonicalStepIndex(event, run.steps, run.planned_steps);
        if (idx !== undefined) running.delete(idx);
        return;
      }

      // Step lifecycle: started adds, completed/failed removes
      if (
        event.event_type !== 'step.started' &&
        event.event_type !== 'step.completed' &&
        event.event_type !== 'step.failed'
      ) {
        return;
      }

      const canonicalIndex = resolveCanonicalStepIndex(event, run.steps, run.planned_steps);

      if (canonicalIndex !== undefined) {
        if (event.event_type === 'step.started') {
          running.add(canonicalIndex);
        } else {
          running.delete(canonicalIndex);
        }
      }
    });

    return running;
  }, [events, run?.steps, run?.planned_steps]);

  // Build display steps based on planner mode, then overlay live running state.
  //
  // The canonical source of truth is run.steps (persisted). The WebSocket
  // events provide a live overlay so the operator sees which step is
  // currently executing without waiting for the next API poll.
  //
  // After retry, the canonical step may still be "failed" (old attempt)
  // while a new attempt is running. The overlay must handle BOTH cases:
  //   1. kind === 'planned' (step never executed) → create synthetic step
  //   2. kind === 'executed' but status is terminal (failed/completed from
  //      an older attempt) → override with running status for the new attempt
  // When the run is active but no step.started event has arrived yet
  // (planner is generating the plan), infer which step will run next
  // so both the step cards AND the timeline show immediate feedback.
  const effectiveRunningIndexes = useMemo(() => {
    if (runningStepNumbers.size > 0 || !isRunningFromEvents || !run) {
      return runningStepNumbers;
    }
    const steps = buildDisplaySteps(run.planner_mode as any, run.planned_steps, run.steps);
    const nextStep = steps.find(
      (s) => s.kind === 'planned' || (s.kind === 'executed' && s.step.status === 'failed'),
    );
    if (nextStep !== undefined) {
      const inferred = new Set(runningStepNumbers);
      inferred.add(nextStep.index);
      return inferred;
    }
    return runningStepNumbers;
  }, [runningStepNumbers, isRunningFromEvents, run]);

  const displaySteps = useMemo(() => {
    if (!run) return [];
    const steps = buildDisplaySteps(run.planner_mode as any, run.planned_steps, run.steps);

    // Enhance with real-time running status from WebSocket
    // (effectiveRunningIndexes includes both confirmed step.started
    // events AND the inferred next-step during the planning gap)
    return steps.map((displayStep) => {
      if (!effectiveRunningIndexes.has(displayStep.index)) {
        return displayStep;
      }

      if (displayStep.kind === 'planned') {
        // Step never executed — create a synthetic running step
        return {
          ...displayStep,
          kind: 'executed' as const,
          step: {
            id: `ws-running-${displayStep.index}`,
            number: displayStep.index,
            name: displayStep.planned.name,
            attempt: 1,
            step_type: displayStep.planned.step_type || 'unknown',
            status: 'running' as const,
            retry_count: 0,
          },
        };
      }

      // Step already has a canonical record (e.g. failed from a previous
      // attempt). Override to show it as running with the next attempt number.
      if (displayStep.kind === 'executed' && displayStep.step.status !== 'running') {
        return {
          ...displayStep,
          step: {
            ...displayStep.step,
            status: 'running' as const,
            // Signal that this is the next attempt beyond what's persisted
            attempt: displayStep.step.attempt + 1,
          },
        };
      }

      return displayStep;
    });
  }, [run, effectiveRunningIndexes]);

  // Retry mutation (same-run semantics — stays on this page)
  const retryMutation = useMutation({
    mutationFn: () => api.retryRun(runId),
    onSuccess: () => {
      showSuccess('Retrying from failing step...');
      queryClient.invalidateQueries({ queryKey: ['run', runId] });
      queryClient.invalidateQueries({ queryKey: ['runGraph', runId] });
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

  // Scroll to step (handles both planned and executed)
  const scrollToStep = (index: number) => {
    setTimeout(() => {
      // Try to find the executed step first
      const executedStep = run?.steps.find((s) => s.number === index);
      const stepId = executedStep?.id || `planned-${index}`;

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
          onRetry={() => retryMutation.mutate()}
          onConfigureCredential={() => router.push('/credentials')}
          isRetrying={retryMutation.isPending}
        />
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
                selectedStepIndex={selectedStepIndex}
                onSelectStep={handleSelectStep}
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
            selectedStepIndex={drawerStep?.number ?? null}
            onSelectStep={() => {}}
            onClearStepFilter={() => setDrawerStepId(null)}
          />
        </BottomDrawer>
      )}
    </div>
  );
}
