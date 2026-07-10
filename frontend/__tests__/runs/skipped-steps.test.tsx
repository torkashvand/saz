/**
 * A step skipped by its `when` guard must be visually distinct from a step
 * that has not started yet. Both used to render as "Not started", so an
 * operator could not tell "the workflow deliberately skipped this" from
 * "this still has to run" — on a completed run that reads as a stuck step.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { StepProgressTimeline } from '@/components/runs/step-timeline';
import { CompactStepCard } from '@/components/runs/step-card';
import type { PlannedStep, RunStep } from '@/lib/types';

window.HTMLElement.prototype.scrollIntoView = vi.fn();
afterEach(cleanup);

const PLANNED: PlannedStep[] = [
  { index: 0, id: 'fetch', name: 'fetch', step_type: 'tool.call' },
  { index: 1, id: 'escalate_if_big', name: 'escalate_if_big', step_type: 'human.approval' },
  { index: 2, id: 'notify', name: 'notify', step_type: 'tool.call' },
];

function executed(name: string, number: number, status: RunStep['status']): RunStep {
  return {
    id: `db-${name}`,
    number,
    name,
    attempt: 1,
    step_type: 'tool.call',
    status,
    retry_count: 0,
  };
}

describe('skipped steps render distinctly', () => {
  it('REGRESSION: timeline shows a skipped step as Skipped, not Not started', () => {
    render(
      <StepProgressTimeline
        plannedSteps={PLANNED}
        executedSteps={[
          executed('fetch', 0, 'completed'),
          executed('escalate_if_big', 1, 'skipped'),
          executed('notify', 2, 'completed'),
        ]}
        runStatus="completed"
        selectedStepIndex={null}
        onSelectStep={() => {}}
      />,
    );

    expect(screen.getByLabelText('Step 2: escalate_if_big. Status: Skipped')).toBeInTheDocument();
    // The legend must explain the new state.
    expect(screen.getByText('Skipped')).toBeInTheDocument();
  });

  it('step card shows a skipped marker instead of "Not started yet"', () => {
    render(
      <CompactStepCard
        displayStep={{
          kind: 'executed',
          index: 1,
          planned: PLANNED[1],
          step: executed('escalate_if_big', 1, 'skipped'),
        }}
      />,
    );

    expect(screen.getByText(/skipped/i)).toBeInTheDocument();
    expect(screen.queryByText(/not started yet/i)).toBeNull();
  });
});
