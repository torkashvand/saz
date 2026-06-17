'use client';

import { useState, useMemo } from 'react';
import {
  ShieldCheck,
  ShieldX,
  Loader2,
  PauseCircle,
  CheckCircle2,
  ArrowRight,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardContent } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { CollapsibleSection, ReadableValue } from '@/components/common/json-view';
import { CallbackUrlBlock } from '@/components/runs/callback-url-block';
import type { HumanApprovalError, RunDetailResponse, RunStep, PlannedStep } from '@/lib/types';

interface HumanApprovalPanelProps {
  approvalError: HumanApprovalError;
  run: RunDetailResponse;
  onApprove: (data: { approved: true; approver?: string; comments?: string }) => void;
  onReject: (data: { approved: false; approver?: string; reason: string }) => void;
  isPending: boolean;
}

/** Find the index of the approval step in planned_steps by step_id */
function findApprovalStepIndex(plannedSteps: PlannedStep[], approvalStepId: string): number {
  return plannedSteps.findIndex((s) => s.id === approvalStepId);
}

/** Get steps that come after the approval step */
function getNextSteps(plannedSteps: PlannedStep[], approvalStepIndex: number): PlannedStep[] {
  if (approvalStepIndex < 0) return [];
  return plannedSteps.slice(approvalStepIndex + 1);
}

/** Human-readable step type label */
function stepTypeLabel(stepType: string | null): string {
  if (!stepType) return 'Step';
  const labels: Record<string, string> = {
    'ai.extract': 'AI Extraction',
    'ai.generate': 'AI Generation',
    'ai.route': 'AI Routing',
    'ai.score': 'AI Scoring',
    'ai.assess': 'AI Assessment',
    'tool.call': 'Tool Call',
    'http.request': 'HTTP Request',
    'webhook.wait': 'Webhook Wait',
    'human.approval': 'Human Approval',
    'artifact.store': 'Artifact Storage',
    condition: 'Condition',
  };
  // Try exact match first, then prefix match
  if (labels[stepType]) return labels[stepType];
  const prefix = stepType.split('.')[0];
  if (prefix === 'ai') return 'AI Operation';
  if (prefix === 'tool' || prefix === 'http') return 'Tool Call';
  return stepType;
}

/** Check if a value has meaningful content to display */
function hasContent(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === 'object' && Object.keys(value as object).length === 0) return false;
  return true;
}

/**
 * Build the absolute URL operators can POST to in order to resolve the
 * approval gate via the webhook callback path. Mirrors the construction
 * used on the run detail page for the webhook.wait variant so the curl
 * recipe in the docs works for both suspension types.
 */
function buildApprovalCallbackUrl(callbackId: string): string {
  const base = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
  return `${base}/api/v1/webhooks/callback/${callbackId}`;
}

export function HumanApprovalPanel({
  approvalError,
  run,
  onApprove,
  onReject,
  isPending,
}: HumanApprovalPanelProps) {
  const [mode, setMode] = useState<'review' | 'approve' | 'reject'>('review');
  const [comments, setComments] = useState('');
  const [reason, setReason] = useState('');

  const completedSteps = useMemo(
    () => run.steps.filter((s) => s.status === 'completed'),
    [run.steps],
  );

  const suspendedStep = useMemo(() => run.steps.find((s) => s.status === 'suspended'), [run.steps]);

  const approvalStepIndex = useMemo(
    () => findApprovalStepIndex(run.planned_steps || [], approvalError.step_id),
    [run.planned_steps, approvalError.step_id],
  );

  const nextSteps = useMemo(
    () => getNextSteps(run.planned_steps || [], approvalStepIndex),
    [run.planned_steps, approvalStepIndex],
  );

  // Steps that have output worth reviewing
  const stepsWithOutput = useMemo(
    () => completedSteps.filter((s) => hasContent(s.output)),
    [completedSteps],
  );

  const hasReviewableContent = stepsWithOutput.length > 0;

  const handleApprove = () => {
    onApprove({
      approved: true,
      comments: comments.trim() || undefined,
    });
  };

  const handleReject = () => {
    onReject({
      approved: false,
      reason: reason.trim() || 'Rejected by user',
    });
  };

  const handleCancel = () => {
    setMode('review');
    setComments('');
    setReason('');
  };

  return (
    <Card className="border-amber-300 bg-amber-50/50 shadow-md">
      <CardHeader className="pb-4">
        {/* Status header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-full bg-amber-100 border border-amber-200 flex items-center justify-center flex-shrink-0">
              <PauseCircle className="h-5 w-5 text-amber-600" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-slate-900">
                Workflow Paused &mdash; Approval Required
              </h3>
              <p className="text-sm text-slate-600">
                {run.flow_name} &middot; Step {approvalStepIndex + 1} of{' '}
                {run.planned_steps?.length ?? '?'}
              </p>
            </div>
          </div>
          <span className="px-3 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800 border border-amber-200">
            Awaiting Decision
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Approval context */}
        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
          <h4 className="text-sm font-semibold text-slate-900">What needs approval</h4>
          <p className="text-sm text-slate-700">{approvalError.message}</p>
          {approvalError.reasoning && (
            <p className="text-sm text-slate-600 italic">{approvalError.reasoning}</p>
          )}
          <div className="text-xs text-slate-500 font-mono">Step: {approvalError.step_id}</div>
          {approvalError.callback_id && (
            <details className="border-t border-slate-100 pt-3">
              <summary className="cursor-pointer select-none text-xs font-medium uppercase tracking-wide text-slate-600">
                Advanced: approve via webhook callback (curl)
              </summary>
              <div className="mt-3">
                <CallbackUrlBlock
                  url={buildApprovalCallbackUrl(approvalError.callback_id)}
                  label="Callback URL"
                />
                <p className="mt-2 text-xs text-slate-500">
                  Approving via the buttons below calls <code>POST /runs/{run.id}/resume</code>.
                  External systems can resolve this gate by POSTing to the callback URL above
                  instead — the audit trail records both paths.
                </p>
              </div>
            </details>
          )}
        </div>

        {/* Tabbed review area */}
        <Tabs defaultValue="summary" className="w-full">
          <TabsList className="bg-white border border-slate-200">
            <TabsTrigger value="summary" className="text-xs">
              Summary
            </TabsTrigger>
            {hasReviewableContent && (
              <TabsTrigger value="outputs" className="text-xs">
                Step Outputs ({stepsWithOutput.length})
              </TabsTrigger>
            )}
            <TabsTrigger value="next" className="text-xs">
              After Approval
            </TabsTrigger>
          </TabsList>

          {/* Summary tab */}
          <TabsContent value="summary">
            <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-4">
              {/* Completed steps */}
              <div>
                <h5 className="text-xs font-semibold text-slate-700 uppercase tracking-wide mb-2">
                  Completed Steps
                </h5>
                {completedSteps.length > 0 ? (
                  <div className="space-y-1.5">
                    {completedSteps.map((step) => (
                      <div key={step.id} className="flex items-center gap-2 text-sm">
                        <CheckCircle2 className="h-3.5 w-3.5 text-green-500 flex-shrink-0" />
                        <span className="text-slate-800 font-medium">{step.name}</span>
                        <span className="text-slate-400 text-xs">
                          {stepTypeLabel(step.step_type)}
                        </span>
                        {step.duration_ms != null && (
                          <span className="text-slate-400 text-xs ml-auto">
                            {step.duration_ms < 1000
                              ? `${step.duration_ms}ms`
                              : `${(step.duration_ms / 1000).toFixed(1)}s`}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">
                    No steps completed before this approval point.
                  </p>
                )}
              </div>

              {/* Suspended step */}
              {suspendedStep && (
                <div>
                  <h5 className="text-xs font-semibold text-slate-700 uppercase tracking-wide mb-2">
                    Pending Approval Step
                  </h5>
                  <div className="flex items-center gap-2 text-sm">
                    <PauseCircle className="h-3.5 w-3.5 text-amber-500 flex-shrink-0" />
                    <span className="text-slate-800 font-medium">{suspendedStep.name}</span>
                    <span className="text-slate-400 text-xs">
                      {stepTypeLabel(suspendedStep.step_type)}
                    </span>
                  </div>
                </div>
              )}

              {/* Run payload context */}
              {hasContent(run.payload) && (
                <div>
                  <h5 className="text-xs font-semibold text-slate-700 uppercase tracking-wide mb-2">
                    Run Input
                  </h5>
                  <CollapsibleSection title="View run payload">
                    <ReadableValue value={run.payload} />
                  </CollapsibleSection>
                </div>
              )}
            </div>
          </TabsContent>

          {/* Step outputs tab */}
          {hasReviewableContent && (
            <TabsContent value="outputs">
              <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
                <p className="text-xs text-slate-500 mb-2">
                  Review the results from completed steps before making your decision.
                </p>
                {stepsWithOutput.map((step) => (
                  <StepOutputSection key={step.id} step={step} />
                ))}
              </div>
            </TabsContent>
          )}

          {/* After approval tab */}
          <TabsContent value="next">
            <div className="bg-white border border-slate-200 rounded-lg p-4">
              <h5 className="text-xs font-semibold text-slate-700 uppercase tracking-wide mb-3">
                What happens after approval
              </h5>
              {nextSteps.length > 0 ? (
                <div className="space-y-2">
                  {nextSteps.map((step, i) => (
                    <div key={step.id} className="flex items-center gap-2 text-sm">
                      <div className="flex items-center gap-1.5 text-slate-400">
                        <ArrowRight className="h-3.5 w-3.5" />
                        <span className="text-xs font-mono w-5 text-right">
                          {approvalStepIndex + 2 + i}
                        </span>
                      </div>
                      <span className="text-slate-800 font-medium">{step.name}</span>
                      <span className="text-slate-400 text-xs">
                        {stepTypeLabel(step.step_type)}
                      </span>
                    </div>
                  ))}
                  <p className="text-xs text-slate-500 mt-3 pt-2 border-t border-slate-100">
                    The workflow will continue with{' '}
                    <span className="font-medium text-slate-700">{nextSteps[0].name}</span>{' '}
                    immediately after approval.
                  </p>
                </div>
              ) : (
                <p className="text-sm text-slate-500">
                  This is the last step. Approving will complete the workflow.
                </p>
              )}
            </div>
          </TabsContent>
        </Tabs>

        {/* Decision actions */}
        {mode === 'review' && (
          <div className="flex items-center gap-3 pt-2">
            <Button
              onClick={() => setMode('approve')}
              disabled={isPending}
              className="bg-green-600 hover:bg-green-700 text-white"
            >
              <ShieldCheck className="h-4 w-4 mr-2" />
              Approve and Continue
            </Button>
            <Button
              onClick={() => setMode('reject')}
              disabled={isPending}
              variant="outline"
              className="border-red-300 text-red-700 hover:bg-red-50"
            >
              <ShieldX className="h-4 w-4 mr-2" />
              Reject
            </Button>
          </div>
        )}

        {/* Approve confirmation */}
        {mode === 'approve' && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-green-600" />
              <span className="text-sm font-semibold text-green-900">Confirm Approval</span>
            </div>
            <p className="text-sm text-green-800">
              The workflow will resume and continue with{' '}
              <span className="font-medium">
                {nextSteps.length > 0 ? nextSteps[0].name : 'completion'}
              </span>
              .
            </p>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              placeholder="Optional comments..."
              className="w-full px-3 py-2 text-sm border border-green-200 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-green-400 resize-none"
              rows={2}
              disabled={isPending}
            />
            <div className="flex items-center gap-2">
              <Button
                onClick={handleApprove}
                disabled={isPending}
                className="bg-green-600 hover:bg-green-700 text-white"
                size="sm"
              >
                {isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Resuming...
                  </>
                ) : (
                  <>
                    <ShieldCheck className="h-4 w-4 mr-2" />
                    Approve and Continue
                  </>
                )}
              </Button>
              <Button onClick={handleCancel} disabled={isPending} variant="ghost" size="sm">
                Back
              </Button>
            </div>
          </div>
        )}

        {/* Reject confirmation */}
        {mode === 'reject' && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 space-y-3">
            <div className="flex items-center gap-2">
              <ShieldX className="h-5 w-5 text-red-600" />
              <span className="text-sm font-semibold text-red-900">Confirm Rejection</span>
            </div>
            <p className="text-sm text-red-800">
              The workflow will be marked as failed and will not continue.
            </p>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for rejection (required)..."
              className="w-full px-3 py-2 text-sm border border-red-200 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-red-400 resize-none"
              rows={2}
              disabled={isPending}
            />
            <div className="flex items-center gap-2">
              <Button
                onClick={handleReject}
                disabled={isPending || !reason.trim()}
                variant="outline"
                size="sm"
                className="border-red-300 text-red-700 hover:bg-red-100"
              >
                {isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Rejecting...
                  </>
                ) : (
                  <>
                    <ShieldX className="h-4 w-4 mr-2" />
                    Reject
                  </>
                )}
              </Button>
              <Button onClick={handleCancel} disabled={isPending} variant="ghost" size="sm">
                Back
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Expandable section for a single step's output */
function StepOutputSection({ step }: { step: RunStep }) {
  const [isOpen, setIsOpen] = useState(false);

  // Try to extract a short summary from the output
  const outputSummary = useMemo(() => {
    if (!step.output) return null;
    if (typeof step.output === 'string') return step.output.slice(0, 120);
    // For objects, try to find a summary-like field
    const summaryKeys = ['summary', 'result', 'message', 'description', 'text', 'content'];
    for (const key of summaryKeys) {
      if (key in step.output && typeof step.output[key] === 'string') {
        return step.output[key].slice(0, 200);
      }
    }
    return null;
  }, [step.output]);

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-3 py-2.5 bg-slate-50 hover:bg-slate-100 transition-colors text-left"
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4 text-slate-500 flex-shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-500 flex-shrink-0" />
        )}
        <CheckCircle2 className="h-3.5 w-3.5 text-green-500 flex-shrink-0" />
        <span className="text-sm font-medium text-slate-800">{step.name}</span>
        <span className="text-xs text-slate-400 ml-auto flex-shrink-0">
          {stepTypeLabel(step.step_type)}
        </span>
      </button>
      {!isOpen && outputSummary && (
        <div className="px-3 py-2 text-xs text-slate-600 border-t border-slate-100 bg-white truncate">
          {outputSummary}
        </div>
      )}
      {isOpen && (
        <div className="p-3 border-t border-slate-200 bg-white">
          <pre className="text-xs bg-slate-50 p-3 rounded overflow-auto max-h-64 font-mono text-slate-700">
            {JSON.stringify(step.output, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
