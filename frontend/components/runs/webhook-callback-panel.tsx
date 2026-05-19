'use client';

import { useState } from 'react';
import { Clock, ArrowRight, CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardContent } from '@/components/ui/card';
import { CallbackUrlBlock } from '@/components/runs/callback-url-block';
import type { WebhookWaitError } from '@/lib/types';

interface WebhookCallbackPanelProps {
  /** run.error when run.error.type === 'WebhookWait' */
  webhookError: WebhookWaitError;
  /** Absolute URL of the callback endpoint, used for display + clipboard. */
  callbackUrl: string;
  /**
   * Caller invokes /api/v1/webhooks/callback/{callback_id} with the
   * provided action + payload. Returning a promise lets the panel render
   * a pending state while the resume happens.
   */
  onSendCallback: (body: {
    action: 'approve' | 'reject';
    reason?: string;
    data?: Record<string, unknown>;
  }) => Promise<void>;
  isPending: boolean;
}

/**
 * Demo-facing panel for callback-driven workflows (webhook.wait step).
 *
 * The run is suspended; the only way to resume it is for an external system
 * to POST to /api/v1/webhooks/callback/{callback_id}. This panel surfaces
 * the callback URL so the operator can copy it, and provides in-UI
 * Approve / Reject buttons that hit the same endpoint directly.
 *
 * For the human.approval step type, use HumanApprovalPanel instead — that
 * panel uses /runs/{id}/resume and is more featureful (tabbed review).
 */
export function WebhookCallbackPanel({
  webhookError,
  callbackUrl,
  onSendCallback,
  isPending,
}: WebhookCallbackPanelProps) {
  const [mode, setMode] = useState<'none' | 'approve' | 'reject'>('none');
  const [reason, setReason] = useState('');
  const [dataJson, setDataJson] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);

  const handleSubmit = (action: 'approve' | 'reject') => {
    setParseError(null);

    let data: Record<string, unknown> | undefined;
    if (dataJson.trim()) {
      try {
        const parsed = JSON.parse(dataJson);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          data = parsed as Record<string, unknown>;
        } else {
          setParseError('"data" must be a JSON object, e.g. { "applied_changes": [...] }');
          return;
        }
      } catch (e) {
        setParseError(`Invalid JSON: ${(e as Error).message}`);
        return;
      }
    }

    if (action === 'reject' && !reason.trim()) {
      setParseError('A reason is required when rejecting the callback.');
      return;
    }

    void onSendCallback({
      action,
      reason: action === 'reject' ? reason.trim() : undefined,
      data,
    });
  };

  return (
    <Card data-testid="webhook-callback-panel" className="border-amber-300 bg-amber-50">
      <CardHeader className="border-b border-amber-200 pb-4">
        <div className="flex items-center gap-3">
          <Clock className="h-6 w-6 text-amber-600" aria-hidden="true" />
          <div className="flex-1">
            <h2 className="text-lg font-semibold text-amber-900">
              Workflow Paused — Awaiting Callback
            </h2>
            <p className="mt-1 text-sm text-amber-800">
              Run is suspended on step{' '}
              <code className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-mono text-amber-900">
                {webhookError.step_id}
              </code>
              . It will resume when an external system POSTs to the callback URL below.
            </p>
          </div>
          <span className="rounded-full border border-amber-300 bg-amber-100 px-3 py-1 text-xs font-medium text-amber-900">
            webhook.wait
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-5 pt-5">
        <CallbackUrlBlock url={callbackUrl} label="Callback URL" />
        {/* Preserve the previous data-testid so existing tests that
            target the URL string keep working. */}
        <div data-testid="webhook-callback-url" hidden>
          {callbackUrl}
        </div>

        {/* Action buttons */}
        {mode === 'none' && (
          <div className="flex flex-wrap gap-3">
            <Button
              type="button"
              data-testid="webhook-approve-trigger"
              onClick={() => setMode('approve')}
              className="bg-green-600 hover:bg-green-700"
              disabled={isPending}
            >
              <CheckCircle2 className="mr-2 h-4 w-4" aria-hidden="true" />
              Send approve callback
            </Button>
            <Button
              type="button"
              data-testid="webhook-reject-trigger"
              variant="outline"
              onClick={() => setMode('reject')}
              disabled={isPending}
              className="border-red-300 text-red-700 hover:bg-red-50"
            >
              <XCircle className="mr-2 h-4 w-4" aria-hidden="true" />
              Send reject callback
            </Button>
          </div>
        )}

        {/* Approve form */}
        {mode === 'approve' && (
          <div className="space-y-3 rounded border border-green-200 bg-white p-4">
            <p className="text-sm text-slate-700">
              Approving will POST{' '}
              <code className="rounded bg-slate-100 px-1 py-0.5 text-xs font-mono">
                {'{"action":"approve",...}'}
              </code>{' '}
              to the callback URL. The run will move to <strong>queued</strong>, then resume.
            </p>
            <div>
              <label
                htmlFor="webhook-approve-data"
                className="text-xs font-medium uppercase tracking-wide text-slate-600"
              >
                Optional callback data (JSON object)
              </label>
              <textarea
                id="webhook-approve-data"
                data-testid="webhook-approve-data"
                rows={3}
                value={dataJson}
                onChange={(e) => setDataJson(e.target.value)}
                placeholder='{"applied_changes": ["cache flushed", "warm cache rebuilt"]}'
                className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 font-mono text-xs"
                disabled={isPending}
              />
            </div>
            {parseError && (
              <p className="text-xs text-red-700" role="alert">
                {parseError}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                type="button"
                data-testid="webhook-approve-submit"
                onClick={() => handleSubmit('approve')}
                disabled={isPending}
                className="bg-green-600 hover:bg-green-700"
              >
                {isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                    Sending…
                  </>
                ) : (
                  <>
                    <ArrowRight className="mr-2 h-4 w-4" aria-hidden="true" />
                    Confirm approve
                  </>
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setMode('none');
                  setParseError(null);
                  setDataJson('');
                }}
                disabled={isPending}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* Reject form */}
        {mode === 'reject' && (
          <div className="space-y-3 rounded border border-red-200 bg-white p-4">
            <p className="text-sm text-slate-700">
              Rejecting will POST{' '}
              <code className="rounded bg-slate-100 px-1 py-0.5 text-xs font-mono">
                {'{"action":"reject","reason":"..."}'}
              </code>{' '}
              to the callback URL. The run will be marked <strong>failed</strong> with the reason
              preserved in the audit trail.
            </p>
            <div>
              <label
                htmlFor="webhook-reject-reason"
                className="text-xs font-medium uppercase tracking-wide text-slate-600"
              >
                Reason (required)
              </label>
              <textarea
                id="webhook-reject-reason"
                data-testid="webhook-reject-reason"
                rows={2}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Maintenance window expired before the deployment completed"
                className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm"
                disabled={isPending}
              />
            </div>
            {parseError && (
              <p className="text-xs text-red-700" role="alert">
                {parseError}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                type="button"
                data-testid="webhook-reject-submit"
                onClick={() => handleSubmit('reject')}
                disabled={isPending}
                className="bg-red-600 hover:bg-red-700"
              >
                {isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                    Sending…
                  </>
                ) : (
                  <>
                    <XCircle className="mr-2 h-4 w-4" aria-hidden="true" />
                    Confirm reject
                  </>
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setMode('none');
                  setParseError(null);
                  setReason('');
                }}
                disabled={isPending}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
