/**
 * Tests for the step mapping fix: after resume, step.number is local to the
 * execution segment.  The UI must match steps to planned positions by NAME,
 * not by number, to avoid painting the wrong bullet.
 *
 * Covers: display-steps.ts (buildDisplaySteps, findExecutedStepForPlanned,
 *         resolveCanonicalStepIndex)
 */

import { describe, it, expect } from 'vitest';
import {
  buildDisplaySteps,
  findExecutedStepForPlanned,
  resolveCanonicalStepIndex,
} from '@/lib/runs/display-steps';
import type { PlannedStep, RunStep } from '@/lib/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal planned step factory */
function planned(index: number, id: string, name?: string): PlannedStep {
  return { index, id, name: name ?? id, step_type: 'tool.call' };
}

/** Minimal executed step factory */
function executed(
  name: string,
  number: number,
  status: RunStep['status'] = 'completed',
): RunStep {
  return {
    id: `db-${name}-${number}`,
    number,
    name,
    attempt: 1,
    step_type: 'tool.call',
    status,
    retry_count: 0,
  };
}

// ---------------------------------------------------------------------------
// Canonical 6-step workflow used in the approval resume scenario
// ---------------------------------------------------------------------------

const PLANNED_STEPS: PlannedStep[] = [
  planned(0, 'extract_requirements'),
  planned(1, 'validate_budget'),
  planned(2, 'draft_rfp'),
  planned(3, 'approve_rfp'),
  planned(4, 'create_rfp_record'),
  planned(5, 'send_confirmation'),
];

// ---------------------------------------------------------------------------
// findExecutedStepForPlanned
// ---------------------------------------------------------------------------

describe('findExecutedStepForPlanned', () => {
  it('matches by planned.id === step.name', () => {
    const step = executed('extract_requirements', 0);
    const p = planned(0, 'extract_requirements');
    expect(findExecutedStepForPlanned([step], p)).toBe(step);
  });

  it('matches by planned.name when id differs', () => {
    const step = executed('Extract Requirements', 0);
    const p = planned(0, 'extract_req', 'Extract Requirements');
    expect(findExecutedStepForPlanned([step], p)).toBe(step);
  });

  it('returns undefined when no match', () => {
    const step = executed('something_else', 0);
    const p = planned(0, 'extract_requirements');
    expect(findExecutedStepForPlanned([step], p)).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// A. Regression: resume must not reset wizard to first bullet
// ---------------------------------------------------------------------------

describe('buildDisplaySteps — resume does not reset wizard', () => {
  it('maps resumed step 0 to correct absolute position, not bullet 1', () => {
    // After resume: steps 0-2 completed originally, step 3 approved (completed),
    // step 4 (create_rfp_record) executing with LOCAL number = 0
    const executedSteps: RunStep[] = [
      executed('extract_requirements', 0, 'completed'),
      executed('validate_budget', 1, 'completed'),
      executed('draft_rfp', 2, 'completed'),
      executed('approve_rfp', 3, 'completed'),
      // Resumed step — LOCAL number 0, NOT absolute 4
      executed('create_rfp_record', 0, 'running'),
    ];

    const result = buildDisplaySteps('deterministic', PLANNED_STEPS, executedSteps);

    // Bullet 1 (extract_requirements) should be completed, not running
    expect(result[0].kind).toBe('executed');
    if (result[0].kind === 'executed') {
      expect(result[0].step.name).toBe('extract_requirements');
      expect(result[0].step.status).toBe('completed');
    }

    // Bullet 5 (create_rfp_record) should be running
    expect(result[4].kind).toBe('executed');
    if (result[4].kind === 'executed') {
      expect(result[4].step.name).toBe('create_rfp_record');
      expect(result[4].step.status).toBe('running');
    }

    // Bullet 6 (send_confirmation) should still be planned/not started
    expect(result[5].kind).toBe('planned');
  });
});

// ---------------------------------------------------------------------------
// B. Failure after resume marks correct step
// ---------------------------------------------------------------------------

describe('buildDisplaySteps — failure after resume', () => {
  it('marks the correct later bullet as failed, not bullet 1', () => {
    const executedSteps: RunStep[] = [
      executed('extract_requirements', 0, 'completed'),
      executed('validate_budget', 1, 'completed'),
      executed('draft_rfp', 2, 'completed'),
      executed('approve_rfp', 3, 'completed'),
      // Resumed step failed — LOCAL number 0
      executed('create_rfp_record', 0, 'failed'),
    ];

    const result = buildDisplaySteps('deterministic', PLANNED_STEPS, executedSteps);

    // Bullet 1 must NOT be failed
    expect(result[0].kind).toBe('executed');
    if (result[0].kind === 'executed') {
      expect(result[0].step.status).toBe('completed');
    }

    // Bullet 5 (create_rfp_record at index 4) must be failed
    expect(result[4].kind).toBe('executed');
    if (result[4].kind === 'executed') {
      expect(result[4].step.status).toBe('failed');
    }
  });
});

// ---------------------------------------------------------------------------
// C. Completed steps remain stable after resume
// ---------------------------------------------------------------------------

describe('buildDisplaySteps — completed steps stable after resume', () => {
  it('preserves all pre-approval completed steps', () => {
    const executedSteps: RunStep[] = [
      executed('extract_requirements', 0, 'completed'),
      executed('validate_budget', 1, 'completed'),
      executed('draft_rfp', 2, 'completed'),
      executed('approve_rfp', 3, 'completed'),
      executed('create_rfp_record', 0, 'completed'),
      executed('send_confirmation', 1, 'completed'),
    ];

    const result = buildDisplaySteps('deterministic', PLANNED_STEPS, executedSteps);

    // Every step should be executed and completed
    result.forEach((ds, i) => {
      expect(ds.kind).toBe('executed');
      if (ds.kind === 'executed') {
        expect(ds.step.status).toBe('completed');
        expect(ds.step.name).toBe(PLANNED_STEPS[i].id);
      }
    });
  });

  it('approval step stays at correct position', () => {
    const executedSteps: RunStep[] = [
      executed('extract_requirements', 0, 'completed'),
      executed('validate_budget', 1, 'completed'),
      executed('draft_rfp', 2, 'completed'),
      executed('approve_rfp', 3, 'suspended'),
    ];

    const result = buildDisplaySteps('deterministic', PLANNED_STEPS, executedSteps);

    expect(result[3].kind).toBe('executed');
    if (result[3].kind === 'executed') {
      expect(result[3].step.name).toBe('approve_rfp');
      expect(result[3].step.status).toBe('suspended');
    }

    // Steps after approval remain planned
    expect(result[4].kind).toBe('planned');
    expect(result[5].kind).toBe('planned');
  });
});

// ---------------------------------------------------------------------------
// D. plan.generated during resume does not reset wizard
// ---------------------------------------------------------------------------

describe('buildDisplaySteps — new plan does not reset state', () => {
  it('only displays canonical planned steps regardless of resumed plan', () => {
    // Even if the backend re-plans with only 2 steps, the display uses
    // the original 6 planned steps from the flow definition.
    const executedSteps: RunStep[] = [
      executed('extract_requirements', 0, 'completed'),
      executed('validate_budget', 1, 'completed'),
      executed('draft_rfp', 2, 'completed'),
      executed('approve_rfp', 3, 'completed'),
      // Resumed plan step 0 — correctly mapped to position 4
      executed('create_rfp_record', 0, 'running'),
    ];

    const result = buildDisplaySteps('deterministic', PLANNED_STEPS, executedSteps);

    // Should have exactly 6 entries (one per planned step)
    expect(result).toHaveLength(6);

    // Each entry should be at the correct canonical index
    result.forEach((ds, i) => {
      expect(ds.index).toBe(i);
    });
  });
});

// ---------------------------------------------------------------------------
// E. Persisted state path — correct after page refresh
// ---------------------------------------------------------------------------

describe('buildDisplaySteps — persisted state after refresh', () => {
  it('renders correctly from API data after resumed failure', () => {
    // This is what the API returns after a page refresh:
    // steps from both execution segments with their local numbers
    const executedSteps: RunStep[] = [
      executed('extract_requirements', 0, 'completed'),
      executed('validate_budget', 1, 'completed'),
      executed('draft_rfp', 2, 'completed'),
      executed('approve_rfp', 3, 'completed'),
      executed('create_rfp_record', 0, 'failed'), // local number 0
    ];

    const result = buildDisplaySteps('deterministic', PLANNED_STEPS, executedSteps);

    const statuses = result.map(ds =>
      ds.kind === 'executed' ? ds.step.status : 'not_started'
    );

    expect(statuses).toEqual([
      'completed',   // extract_requirements
      'completed',   // validate_budget
      'completed',   // draft_rfp
      'completed',   // approve_rfp
      'failed',      // create_rfp_record — CORRECT position
      'not_started', // send_confirmation
    ]);
  });
});

// ---------------------------------------------------------------------------
// F. Non-resume path regression
// ---------------------------------------------------------------------------

describe('buildDisplaySteps — non-resume runs still correct', () => {
  it('normal run without suspension maps correctly', () => {
    const executedSteps: RunStep[] = [
      executed('extract_requirements', 0, 'completed'),
      executed('validate_budget', 1, 'completed'),
      executed('draft_rfp', 2, 'failed'),
    ];

    const result = buildDisplaySteps('deterministic', PLANNED_STEPS, executedSteps);

    expect(result[0].kind).toBe('executed');
    expect(result[1].kind).toBe('executed');
    expect(result[2].kind).toBe('executed');
    if (result[2].kind === 'executed') {
      expect(result[2].step.status).toBe('failed');
    }
    expect(result[3].kind).toBe('planned');
  });

  it('agentic mode uses step.number as index (no planned steps)', () => {
    const executedSteps: RunStep[] = [
      executed('step_a', 0, 'completed'),
      executed('step_b', 1, 'failed'),
    ];

    const result = buildDisplaySteps('agentic', undefined, executedSteps);

    expect(result).toHaveLength(2);
    expect(result[0].index).toBe(0);
    expect(result[1].index).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// G. Duplicate step names (edge case)
// ---------------------------------------------------------------------------

describe('buildDisplaySteps — handles duplicates gracefully', () => {
  it('find() returns first match, which is the original completed step', () => {
    // Pathological case: two steps with number=0 but different names
    // (this is the actual resumed scenario)
    const executedSteps: RunStep[] = [
      executed('extract_requirements', 0, 'completed'),
      executed('create_rfp_record', 0, 'failed'),
    ];

    const result = buildDisplaySteps('deterministic', PLANNED_STEPS, executedSteps);

    // extract_requirements at index 0 should be completed
    if (result[0].kind === 'executed') {
      expect(result[0].step.name).toBe('extract_requirements');
      expect(result[0].step.status).toBe('completed');
    }

    // create_rfp_record at index 4 should be failed
    if (result[4].kind === 'executed') {
      expect(result[4].step.name).toBe('create_rfp_record');
      expect(result[4].step.status).toBe('failed');
    }
  });
});

// ---------------------------------------------------------------------------
// resolveCanonicalStepIndex — live event mapping
// ---------------------------------------------------------------------------

function makeEvent(overrides: {
  step_id?: string | null;
  payload?: Record<string, any>;
  summary?: string;
}) {
  return {
    step_id: overrides.step_id ?? null,
    payload: overrides.payload ?? {},
    summary: overrides.summary ?? '',
  };
}

describe('resolveCanonicalStepIndex', () => {
  it('resolves by payload.step_name to correct canonical index', () => {
    const event = makeEvent({
      payload: { step_name: 'create_rfp_record', step_number: 0 },
    });

    const idx = resolveCanonicalStepIndex(event, [], PLANNED_STEPS);
    // create_rfp_record is at planned index 4, NOT step_number 0
    expect(idx).toBe(4);
  });

  it('resolves by event.step_id → run.steps → planned index', () => {
    const executedSteps: RunStep[] = [
      executed('create_rfp_record', 0, 'running'),
    ];
    // Override the db id to match what the event references
    executedSteps[0].id = 'db-uuid-123';

    const event = makeEvent({ step_id: 'db-uuid-123' });
    const idx = resolveCanonicalStepIndex(event, executedSteps, PLANNED_STEPS);
    expect(idx).toBe(4);
  });

  it('resolves by summary extraction as fallback', () => {
    const event = makeEvent({
      summary: 'Step started: create_rfp_record',
    });
    const idx = resolveCanonicalStepIndex(event, [], PLANNED_STEPS);
    expect(idx).toBe(4);
  });

  it('returns undefined for unrecognized step name', () => {
    const event = makeEvent({
      payload: { step_name: 'nonexistent_step' },
    });
    const idx = resolveCanonicalStepIndex(event, [], PLANNED_STEPS);
    expect(idx).toBeUndefined();
  });

  it('does NOT use step_number from payload as the index', () => {
    // This is the exact bug scenario: step_number=0 but step_name maps to index 4
    const event = makeEvent({
      payload: { step_name: 'create_rfp_record', step_number: 0 },
    });
    const idx = resolveCanonicalStepIndex(event, [], PLANNED_STEPS);
    expect(idx).not.toBe(0);
    expect(idx).toBe(4);
  });

  it('prefers payload.step_name over step_id lookup', () => {
    const executedSteps: RunStep[] = [
      executed('extract_requirements', 0, 'completed'),
    ];
    executedSteps[0].id = 'db-uuid-wrong';

    const event = makeEvent({
      step_id: 'db-uuid-wrong',
      payload: { step_name: 'create_rfp_record' },
    });
    const idx = resolveCanonicalStepIndex(event, executedSteps, PLANNED_STEPS);
    // Should use payload.step_name (create_rfp_record → 4), not step_id lookup
    expect(idx).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// H. Retry: agentic mode deduplicates step attempts
// ---------------------------------------------------------------------------

/** Executed step factory with attempt number */
function executedWithAttempt(
  name: string,
  number: number,
  status: RunStep['status'],
  attempt: number,
): RunStep {
  return {
    id: `db-${name}-a${attempt}`,
    number,
    name,
    attempt,
    step_type: 'tool.call',
    status,
    retry_count: 0,
  };
}

describe('buildDisplaySteps — agentic mode after retry', () => {
  it('shows only latest attempt per step, not duplicates', () => {
    // After retry in agentic mode: step_a has attempt 1 (failed) and attempt 2 (completed)
    const executedSteps: RunStep[] = [
      executedWithAttempt('step_a', 0, 'failed', 1),
      executedWithAttempt('step_a', 0, 'completed', 2),
      executedWithAttempt('step_b', 1, 'completed', 1),
    ];

    const result = buildDisplaySteps('agentic', undefined, executedSteps);

    // Should show 2 steps (one per name), not 3
    expect(result).toHaveLength(2);

    // step_a should show attempt 2 (completed), not attempt 1 (failed)
    expect(result[0].kind).toBe('executed');
    if (result[0].kind === 'executed') {
      expect(result[0].step.name).toBe('step_a');
      expect(result[0].step.status).toBe('completed');
      expect(result[0].step.attempt).toBe(2);
    }

    // step_b should show attempt 1 (completed)
    expect(result[1].kind).toBe('executed');
    if (result[1].kind === 'executed') {
      expect(result[1].step.name).toBe('step_b');
      expect(result[1].step.attempt).toBe(1);
    }
  });

  it('preserves failed status from latest attempt', () => {
    // After double retry: step_a has 3 attempts, latest is still failed
    const executedSteps: RunStep[] = [
      executedWithAttempt('step_a', 0, 'failed', 1),
      executedWithAttempt('step_a', 0, 'failed', 2),
      executedWithAttempt('step_a', 0, 'failed', 3),
    ];

    const result = buildDisplaySteps('agentic', undefined, executedSteps);

    expect(result).toHaveLength(1);
    if (result[0].kind === 'executed') {
      expect(result[0].step.attempt).toBe(3);
      expect(result[0].step.status).toBe('failed');
    }
  });
});

// ---------------------------------------------------------------------------
// I. Retry: deterministic mode shows latest attempt per step
// ---------------------------------------------------------------------------

describe('buildDisplaySteps — deterministic mode after retry', () => {
  it('shows latest attempt for retried step, not historical failure', () => {
    // After retry: draft had attempt 1 (failed) then attempt 2 (completed)
    const executedSteps: RunStep[] = [
      executedWithAttempt('extract_requirements', 0, 'completed', 1),
      executedWithAttempt('validate_budget', 1, 'completed', 1),
      executedWithAttempt('draft_rfp', 2, 'failed', 1),
      executedWithAttempt('draft_rfp', 2, 'completed', 2),
      executedWithAttempt('approve_rfp', 3, 'completed', 1),
      executedWithAttempt('create_rfp_record', 4, 'completed', 1),
      executedWithAttempt('send_confirmation', 5, 'completed', 1),
    ];

    const result = buildDisplaySteps('deterministic', PLANNED_STEPS, executedSteps);

    // draft_rfp at index 2 should show attempt 2 (completed), not attempt 1 (failed)
    expect(result[2].kind).toBe('executed');
    if (result[2].kind === 'executed') {
      expect(result[2].step.name).toBe('draft_rfp');
      expect(result[2].step.status).toBe('completed');
      expect(result[2].step.attempt).toBe(2);
    }

    // All 6 steps should be shown and completed
    const statuses = result.map(ds =>
      ds.kind === 'executed' ? ds.step.status : 'not_started'
    );
    expect(statuses).toEqual([
      'completed', 'completed', 'completed', 'completed', 'completed', 'completed',
    ]);
  });
});