/**
 * The console must trust the backend's event.severity, not just a name
 * heuristic on event_type. The backend emits e.g. policy.blocked with
 * severity "error" and verifier.escalated / policy.pii_redacted with
 * severity "warn" — none of these contain "error"/"failed"/"warn" in their
 * type, so the old heuristic filed them under Info and the Error/Warning
 * filters hid exactly the events an operator is looking for.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import { EnhancedConsolePanel } from '@/components/runs/console-panel';
import type { Event, Severity } from '@/lib/types';

window.HTMLElement.prototype.scrollIntoView = vi.fn();
afterEach(cleanup);

function evt(
  id: string,
  eventType: Event['event_type'],
  severity: Severity,
  summary: string,
): Event {
  return {
    id,
    event_type: eventType,
    timestamp: `2026-06-04T12:00:0${id.length}.000Z`,
    schema_version: 1,
    seq: Number(id.replace(/\D/g, '')) || 1,
    run_id: 'run-1',
    step_id: null,
    correlation_id: null,
    planner_mode: 'deterministic',
    severity,
    actor: 'system',
    summary,
    payload: {},
    tags: {},
  };
}

function renderPanel(events: Event[]) {
  return render(
    <EnhancedConsolePanel
      events={events}
      steps={[]}
      selectedStepId={null}
      onSelectStep={() => {}}
      onClearStepFilter={() => {}}
    />,
  );
}

describe('console level classification uses event.severity', () => {
  it('REGRESSION: policy.blocked with severity=error counts and filters as an error', () => {
    renderPanel([
      evt('e1', 'policy.blocked', 'error', 'Tool call blocked by policy'),
      evt('e2', 'step.completed', 'info', 'Step done'),
    ]);

    expect(screen.getByText('Error (1)')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Error (1)'));
    expect(screen.getByText('Tool call blocked by policy')).toBeInTheDocument();
    expect(screen.queryByText('Step done')).toBeNull();
  });

  it('REGRESSION: verifier.escalated with severity=warn counts and filters as a warning', () => {
    renderPanel([
      evt('e1', 'verifier.escalated', 'warn', 'Verifier escalated to human'),
      evt('e2', 'step.completed', 'info', 'Step done'),
    ]);

    expect(screen.getByText('Warning (1)')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Warning (1)'));
    expect(screen.getByText('Verifier escalated to human')).toBeInTheDocument();
    expect(screen.queryByText('Step done')).toBeNull();
  });

  it('falls back to the type heuristic when severity carries no signal', () => {
    // An emitter that forgot to set severity (defaults to info) on a
    // failure-shaped event type must still be classified as an error.
    renderPanel([evt('e1', 'step.failed', 'info', 'Step blew up')]);
    expect(screen.getByText('Error (1)')).toBeInTheDocument();
  });
});
