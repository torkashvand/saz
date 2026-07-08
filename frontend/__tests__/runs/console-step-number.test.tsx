/**
 * Pins step-number labelling consistency in the console panel.
 *
 * Backend step.number is 0-based. The log-line badge rendered it raw ("Step 0")
 * while the step-filter header rendered number + 1 ("Step 1"), so the same step
 * showed two different labels. All user-facing labels must be 1-based and agree.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { EnhancedConsolePanel } from '@/components/runs/console-panel';
import type { Event, RunStep } from '@/lib/types';

// jsdom does not implement scrollIntoView; the panel's auto-scroll effect calls it.
window.HTMLElement.prototype.scrollIntoView = vi.fn();

const STEP: RunStep = {
  id: 'step-abc',
  number: 0,
  name: 'extract_ticket',
  attempt: 1,
  step_type: 'ai.extract',
  status: 'completed',
  retry_count: 0,
};

const EVENT: Event = {
  id: 'evt-1',
  event_type: 'step.started',
  timestamp: '2026-06-04T12:00:00.000Z',
  schema_version: 1,
  seq: 1,
  run_id: 'run-1',
  step_id: 'step-abc',
  correlation_id: null,
  planner_mode: 'deterministic',
  severity: 'info',
  actor: 'system',
  summary: 'Step started',
  payload: {},
  tags: {},
};

afterEach(() => cleanup());

describe('console panel step numbering', () => {
  it('labels the same step identically in the log line and the filter header', () => {
    render(
      <EnhancedConsolePanel
        events={[EVENT]}
        steps={[STEP]}
        selectedStepId="step-abc"
        onSelectStep={() => {}}
        onClearStepFilter={() => {}}
      />,
    );

    // Filter header (already 1-based).
    expect(screen.getByText(/Showing logs for Step 1: extract_ticket/)).toBeTruthy();

    // Log-line badge must show the SAME 1-based number, not the raw 0.
    const badge = screen.getByText('Step 1', { selector: 'button' });
    expect(badge.getAttribute('title')).toBe('Jump to Step 1: extract_ticket');
  });
});
