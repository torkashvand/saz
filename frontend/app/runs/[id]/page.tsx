'use client';

import { useParams, useRouter } from 'next/navigation';
import { useState, useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { useRunDetails, useRunGraph } from '@/lib/hooks';
import { api } from '@/lib/api';
import { useErrorToast } from '@/lib/use-error-toast';
import { useRunEvents } from '@/lib/use-run-events';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Play,
  RefreshCw,
  Rewind,
  AlertCircle,
  Layout,
} from 'lucide-react';
import { CollapsibleJson } from '@/components/json-view';
import { ErrorBanner } from '@/components/ui/error-banner';
import { ErrorSummaryBanner } from '@/components/error-summary';
import { ResizableSplit } from '@/components/ui/resizable-split';
import { StepTimeline as NewStepTimeline } from '@/components/step-timeline';
import { EnhancedConsolePanel } from '@/components/enhanced-console-panel';
import { RunSummaryCards } from '@/components/run-summary-cards';
import { RunGraphView } from '@/components/run-graph-view';
import { CostMetricsTab } from '@/components/cost-metrics-tab';
import { useRunMetrics } from '@/lib/use-run-metrics';
import { buildErrorSummary } from '@/lib/error-enrichment';
import type { RunStep, StepStatus } from '@/lib/types';
import type { RemediationAction } from '@/lib/types-enhanced';

const STATUS_ICONS: Record<StepStatus, React.ReactNode> = {
  pending: <Clock className="h-5 w-5 text-slate-400" />,
  queued: <Clock className="h-5 w-5 text-slate-400" />,
  running: <Play className="h-5 w-5 text-blue-500 animate-pulse" />,
  success: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  completed: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  failed: <XCircle className="h-5 w-5 text-red-500" />,
  suspended: <Clock className="h-5 w-5 text-amber-500" />,
};

const STATUS_COLORS: Record<StepStatus, string> = {
  pending: 'bg-slate-200',
  queued: 'bg-slate-200',
  running: 'bg-blue-500',
  success: 'bg-green-500',
  completed: 'bg-green-500',
  failed: 'bg-red-500',
  suspended: 'bg-amber-500',
};

function formatDuration(ms?: number): string {
  if (!ms) return '-';
  if (ms < 1000) return `${ms}ms`;
  const seconds = (ms / 1000).toFixed(2);
  return `${seconds}s`;
}

function formatCost(cost?: number): string {
  if (!cost) return '-';
  return `$${cost.toFixed(4)}`;
}

function StepTimeline({ steps }: { steps: RunStep[] }) {
  return (
    <div className="space-y-3">
      {steps.map((step, idx) => (
        <div key={step.id} className="relative">
          {/* Vertical line connecting steps */}
          {idx < steps.length - 1 && (
            <div className="absolute left-[10px] top-[32px] w-[2px] h-[calc(100%+12px)] bg-slate-200" />
          )}

          <div className="flex items-start gap-3">
            {/* Status indicator */}
            <div className="relative z-10 flex-shrink-0">{STATUS_ICONS[step.status]}</div>

            {/* Step content */}
            <div className="flex-1 border rounded-lg overflow-hidden">
              <div className="bg-muted px-3 py-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{step.id}</span>
                </div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  {step.duration_ms && <span>{formatDuration(step.duration_ms)}</span>}
                </div>
              </div>

              {/* Step output and error display */}
              <div className="p-3 space-y-2">
                {/* Output display */}
                {step.output && Object.keys(step.output).length > 0 && (
                  <div className="border-l-4 border-green-500 bg-green-50 p-3 rounded">
                    <p className="text-xs font-medium text-green-900 mb-2">Output</p>
                    <CollapsibleJson label="Details" data={step.output} />
                  </div>
                )}

                {/* Error display */}
                {step.error && (
                  <div className="border-l-4 border-red-500 bg-red-50 p-3 rounded">
                    <p className="text-xs font-medium text-red-900 mb-1">Error</p>
                    <p className="text-xs text-red-700 whitespace-pre-wrap">
                      {typeof step.error === 'object' ? step.error.message : step.error}
                    </p>
                    {step.error?.type && (
                      <p className="text-xs text-red-600 mt-1">Type: {step.error.type}</p>
                    )}
                    {step.error?.traceback && (
                      <details className="mt-2">
                        <summary className="text-xs text-red-600 cursor-pointer hover:underline">
                          Show traceback
                        </summary>
                        <pre className="mt-2 text-xs text-red-800 bg-red-100 p-2 rounded overflow-x-auto font-mono">
                          {step.error.traceback}
                        </pre>
                      </details>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function RunDetailPage() {
  const params = useParams();
  const router = useRouter();
  const runId = params.id as string;
  const { showError, showSuccess } = useErrorToast();
  const { data: run, isLoading: isLoadingRun, error } = useRunDetails(runId);
  const { data: runGraph, isLoading: isLoadingGraph } = useRunGraph(runId);
  const { events } = useRunEvents(runId);
  const [activeTab, setActiveTab] = useState('split-view');
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());

  // Calculate metrics with proper aggregation
  const metrics = useRunMetrics(run);
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
  const [replayStep, setReplayStep] = useState<number | null>(null);
  const replayMutation = useMutation({
    mutationFn: (fromStep: number) => api.replayRun(runId, fromStep),
    onSuccess: (data) => {
      showSuccess(`New run created: ${data.new_run_id.slice(0, 8)}...`);
      router.push(`/runs/${data.new_run_id}`);
      setReplayStep(null);
    },
    onError: (error: any) => {
      showError(error);
      setReplayStep(null);
    },
  });

  if (isLoadingRun) {
    return (
      <div className="container mx-auto px-4 py-12 flex justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto px-4 py-12">
        <ErrorBanner
          error={error}
          title="Failed to Load Run"
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  if (!run) {
    return (
      <div className="container mx-auto px-4 py-12">
        <Card>
          <CardHeader>
            <CardTitle>Run Not Found</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-muted-foreground">The run with ID {runId} could not be found.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const isFailed = run.status === 'failed';
  const isSuspended = run.status === 'suspended';

  // Build error summary for failed runs
  const errorSummary = isFailed ? buildErrorSummary(run) : null;

  // Handle remediation actions
  const handleRemediationAction = (action: RemediationAction) => {
    switch (action) {
      case 'configure_credential':
        router.push('/credentials');
        break;
      case 'retry':
        retryMutation.mutate();
        break;
      case 'fix_input_data':
        // Navigate to flow definition or input editor
        router.push(`/flows/${run.flow_id}`);
        break;
      case 'view_logs':
        // Switch to split view tab and ensure logs are visible
        setActiveTab('split-view');
        if (errorSummary?.failed_step_number) {
          const failedStep = run.steps?.find(s => s.number === errorSummary.failed_step_number);
          if (failedStep) {
            setSelectedStepId(failedStep.id);
          }
        }
        break;
      case 'check_api_status':
      case 'contact_support':
      case 'check_permissions':
        // These would typically open external links or modals
        showError(`Action "${action}" not yet implemented`);
        break;
    }
  };

  // Determine status display
  const getStatusLabel = (status: string) => {
    switch (status) {
      case 'failed':
        return 'Failed';
      case 'suspended':
        return 'Needs Review';
      case 'success':
        return 'Succeeded';
      case 'completed':
        return 'Completed';
      case 'running':
        return 'Running';
      case 'pending':
        return 'Pending';
      default:
        return status;
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'failed':
        return 'bg-red-100 text-red-800 border-red-300';
      case 'suspended':
        return 'bg-amber-100 text-amber-800 border-amber-300';
      case 'success':
        return 'bg-green-100 text-green-800 border-green-300';
      case 'completed':
        return 'bg-green-100 text-green-800 border-green-300';
      case 'running':
        return 'bg-blue-100 text-blue-800 border-blue-300';
      case 'pending':
        return 'bg-slate-100 text-slate-800 border-slate-300';
      default:
        return 'bg-slate-100 text-slate-800 border-slate-300';
    }
  };

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-3xl font-bold">Run Details</h1>
          <div className="flex items-center gap-2">
            <div
              className={`px-3 py-1 rounded-full text-sm font-medium border ${getStatusColor(run.status)}`}
            >
              {getStatusLabel(run.status)}
            </div>
          </div>
        </div>
        <p className="text-sm text-muted-foreground font-mono">{runId}</p>

        {/* Error Summary Banner */}
        {errorSummary && (
          <div className="mt-4">
            <ErrorSummaryBanner
              error={errorSummary}
              onAction={handleRemediationAction}
            />
          </div>
        )}

        {/* Action Buttons (for runs that need replay without error) */}
        {!isFailed && !isRunning && run.steps && run.steps.length > 0 && (
          <div className="mt-4">
            <Button
              variant="outline"
              onClick={() => {
                const step = prompt(
                  `Enter step number to replay from (1-${run.steps.length}):`,
                );
                if (step !== null) {
                  const stepNum = parseInt(step, 10);
                  if (!isNaN(stepNum) && stepNum >= 1 && stepNum <= run.steps.length) {
                    setReplayStep(stepNum - 1);
                    replayMutation.mutate(stepNum - 1);
                  } else {
                    showError(`Please enter a number between 1 and ${run.steps.length}`);
                  }
                }
              }}
              disabled={replayMutation.isPending}
              size="sm"
            >
              <Rewind className="h-4 w-4 mr-2" />
              Replay from Step...
            </Button>
          </div>
        )}
      </div>

      {/* Summary Cards */}
      <div className="mb-6">
        <RunSummaryCards metrics={metrics} isRunning={isRunning} />
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="w-full">
          <TabsTrigger value="split-view" className="flex-1">
            <Layout className="h-4 w-4 mr-2" />
            Split View
          </TabsTrigger>
          {/* Graph tab hidden - redundant with Split View */}
          {run.artifacts && run.artifacts.length > 0 && (
            <TabsTrigger value="artifacts" className="flex-1">
              Artifacts ({run.artifacts.length})
            </TabsTrigger>
          )}
          <TabsTrigger value="cost" className="flex-1">
            Cost Breakdown
          </TabsTrigger>
        </TabsList>

        {/* Split View - Timeline + Console */}
        <TabsContent value="split-view" className="mt-6">
          <div className="border rounded-lg overflow-hidden" style={{ height: 'calc(100vh - 400px)', minHeight: '600px' }}>
            <ResizableSplit
              left={
                <NewStepTimeline
                  steps={run.steps}
                  selectedStepId={selectedStepId}
                  expandedSteps={expandedSteps}
                  onSelectStep={setSelectedStepId}
                  onToggleStep={(stepId) => {
                    const next = new Set(expandedSteps);
                    next.has(stepId) ? next.delete(stepId) : next.add(stepId);
                    setExpandedSteps(next);
                  }}
                />
              }
              right={
                <EnhancedConsolePanel
                  events={events}
                  steps={run.steps || []}
                  selectedStepId={selectedStepId}
                  onSelectStep={setSelectedStepId}
                />
              }
              defaultLeftWidth={40}
              minLeftWidth={30}
              minRightWidth={40}
              storageKey={`run-split-view-${runId}`}
            />
          </div>
        </TabsContent>

        {/* TODO: Graph tab removed - was redundant. If needed later, integrate a compact inline graph in Split View */}

        {run.artifacts && run.artifacts.length > 0 && (
          <TabsContent value="artifacts" className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle>Artifacts</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {run.artifacts.map((artifactId) => (
                    <div key={artifactId} className="border rounded p-3 font-mono text-sm">
                      {artifactId}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        )}

        <TabsContent value="cost" className="mt-6">
          <CostMetricsTab
            steps={run.steps || []}
            totalTokens={metrics.totalTokens || 0}
            totalCost={metrics.totalCost || 0}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
