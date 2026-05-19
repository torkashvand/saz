/**
 * Component tests for the WebhookCallbackPanel.
 *
 * Pins the demo-critical UI behaviour for the callback-driven maintenance
 * wedge demo:
 *   1. The panel surfaces the full callback URL operators must POST to.
 *   2. The Approve flow sends action="approve" and parses the optional
 *      JSON data payload, surfacing a clear error when the JSON is
 *      malformed (so the demo never silently sends invalid data).
 *   3. The Reject flow requires a reason and sends action="reject".
 *
 * The panel is rendered with mocked `onSendCallback`, since this test is
 * about UI semantics, not network behaviour.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { WebhookCallbackPanel } from '@/components/runs/webhook-callback-panel';
import type { WebhookWaitError } from '@/lib/types';

const ERROR: WebhookWaitError = {
  message: 'Webhook wait for step wait_for_completion_callback',
  type: 'WebhookWait',
  step_id: 'wait_for_completion_callback',
  callback_id: 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4',
};
const URL = `http://localhost:8000/api/v1/webhooks/callback/${ERROR.callback_id}`;

function renderPanel(overrides: Partial<React.ComponentProps<typeof WebhookCallbackPanel>> = {}) {
  const onSendCallback = vi.fn().mockResolvedValue(undefined);
  const utils = render(
    <WebhookCallbackPanel
      webhookError={ERROR}
      callbackUrl={URL}
      onSendCallback={onSendCallback}
      isPending={false}
      {...overrides}
    />,
  );
  return { ...utils, onSendCallback };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe('WebhookCallbackPanel', () => {
  it('surfaces the callback URL and the suspended step id', () => {
    renderPanel();
    expect(screen.getByTestId('webhook-callback-url')).toHaveTextContent(URL);
    // The suspended step id is rendered in the header so the operator can
    // confirm which step paused the run.
    expect(screen.getByText(ERROR.step_id)).toBeInTheDocument();
  });

  it('sends action=approve when the operator confirms the approve flow', () => {
    const { onSendCallback } = renderPanel();
    fireEvent.click(screen.getByTestId('webhook-approve-trigger'));
    fireEvent.click(screen.getByTestId('webhook-approve-submit'));
    expect(onSendCallback).toHaveBeenCalledTimes(1);
    expect(onSendCallback).toHaveBeenCalledWith({
      action: 'approve',
      reason: undefined,
      data: undefined,
    });
  });

  it('parses optional approve data JSON and forwards it', () => {
    const { onSendCallback } = renderPanel();
    fireEvent.click(screen.getByTestId('webhook-approve-trigger'));
    fireEvent.change(screen.getByTestId('webhook-approve-data'), {
      target: { value: '{"applied_changes":["cache flushed"]}' },
    });
    fireEvent.click(screen.getByTestId('webhook-approve-submit'));
    expect(onSendCallback).toHaveBeenCalledWith({
      action: 'approve',
      reason: undefined,
      data: { applied_changes: ['cache flushed'] },
    });
  });

  it('refuses to submit malformed approve data and shows an inline error', () => {
    const { onSendCallback } = renderPanel();
    fireEvent.click(screen.getByTestId('webhook-approve-trigger'));
    fireEvent.change(screen.getByTestId('webhook-approve-data'), {
      target: { value: '{not json' },
    });
    fireEvent.click(screen.getByTestId('webhook-approve-submit'));
    expect(onSendCallback).not.toHaveBeenCalled();
    // The user must see an actionable error rather than a silent failure.
    expect(screen.getByRole('alert')).toHaveTextContent(/invalid json/i);
  });

  it('refuses to submit approve data that is a JSON array (must be object)', () => {
    const { onSendCallback } = renderPanel();
    fireEvent.click(screen.getByTestId('webhook-approve-trigger'));
    fireEvent.change(screen.getByTestId('webhook-approve-data'), {
      target: { value: '["nope"]' },
    });
    fireEvent.click(screen.getByTestId('webhook-approve-submit'));
    expect(onSendCallback).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/json object/i);
  });

  it('sends action=reject with a reason when the operator rejects', () => {
    const { onSendCallback } = renderPanel();
    fireEvent.click(screen.getByTestId('webhook-reject-trigger'));
    fireEvent.change(screen.getByTestId('webhook-reject-reason'), {
      target: { value: 'Window expired before deployment completed' },
    });
    fireEvent.click(screen.getByTestId('webhook-reject-submit'));
    expect(onSendCallback).toHaveBeenCalledWith({
      action: 'reject',
      reason: 'Window expired before deployment completed',
      data: undefined,
    });
  });

  it('refuses to submit a reject without a reason', () => {
    const { onSendCallback } = renderPanel();
    fireEvent.click(screen.getByTestId('webhook-reject-trigger'));
    fireEvent.click(screen.getByTestId('webhook-reject-submit'));
    expect(onSendCallback).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/reason is required/i);
  });

  it('disables submit buttons while a callback is pending', () => {
    renderPanel({ isPending: true });
    // While a callback is in flight, the trigger buttons must be disabled
    // so the operator does not double-submit a destructive action.
    expect(screen.getByTestId('webhook-approve-trigger')).toBeDisabled();
    expect(screen.getByTestId('webhook-reject-trigger')).toBeDisabled();
  });
});