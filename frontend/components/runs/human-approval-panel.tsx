'use client';

import { useState, useMemo } from 'react';
import {
  ShieldCheck,
  ShieldX,
  Loader2,
  PauseCircle,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  HelpCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardContent } from '@/components/ui/card';
import {
  CollapsibleSection,
  ReadableValue,
  isRecord,
  isEmptyValue,
} from '@/components/common/json-view';
import { CallbackUrlBlock } from '@/components/runs/callback-url-block';
import { API_BASE_URL } from '@/lib/api';
import type {
  ApprovalBrief,
  ApprovalCheck,
  ApprovalCheckStatus,
  ApprovalReadiness,
  HumanApprovalError,
  RunDetailResponse,
  RunStep,
  PlannedStep,
} from '@/lib/types';

interface HumanApprovalPanelProps {
  approvalError: HumanApprovalError;
  run: RunDetailResponse;
  onApprove: (data: { approved: true; approver?: string; comments?: string }) => void;
  onReject: (data: { approved: false; approver?: string; reason: string }) => void;
  isPending: boolean;
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function humanize(value: string): string {
  const stripped = value.replace(/_(input|eur|pct)$/i, '');
  const spaced = stripped.replace(/_/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function humanizeEnum(value: unknown): string {
  return String(value)
    .replace(/_/g, ' ')
    .replace(/^./, (c) => c.toUpperCase());
}

function formatEuro(value: unknown): string {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `€${n.toLocaleString('en-US')}`;
}

/**
 * Humanize a key-fact value regardless of how the brief produced it: a bare
 * monetary integer becomes `€30,000`, an enum-ish token becomes `Confidential`.
 * Idempotent on already-formatted values.
 */
function formatFactValue(label: string, value: string): string {
  const v = value.trim();
  if (/value|amount|cost|budget|price|eur/i.test(label) && /^\d{3,}$/.test(v)) {
    return formatEuro(v);
  }
  if (/^[a-z][a-z_]*$/.test(v)) {
    return humanizeEnum(v);
  }
  return value;
}

function stepTypeLabel(stepType: string | null): string {
  if (!stepType) return 'Step';
  const labels: Record<string, string> = {
    'ai.extract': 'AI Extraction',
    'ai.evaluate': 'AI Evaluation',
    'ai.generate': 'AI Generation',
    'tool.call': 'Tool Call',
    'http.request': 'HTTP Request',
    'webhook.wait': 'Webhook Wait',
    'human.approval': 'Human Approval',
    'artifact.store': 'Artifact Storage',
    condition: 'Condition',
  };
  if (labels[stepType]) return labels[stepType];
  const prefix = stepType.split('.')[0];
  if (prefix === 'ai') return 'AI Operation';
  if (prefix === 'tool' || prefix === 'http') return 'Tool Call';
  return stepType;
}

function buildApprovalCallbackUrl(callbackId: string): string {
  return `${API_BASE_URL.replace(/\/$/, '')}/api/v1/webhooks/callback/${callbackId}`;
}

// ---------------------------------------------------------------------------
// Approval brief: read the server-generated brief, or derive one client-side
// ---------------------------------------------------------------------------

const READINESS_LABELS: Record<ApprovalReadiness, string> = {
  ready: 'Ready for approval',
  review_required: 'Review required',
  blocked: 'Blocked — review required',
  unknown: 'Approval required',
};

// Readiness is the single warning-colored element, rendered inline inside the
// decision card (not as a separate banner) to avoid duplicating the message.
const READINESS_STYLES: Record<ApprovalReadiness, { text: string; Icon: typeof CheckCircle2 }> = {
  ready: { text: 'text-green-700', Icon: CheckCircle2 },
  review_required: { text: 'text-amber-700', Icon: AlertTriangle },
  blocked: { text: 'text-red-700', Icon: AlertTriangle },
  unknown: { text: 'text-slate-500', Icon: HelpCircle },
};

const READINESS_VALUES: ApprovalReadiness[] = ['ready', 'review_required', 'blocked', 'unknown'];

const CHECK_STATUS_VALUES: ApprovalCheckStatus[] = ['passed', 'needs_review', 'blocked', 'unknown'];

const CHECK_STYLES: Record<ApprovalCheckStatus, { text: string; Icon: typeof CheckCircle2 }> = {
  passed: { text: 'text-green-700', Icon: CheckCircle2 },
  needs_review: { text: 'text-amber-700', Icon: AlertTriangle },
  blocked: { text: 'text-red-700', Icon: AlertTriangle },
  unknown: { text: 'text-slate-500', Icon: HelpCircle },
};

const CHECK_STATUS_SUFFIX: Record<ApprovalCheckStatus, string> = {
  passed: 'passed',
  needs_review: 'needs review',
  blocked: 'blocked',
  unknown: '',
};

function CheckRow({ check }: { check: ApprovalCheck }) {
  const style = CHECK_STYLES[check.status];
  const suffix = CHECK_STATUS_SUFFIX[check.status];
  return (
    <li className={`flex items-center gap-1.5 ${style.text}`}>
      <style.Icon className="h-3.5 w-3.5 flex-shrink-0" />
      <span>
        {check.label}
        {suffix ? ` ${suffix}` : ''}
        {check.detail ? <span className="text-slate-400"> · {check.detail}</span> : null}
      </span>
    </li>
  );
}

/** Validate and normalize the server-provided brief; null when absent/malformed. */
function readServerBrief(step: RunStep | undefined): ApprovalBrief | null {
  const raw = step?.input;
  if (!isRecord(raw)) return null;
  const brief = raw.approval_brief;
  if (!isRecord(brief)) return null;
  if (
    typeof brief.decision_title !== 'string' ||
    typeof brief.main_reason !== 'string' ||
    !READINESS_VALUES.includes(brief.readiness as ApprovalReadiness)
  ) {
    return null;
  }
  const arr = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [];
  const facts = Array.isArray(brief.key_facts)
    ? brief.key_facts
        .filter((f): f is { label: string; value: string } => isRecord(f))
        .map((f) => ({ label: String(f.label), value: String(f.value) }))
    : [];
  const readiness = brief.readiness as ApprovalReadiness;
  const checks = Array.isArray(brief.checks)
    ? brief.checks
        .filter((c): c is Record<string, unknown> => isRecord(c))
        .filter(
          (c) =>
            typeof c.label === 'string' &&
            CHECK_STATUS_VALUES.includes(c.status as ApprovalCheckStatus),
        )
        .map((c) => ({
          label: String(c.label),
          status: c.status as ApprovalCheckStatus,
          detail: typeof c.detail === 'string' ? c.detail : undefined,
          source_step_id: typeof c.source_step_id === 'string' ? c.source_step_id : undefined,
        }))
    : undefined;
  return {
    decision_title: brief.decision_title,
    readiness,
    readiness_label:
      typeof brief.readiness_label === 'string'
        ? brief.readiness_label
        : READINESS_LABELS[readiness],
    main_reason: brief.main_reason,
    critical_issues: arr(brief.critical_issues),
    passed_checks: arr(brief.passed_checks),
    checks,
    key_facts: facts,
    approval_consequence:
      typeof brief.approval_consequence === 'string' ? brief.approval_consequence : '',
    source_step_ids: arr(brief.source_step_ids),
    generation_status:
      brief.generation_status === 'generated' || brief.generation_status === 'failed'
        ? brief.generation_status
        : 'fallback',
    confidence: typeof brief.confidence === 'number' ? brief.confidence : undefined,
    warnings: arr(brief.warnings),
    debug_reason: typeof brief.debug_reason === 'string' ? brief.debug_reason : undefined,
  };
}

// Evidence keys recognized when deriving a client-side fallback brief.
const FACT_FIELDS: { key: string; label: string; format?: (v: unknown) => string }[] = [
  { key: 'project_name', label: 'Project' },
  { key: 'criticality', label: 'Criticality', format: humanizeEnum },
  { key: 'estimated_value_eur', label: 'Estimated value', format: formatEuro },
  { key: 'data_sensitivity', label: 'Data sensitivity', format: humanizeEnum },
  { key: 'num_users', label: 'Users' },
  { key: 'contract_duration', label: 'Contract duration' },
  { key: 'pricing_model', label: 'Pricing model', format: humanizeEnum },
];

/** Best-effort brief built from run data when no server brief is available. */
function buildClientFallbackBrief(
  run: RunDetailResponse,
  approvalError: HumanApprovalError,
  completedSteps: RunStep[],
  nextSteps: PlannedStep[],
): ApprovalBrief {
  const payload = (run.payload ?? {}) as Record<string, unknown>;
  const issues: string[] = [];
  const passed: string[] = [];
  let blocking = false;
  let concern = false;

  for (const step of completedSteps) {
    const out = step.output;
    if (!isRecord(out)) continue;
    if (Array.isArray(out.missing_fields)) {
      if (out.missing_fields.length) {
        blocking = true;
        issues.push(...out.missing_fields.slice(0, 5).map((f) => `Missing: ${String(f)}`));
      } else {
        passed.push('No missing fields');
      }
    }
    if (typeof out.pass === 'boolean') {
      if (out.pass === false) {
        concern = true;
        issues.push('PONT/compliance check did not pass');
      } else {
        passed.push('PONT/compliance check passed');
      }
    }
    for (const key of ['inconsistencies', 'issues', 'risks']) {
      const v = out[key];
      if (Array.isArray(v) && v.length) {
        concern = true;
        issues.push(...v.slice(0, 5).map((x) => String(x)));
      } else if (key === 'inconsistencies' && Array.isArray(v)) {
        passed.push('No inconsistencies');
      }
    }
  }

  const readiness: ApprovalReadiness = blocking
    ? 'blocked'
    : concern
      ? 'review_required'
      : 'unknown';

  const keyFacts = FACT_FIELDS.filter((f) => f.key in payload && !isEmptyValue(payload[f.key])).map(
    (f) => ({
      label: f.label,
      value: f.format ? f.format(payload[f.key]) : String(payload[f.key]),
    }),
  );

  const nextName = nextSteps.length > 0 ? humanize(nextSteps[0].name) : null;
  // Name the actual planned next steps rather than a generic "continue".
  const nextNames = nextSteps.slice(0, 3).map((s) => humanize(s.name));
  const consequence = nextNames.length
    ? `If approved, Saz will continue with ${nextNames.join(', ')}.`
    : 'If approved, the workflow will complete.';

  return {
    decision_title: nextName
      ? `Approve continuing to ${nextName}?`
      : 'Approve completing this workflow?',
    readiness,
    readiness_label: READINESS_LABELS[readiness],
    main_reason:
      approvalError.message ||
      approvalError.reasoning ||
      'Human approval is required before this workflow can continue.',
    critical_issues: issues.slice(0, 8),
    passed_checks: passed,
    key_facts: keyFacts,
    approval_consequence: consequence,
    source_step_ids: completedSteps.map((s) => s.name),
    generation_status: 'fallback',
    warnings: [],
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

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
  const [showAdvanced, setShowAdvanced] = useState(false);

  const completedSteps = useMemo(
    () => run.steps.filter((s) => s.status === 'completed'),
    [run.steps],
  );
  const suspendedStep = useMemo(() => run.steps.find((s) => s.status === 'suspended'), [run.steps]);

  const approvalStepIndex = useMemo(
    () => (run.planned_steps || []).findIndex((s) => s.id === approvalError.step_id),
    [run.planned_steps, approvalError.step_id],
  );
  const nextSteps = useMemo(
    () => (approvalStepIndex < 0 ? [] : (run.planned_steps || []).slice(approvalStepIndex + 1)),
    [run.planned_steps, approvalStepIndex],
  );

  const brief = useMemo(
    () =>
      readServerBrief(suspendedStep) ??
      buildClientFallbackBrief(run, approvalError, completedSteps, nextSteps),
    [suspendedStep, run, approvalError, completedSteps, nextSteps],
  );

  const stepsWithOutput = useMemo(
    () => completedSteps.filter((s) => !isEmptyValue(s.output)),
    [completedSteps],
  );

  const approvalTitle = suspendedStep ? humanize(suspendedStep.name) : 'this step';
  const nextStepName = nextSteps.length > 0 ? humanize(nextSteps[0].name) : null;
  const readinessStyle = READINESS_STYLES[brief.readiness];

  // Keep key facts compact: long prose (objective/scope/background) belongs in
  // advanced details, not the default scannable view.
  const compactFacts = brief.key_facts.filter((f) => f.value.length <= 80);

  const handleApprove = () => onApprove({ approved: true, comments: comments.trim() || undefined });
  const handleReject = () =>
    onReject({ approved: false, reason: reason.trim() || 'Rejected by user' });
  const handleCancel = () => {
    setMode('review');
    setComments('');
    setReason('');
  };

  return (
    <Card className="border-amber-300 bg-amber-50/50 shadow-md" data-testid="approval-packet">
      <CardHeader className="pb-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full border border-amber-200 bg-amber-100">
              <PauseCircle className="h-5 w-5 text-amber-600" />
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-amber-700">
                Workflow paused — approval required
              </p>
              <h3 className="text-lg font-semibold text-slate-900">
                Approval needed: {approvalTitle}
              </h3>
              <p className="mt-1 text-xs text-slate-500">
                {run.flow_name} · Step {approvalStepIndex + 1} of {run.planned_steps?.length ?? '?'}
              </p>
            </div>
          </div>
          <span className="flex-shrink-0 rounded-full border border-amber-200 bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800">
            Awaiting decision
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* One decision card: question + readiness + reason, no duplicate banner */}
        <div
          data-testid="decision-question"
          className="space-y-2 rounded-lg border border-slate-200 bg-white p-4"
        >
          <p className="text-base font-semibold text-slate-900">{brief.decision_title}</p>
          <div
            data-testid="readiness-state"
            className={`flex items-center gap-1.5 text-sm font-medium ${readinessStyle.text}`}
          >
            <readinessStyle.Icon className="h-4 w-4 flex-shrink-0" />
            <span>{brief.readiness_label}</span>
          </div>
          {brief.main_reason && (
            <p className="whitespace-pre-wrap text-sm text-slate-600">{brief.main_reason}</p>
          )}
        </div>

        {/* Checks — structured (passed / needs review / blocked) when available,
            otherwise the legacy passed-only list. Compact rows, not chips. */}
        {brief.checks && brief.checks.length > 0 ? (
          <section data-testid="checks">
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-700">
              Checks
            </h4>
            <ul className="space-y-0.5 text-sm">
              {brief.checks.map((check, i) => (
                <CheckRow key={i} check={check} />
              ))}
            </ul>
          </section>
        ) : (
          brief.passed_checks.length > 0 && (
            <section data-testid="checks">
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-700">
                Checks
              </h4>
              <ul className="space-y-0.5 text-sm text-slate-700">
                {brief.passed_checks.map((check, i) => (
                  <li key={i} className="flex items-center gap-1.5">
                    <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0 text-green-600" />
                    <span>{check}</span>
                  </li>
                ))}
              </ul>
            </section>
          )
        )}

        {/* Critical issues — compact list, no heavy nested warning box */}
        {brief.critical_issues.length > 0 && (
          <section data-testid="critical-issues">
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-700">
              Critical issues
            </h4>
            <ul className="space-y-1 text-sm text-slate-700">
              {brief.critical_issues.map((issue, i) => (
                <li key={i} className="flex gap-2">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-500" />
                  <span className="whitespace-pre-wrap break-words">{issue}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Key facts — compact two-column grid with human formatting */}
        {compactFacts.length > 0 && (
          <section data-testid="key-facts">
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-700">
              Key facts
            </h4>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-1 rounded-lg border border-slate-200 bg-white p-3 text-sm sm:grid-cols-2">
              {compactFacts.map((fact, i) => (
                <div key={i} className="flex gap-1.5">
                  <dt className="font-medium text-slate-500 after:content-[':']">{fact.label}</dt>
                  <dd className="min-w-0 text-slate-800">
                    {formatFactValue(fact.label, fact.value)}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {/* What happens after approval */}
        {brief.approval_consequence && (
          <section data-testid="after-approval">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-700">
              What happens after approval
            </h4>
            <p className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700">
              {brief.approval_consequence}
            </p>
          </section>
        )}

        {/* Decision actions */}
        {mode === 'review' && (
          <div className="flex items-center gap-3 pt-1">
            <Button
              onClick={() => setMode('approve')}
              disabled={isPending}
              className="bg-green-600 text-white hover:bg-green-700"
            >
              <ShieldCheck className="mr-2 h-4 w-4" />
              Approve and continue
            </Button>
            <Button
              onClick={() => setMode('reject')}
              disabled={isPending}
              variant="outline"
              className="border-red-300 text-red-700 hover:bg-red-50"
            >
              <ShieldX className="mr-2 h-4 w-4" />
              Reject and stop
            </Button>
          </div>
        )}

        {mode === 'approve' && (
          <div className="space-y-3 rounded-lg border border-green-200 bg-green-50 p-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-green-600" />
              <span className="text-sm font-semibold text-green-900">Confirm approval</span>
            </div>
            <p className="text-sm text-green-800">
              The workflow will resume and continue with{' '}
              <span className="font-medium">{nextStepName ?? 'completion'}</span>.
            </p>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              placeholder="Optional comments..."
              aria-label="Approval comments"
              className="w-full resize-none rounded-md border border-green-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
              rows={2}
              disabled={isPending}
            />
            <div className="flex items-center gap-2">
              <Button
                onClick={handleApprove}
                disabled={isPending}
                size="sm"
                className="bg-green-600 text-white hover:bg-green-700"
              >
                {isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Resuming...
                  </>
                ) : (
                  <>
                    <ShieldCheck className="mr-2 h-4 w-4" />
                    Approve and continue
                  </>
                )}
              </Button>
              <Button onClick={handleCancel} disabled={isPending} variant="ghost" size="sm">
                Back
              </Button>
            </div>
          </div>
        )}

        {mode === 'reject' && (
          <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-4">
            <div className="flex items-center gap-2">
              <ShieldX className="h-5 w-5 text-red-600" />
              <span className="text-sm font-semibold text-red-900">Confirm rejection</span>
            </div>
            <p className="text-sm text-red-800">
              The workflow will be marked as failed and will not continue.
            </p>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for rejection (required)..."
              aria-label="Rejection reason"
              className="w-full resize-none rounded-md border border-red-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
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
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Rejecting...
                  </>
                ) : (
                  <>
                    <ShieldX className="mr-2 h-4 w-4" />
                    Reject and stop
                  </>
                )}
              </Button>
              <Button onClick={handleCancel} disabled={isPending} variant="ghost" size="sm">
                Back
              </Button>
            </div>
          </div>
        )}

        {/* Advanced / debug — collapsed by default, conditionally mounted */}
        <div data-testid="advanced-details" className="border-t border-slate-200 pt-3">
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-700"
          >
            {showAdvanced ? (
              <ChevronDown className="h-3.5 w-3.5" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" />
            )}
            Advanced details
          </button>

          {showAdvanced && (
            <div className="mt-3 space-y-4">
              <div>
                <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Approval brief ({brief.generation_status})
                </h5>
                {brief.warnings && brief.warnings.length > 0 && (
                  <ul className="mb-2 list-disc pl-5 text-xs text-slate-500">
                    {brief.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                )}
                {brief.debug_reason && (
                  <p className="mb-2 text-xs text-slate-400">Reason: {brief.debug_reason}</p>
                )}
                <CollapsibleSection title="View raw brief">
                  <ReadableValue value={brief} />
                </CollapsibleSection>
              </div>

              {nextSteps.length > 0 && (
                <div>
                  <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    Planned next steps
                  </h5>
                  <div className="space-y-1.5">
                    {nextSteps.map((step, i) => (
                      <div key={step.id} className="flex items-center gap-2 text-sm">
                        <ArrowRight className="h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
                        <span className="w-5 text-right font-mono text-xs text-slate-400">
                          {approvalStepIndex + 2 + i}
                        </span>
                        <span className="font-medium text-slate-800">{humanize(step.name)}</span>
                        <span className="text-xs text-slate-400">
                          {stepTypeLabel(step.step_type)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {stepsWithOutput.length > 0 && (
                <div>
                  <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    Full step outputs
                  </h5>
                  <div className="space-y-2">
                    {stepsWithOutput.map((step) => (
                      <StepOutputSection key={step.id} step={step} />
                    ))}
                  </div>
                </div>
              )}

              {!isEmptyValue(run.payload) && (
                <div>
                  <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    Raw run input
                  </h5>
                  <CollapsibleSection title="View full run payload">
                    <ReadableValue value={run.payload} />
                  </CollapsibleSection>
                </div>
              )}

              {approvalError.callback_id && (
                <div>
                  <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    Approve via webhook callback (curl)
                  </h5>
                  <CallbackUrlBlock
                    url={buildApprovalCallbackUrl(approvalError.callback_id)}
                    label="Callback URL"
                  />
                  <p className="mt-2 text-xs text-slate-500">
                    Approving via the buttons above calls <code>POST /runs/{run.id}/resume</code>.
                    External systems can resolve this gate by POSTing to the callback URL instead —
                    the audit trail records both paths.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/** Expandable raw JSON for a single completed step (advanced view). */
function StepOutputSection({ step }: { step: RunStep }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center gap-2 bg-slate-50 px-3 py-2.5 text-left transition-colors hover:bg-slate-100"
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4 flex-shrink-0 text-slate-500" />
        ) : (
          <ChevronRight className="h-4 w-4 flex-shrink-0 text-slate-500" />
        )}
        <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0 text-green-500" />
        <span className="text-sm font-medium text-slate-800">{step.name}</span>
        <span className="ml-auto flex-shrink-0 text-xs text-slate-400">
          {stepTypeLabel(step.step_type)}
        </span>
      </button>
      {isOpen && (
        <div className="border-t border-slate-200 bg-white p-3">
          <pre className="max-h-64 overflow-auto rounded bg-slate-50 p-3 font-mono text-xs text-slate-700">
            {JSON.stringify(step.output, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
