/**
 * Regression: the console filtered logs by step NUMBER. After a resume the
 * segment-local step_number restarts at 0, so two distinct steps can share a
 * number and the console showed the wrong step's logs. Filtering by step id
 * must select exactly the chosen step's events.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { EnhancedConsolePanel } from '@/components/runs/console-panel';
import type { Event, RunStep } from '@/lib/types';

window.HTMLElement.prototype.scrollIntoView = vi.fn();
afterEach(cleanup);

// Two steps that share segment-local number 0 (as happens after a resume).
const STEPS: RunStep[] = [
  {
    id: 'step-a',
    number: 0,
    name: 'first_segment',
    attempt: 1,
    step_type: 'ai.extract',
    status: 'completed',
    retry_count: 0,
  },
  {
    id: 'step-b',
    number: 0,
    name: 'resumed_segment',
    attempt: 1,
    step_type: 'ai.generate',
    status: 'running',
    retry_count: 0,
  },
];

function evt(id: string, stepId: string, summary: string): Event {
  return {
    id,
    event_type: 'step.started',
    timestamp: `2026-06-04T12:00:0${id.length}.000Z`,
    schema_version: 1,
    seq: Number(id.replace(/\D/g, '')) || 1,
    run_id: 'run-1',
    step_id: stepId,
    correlation_id: null,
    planner_mode: 'deterministic',
    severity: 'info',
    actor: 'system',
    summary,
    payload: {},
    tags: {},
  };
}

describe('console step filter by id', () => {
  it('shows only the selected step id, not another step sharing its number', () => {
    render(
      <EnhancedConsolePanel
        events={[evt('e1', 'step-a', 'log for A'), evt('e2', 'step-b', 'log for B')]}
        steps={STEPS}
        selectedStepId="step-b"
        onSelectStep={() => {}}
        onClearStepFilter={() => {}}
      />,
    );
    expect(screen.getByText('log for B')).toBeInTheDocument();
    expect(screen.queryByText('log for A')).toBeNull();
    expect(screen.getByText(/Showing logs for Step 1: resumed_segment/)).toBeInTheDocument();
  });
});
