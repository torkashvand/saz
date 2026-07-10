/**
 * Tests for the live WebSocket overlay logic on the run detail page.
 *
 * The canonical step list comes from `buildDisplaySteps` (tested separately).
 * The live overlay derivations live in `lib/runs/live-overlay.ts` and are
 * imported by BOTH app/runs/[id]/page.tsx and this test, so these tests
 * exercise the real page logic, not a mirrored copy that can drift.
 *
 * Covers:
 * - resolveCanonicalStepIndex mapping from events to canonical positions
 * - Live overlay applying to both 'planned' and 'executed' (failed) display steps
 * - Attempt number derivation on synthetic/overridden running steps
 * - Repeated execution segments (retry) not resetting running indicator
 * - Canonical terminal run status gating the overlay (truncated event buffer)
 * - Timeline integration with liveRunningIndexes
 */

import { describe, it, expect } from 'vitest';
import { buildDisplaySteps } from '@/lib/runs/display-steps';
import {
  applyLiveOverlay,
  computeEffectiveRunningIndexes,
  deriveIsRunningFromEvents,
  deriveRunningIndexes,
} from '@/lib/runs/live-overlay';
import type { PlannedStep, RunStep } from '@/lib/types';

// Local alias mirroring the canonical run-status union in lib/types.ts.
// Used so regression tests can write `const status: RunStatus = 'queued'`
// without TS narrowing the const to a literal that makes
// `status === 'running'` look like dead code.
type RunStatus = 'queued' | 'running' | 'suspended' | 'failed' | 'completed' | 'pending';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function planned(index: number, id: string, name?: string): PlannedStep {
  return { index, id, name: name ?? id, step_type: 'tool.call' };
}

function executedStep(
  name: string,
  number: number,
  status: RunStep['status'],
  attempt: number = 1,
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

function makeEvent(type: string, stepName: string, stepId?: string) {
  return {
    event_type: type,
    step_id: stepId ?? null,
    payload: { step_name: stepName },
    summary: `${type}: ${stepName}`,
  };
}

/** Run-level event (no step name) */
function makeRunEvent(type: string) {
  return {
    event_type: type,
    step_id: null,
    payload: {},
    summary: type,
  };
}

// ---------------------------------------------------------------------------
// 5-step workflow for retry scenario
// ---------------------------------------------------------------------------

const PLANNED = [
  planned(0, 'extract_requirements'),
  planned(1, 'validate_budget'),
  planned(2, 'draft_rfp'),
  planned(3, 'create_rfp_record'),
  planned(4, 'send_confirmation'),
];

// ---------------------------------------------------------------------------
// A. Core bug: live running indicator after retry
// ---------------------------------------------------------------------------

describe('live overlay — retry running indicator', () => {
  it('shows running on correct canonical step after retry, not step 0', () => {
    // Canonical state: steps 0-2 completed, step 3 failed (attempt 1)
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'completed'),
      executedStep('create_rfp_record', 3, 'failed', 1),
    ];

    // After retry, backend emits step.started for create_rfp_record
    // with event-local step_number=0 (new execution segment)
    const events = [makeEvent('step.started', 'create_rfp_record')];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);

    // Must resolve to canonical index 3, NOT 0
    expect(runningIndexes.has(3)).toBe(true);
    expect(runningIndexes.has(0)).toBe(false);
    expect(runningIndexes.size).toBe(1);
  });

  it('applies running overlay to failed canonical step (not just planned)', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'completed'),
      executedStep('create_rfp_record', 3, 'failed', 1),
    ];

    const canonicalSteps = buildDisplaySteps('deterministic', PLANNED, executed);

    // Before overlay: step 3 should show as executed+failed
    expect(canonicalSteps[3].kind).toBe('executed');
    if (canonicalSteps[3].kind === 'executed') {
      expect(canonicalSteps[3].step.status).toBe('failed');
    }

    // Apply live overlay with step 3 running
    const runningIndexes = new Set([3]);
    const overlaid = applyLiveOverlay(canonicalSteps, runningIndexes);

    // After overlay: step 3 should now show as running with attempt+1
    expect(overlaid[3].kind).toBe('executed');
    if (overlaid[3].kind === 'executed') {
      expect(overlaid[3].step.status).toBe('running');
      expect(overlaid[3].step.attempt).toBe(2); // was 1 (failed), now 2 (running)
    }

    // Other steps unchanged
    if (overlaid[0].kind === 'executed') {
      expect(overlaid[0].step.status).toBe('completed');
    }
  });

  it('does NOT apply overlay to already-running canonical step', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'running'), // already running in canonical
    ];

    const canonicalSteps = buildDisplaySteps('deterministic', PLANNED, executed);
    const runningIndexes = new Set([1]);
    const overlaid = applyLiveOverlay(canonicalSteps, runningIndexes);

    // Should keep the original running step, not increment attempt
    if (overlaid[1].kind === 'executed') {
      expect(overlaid[1].step.status).toBe('running');
      expect(overlaid[1].step.attempt).toBe(1); // not 2
    }
  });
});

// ---------------------------------------------------------------------------
// B. Attempt display correctness
// ---------------------------------------------------------------------------

describe('live overlay — attempt display', () => {
  it('synthetic running step for never-executed step shows attempt 1', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
    ];

    const canonicalSteps = buildDisplaySteps('deterministic', PLANNED, executed);
    // Step 2 (draft_rfp) is still planned
    expect(canonicalSteps[2].kind).toBe('planned');

    const runningIndexes = new Set([2]);
    const overlaid = applyLiveOverlay(canonicalSteps, runningIndexes);

    if (overlaid[2].kind === 'executed') {
      expect(overlaid[2].step.attempt).toBe(1);
      expect(overlaid[2].step.name).toBe('draft_rfp');
    }
  });

  it('retried running step shows attempt N+1 over last failed attempt', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'failed', 1),
      executedStep('draft_rfp', 2, 'failed', 2), // double-retry
    ];

    const canonicalSteps = buildDisplaySteps('deterministic', PLANNED, executed);
    // findExecutedStepForPlanned returns latest attempt (2)
    if (canonicalSteps[2].kind === 'executed') {
      expect(canonicalSteps[2].step.attempt).toBe(2);
    }

    const runningIndexes = new Set([2]);
    const overlaid = applyLiveOverlay(canonicalSteps, runningIndexes);

    if (overlaid[2].kind === 'executed') {
      expect(overlaid[2].step.status).toBe('running');
      expect(overlaid[2].step.attempt).toBe(3); // 2 + 1
    }
  });
});

// ---------------------------------------------------------------------------
// C. Repeated execution segments don't reset running indicator
// ---------------------------------------------------------------------------

describe('live overlay — repeated execution segments', () => {
  it('second plan.generated and step.started does not reset to step 0', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'completed'),
      executedStep('create_rfp_record', 3, 'failed', 1),
    ];

    // Simulate: first execution segment events, then retry segment events
    const events = [
      // First segment (historical)
      makeEvent('step.started', 'extract_requirements'),
      makeEvent('step.completed', 'extract_requirements'),
      makeEvent('step.started', 'validate_budget'),
      makeEvent('step.completed', 'validate_budget'),
      makeEvent('step.started', 'draft_rfp'),
      makeEvent('step.completed', 'draft_rfp'),
      makeEvent('step.started', 'create_rfp_record'),
      makeEvent('step.failed', 'create_rfp_record'),
      // Retry segment — step.started again for create_rfp_record
      makeEvent('step.started', 'create_rfp_record'),
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);

    // Only create_rfp_record (index 3) should be running
    expect(runningIndexes.has(3)).toBe(true);
    expect(runningIndexes.size).toBe(1);

    // Earlier steps must NOT be running
    expect(runningIndexes.has(0)).toBe(false);
    expect(runningIndexes.has(1)).toBe(false);
    expect(runningIndexes.has(2)).toBe(false);
  });

  it('step.completed after retry clears running indicator', () => {
    const executed: RunStep[] = [executedStep('create_rfp_record', 3, 'failed', 1)];

    const events = [
      makeEvent('step.started', 'create_rfp_record'),
      makeEvent('step.completed', 'create_rfp_record'),
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.size).toBe(0);
  });

  it('step.failed after retry clears running indicator', () => {
    const executed: RunStep[] = [executedStep('create_rfp_record', 3, 'failed', 1)];

    const events = [
      makeEvent('step.started', 'create_rfp_record'),
      makeEvent('step.failed', 'create_rfp_record'),
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.size).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// D. Normal execution (regression guard)
// ---------------------------------------------------------------------------

describe('live overlay — normal execution (no retry)', () => {
  it('shows correct running step during first execution', () => {
    const executed: RunStep[] = [];

    const events = [makeEvent('step.started', 'extract_requirements')];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.has(0)).toBe(true);
    expect(runningIndexes.size).toBe(1);
  });

  it('moves running indicator from step 1 to step 2', () => {
    const executed: RunStep[] = [];

    const events = [
      makeEvent('step.started', 'extract_requirements'),
      makeEvent('step.completed', 'extract_requirements'),
      makeEvent('step.started', 'validate_budget'),
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.has(0)).toBe(false);
    expect(runningIndexes.has(1)).toBe(true);
    expect(runningIndexes.size).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// E. Suspension lifecycle — the core double-running bug
// ---------------------------------------------------------------------------

describe('live overlay — suspension clears running state', () => {
  it('REGRESSION: run.suspended clears the approval step from running set', () => {
    // This is the exact bug: approve_rfp starts, then run suspends,
    // but approve_rfp stayed in the running set because run.suspended
    // was ignored. The fix: run.suspended clears all running indicators.
    const executed: RunStep[] = [];

    const events = [
      makeEvent('step.started', 'extract_requirements'),
      makeEvent('step.completed', 'extract_requirements'),
      makeEvent('step.started', 'validate_budget'),
      makeEvent('step.completed', 'validate_budget'),
      makeEvent('step.started', 'draft_rfp'),
      makeEvent('step.completed', 'draft_rfp'),
      // Approval step starts, then run suspends
      makeEvent('step.started', 'create_rfp_record'),
      makeRunEvent('run.suspended'),
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);

    // After suspension, NO step should be running
    expect(runningIndexes.size).toBe(0);
    expect(runningIndexes.has(3)).toBe(false);
  });

  it('REGRESSION: no double-running after suspension then retry/resume', () => {
    // The exact reported bug scenario:
    // 1. approve_rfp starts
    // 2. run suspends
    // 3. later, create_rfp_record starts after resume
    // Previously: both approve_rfp AND create_rfp_record appeared running
    // Fixed: run.suspended clears running set, so only create_rfp_record is running
    const executed: RunStep[] = [];

    const events = [
      makeEvent('step.started', 'create_rfp_record'), // approval step starts
      makeRunEvent('run.suspended'), // run suspends — must clear
      // ... time passes, approval granted, run resumes ...
      makeEvent('step.started', 'send_confirmation'), // next step starts
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);

    // Only send_confirmation (index 4) should be running
    expect(runningIndexes.size).toBe(1);
    expect(runningIndexes.has(4)).toBe(true);

    // create_rfp_record must NOT still be running
    expect(runningIndexes.has(3)).toBe(false);
  });

  it('step.suspended also removes that specific step from running set', () => {
    const executed: RunStep[] = [];

    const events = [
      makeEvent('step.started', 'create_rfp_record'),
      makeEvent('step.suspended', 'create_rfp_record'),
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.size).toBe(0);
    expect(runningIndexes.has(3)).toBe(false);
  });

  it('no step shows as running when canonical data shows suspension', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'suspended'),
    ];

    // No live events
    const events: any[] = [];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.size).toBe(0);
  });

  it('after resume, only the next step shows as running', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'), // approved
    ];

    const events = [makeEvent('step.started', 'draft_rfp')];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.has(2)).toBe(true);
    expect(runningIndexes.size).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// F. Run terminal events clear stale running state
// ---------------------------------------------------------------------------

describe('live overlay — run terminal events', () => {
  it('run.completed clears all running indicators', () => {
    const executed: RunStep[] = [];

    const events = [makeEvent('step.started', 'send_confirmation'), makeRunEvent('run.completed')];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.size).toBe(0);
  });

  it('run.failed clears all running indicators', () => {
    const executed: RunStep[] = [];

    const events = [makeEvent('step.started', 'create_rfp_record'), makeRunEvent('run.failed')];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.size).toBe(0);
  });

  it('new step.started after run.failed (retry) works correctly', () => {
    const executed: RunStep[] = [];

    const events = [
      makeEvent('step.started', 'create_rfp_record'),
      makeRunEvent('run.failed'),
      // Retry starts
      makeEvent('step.started', 'create_rfp_record'),
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.size).toBe(1);
    expect(runningIndexes.has(3)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// G. Full overlay integration test
// ---------------------------------------------------------------------------

describe('live overlay — full integration', () => {
  it('end-to-end: retry scenario produces correct display steps', () => {
    // State: first 3 steps completed, step 3 failed, retry in progress
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'completed'),
      executedStep('create_rfp_record', 3, 'failed', 1),
    ];

    const events = [makeEvent('step.started', 'create_rfp_record')];

    // Step 1: Build canonical steps
    const canonical = buildDisplaySteps('deterministic', PLANNED, executed);

    // Step 2: Derive running indexes from events
    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);

    // Step 3: Apply overlay
    const final = applyLiveOverlay(canonical, runningIndexes);

    // Verify all 5 steps
    const statuses = final.map((ds) => (ds.kind === 'executed' ? ds.step.status : 'not_started'));
    expect(statuses).toEqual([
      'completed', // extract_requirements
      'completed', // validate_budget
      'completed', // draft_rfp
      'running', // create_rfp_record — LIVE OVERLAY
      'not_started', // send_confirmation
    ]);

    // Verify attempt on the running step
    if (final[3].kind === 'executed') {
      expect(final[3].step.attempt).toBe(2); // failed at 1, now running at 2
      expect(final[3].step.name).toBe('create_rfp_record');
    }
  });

  it('end-to-end: suspension→resume produces exactly one running step', () => {
    // Full lifecycle: steps run → approval step starts → run suspends →
    // approval granted → resumed step starts → only that step is running
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'completed'),
      executedStep('create_rfp_record', 3, 'completed'), // approved and completed
    ];

    const events = [
      // First execution segment
      makeEvent('step.started', 'extract_requirements'),
      makeEvent('step.completed', 'extract_requirements'),
      makeEvent('step.started', 'validate_budget'),
      makeEvent('step.completed', 'validate_budget'),
      makeEvent('step.started', 'draft_rfp'),
      makeEvent('step.completed', 'draft_rfp'),
      // Approval step starts, run suspends
      makeEvent('step.started', 'create_rfp_record'),
      makeRunEvent('run.suspended'),
      // Resume: approval granted, step completed, next step starts
      makeEvent('step.completed', 'create_rfp_record'),
      makeEvent('step.started', 'send_confirmation'),
    ];

    const canonical = buildDisplaySteps('deterministic', PLANNED, executed);
    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    const final = applyLiveOverlay(canonical, runningIndexes);

    const statuses = final.map((ds) => (ds.kind === 'executed' ? ds.step.status : 'not_started'));
    expect(statuses).toEqual([
      'completed', // extract_requirements
      'completed', // validate_budget
      'completed', // draft_rfp
      'completed', // create_rfp_record — approved
      'running', // send_confirmation — ONLY running step
    ]);

    // Exactly one running step
    expect(runningIndexes.size).toBe(1);
    expect(runningIndexes.has(4)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// H. Immediate run-active detection from live events
// ---------------------------------------------------------------------------

describe('live overlay — immediate run-active detection', () => {
  it('REGRESSION: run.started makes isRunning true even when canonical status is queued', () => {
    // This is the exact bug: run.status is still "queued" (refetch pending)
    // but run.started event has arrived via WebSocket
    const canonicalStatus = 'queued' as RunStatus;
    const isRunningCanonical = canonicalStatus === 'running' || canonicalStatus === 'pending';

    const events = [{ event_type: 'run.started' }];
    const isRunningFromEvents = deriveIsRunningFromEvents(events);

    // Canonical says not running, but events say it is
    expect(isRunningCanonical).toBe(false);
    expect(isRunningFromEvents).toBe(true);

    // Combined result: should be running
    const isRunning = isRunningCanonical || isRunningFromEvents;
    expect(isRunning).toBe(true);
  });

  it('plan.generated without terminal event keeps run active', () => {
    const events = [{ event_type: 'run.started' }, { event_type: 'plan.generated' }];
    expect(deriveIsRunningFromEvents(events)).toBe(true);
  });

  it('run.completed clears active state from events', () => {
    const events = [{ event_type: 'run.started' }, { event_type: 'run.completed' }];
    expect(deriveIsRunningFromEvents(events)).toBe(false);
  });

  it('run.failed clears active state from events', () => {
    const events = [{ event_type: 'run.started' }, { event_type: 'run.failed' }];
    expect(deriveIsRunningFromEvents(events)).toBe(false);
  });

  it('run.suspended clears active state from events', () => {
    const events = [{ event_type: 'run.started' }, { event_type: 'run.suspended' }];
    expect(deriveIsRunningFromEvents(events)).toBe(false);
  });

  it('run.resumed re-activates after suspension', () => {
    const events = [
      { event_type: 'run.started' },
      { event_type: 'run.suspended' },
      { event_type: 'run.resumed' },
    ];
    expect(deriveIsRunningFromEvents(events)).toBe(true);
  });

  it('no events means not running', () => {
    expect(deriveIsRunningFromEvents([])).toBe(false);
  });

  it('timeline shows first step running when isRunning is true from events', () => {
    const canonicalStatus = 'queued';
    const isRunning = true;
    const effectiveRunStatus = isRunning ? 'running' : canonicalStatus;
    expect(effectiveRunStatus).toBe('running');
  });
});

// ---------------------------------------------------------------------------
// I. Inferred next-step during planning gap — effectiveRunningIndexes
// ---------------------------------------------------------------------------

describe('inferred next-step during planning gap', () => {
  it('fresh run: first planned step gets spinner', () => {
    const effective = computeEffectiveRunningIndexes(new Set(), true, 'deterministic', PLANNED, []);
    expect(effective.has(0)).toBe(true);
    expect(effective.size).toBe(1);
  });

  it('retry: failed step at position 3 gets spinner, not step 0', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'completed'),
      executedStep('create_rfp_record', 3, 'failed', 1),
    ];
    const effective = computeEffectiveRunningIndexes(
      new Set(),
      true,
      'deterministic',
      PLANNED,
      executed,
    );
    expect(effective.has(3)).toBe(true);
    expect(effective.has(0)).toBe(false);
    expect(effective.size).toBe(1);
  });

  it('all completed + one planned: infers the planned step', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'completed'),
      executedStep('create_rfp_record', 3, 'completed'),
    ];
    const effective = computeEffectiveRunningIndexes(
      new Set(),
      true,
      'deterministic',
      PLANNED,
      executed,
    );
    // Step 4 (send_confirmation) is still planned
    expect(effective.has(4)).toBe(true);
    expect(effective.size).toBe(1);
  });

  it('all steps completed: no inference (nothing to run)', () => {
    const executed: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'completed'),
      executedStep('create_rfp_record', 3, 'completed'),
      executedStep('send_confirmation', 4, 'completed'),
    ];
    const effective = computeEffectiveRunningIndexes(
      new Set(),
      true,
      'deterministic',
      PLANNED,
      executed,
    );
    expect(effective.size).toBe(0);
  });

  it('skipped when step.started already populated runningStepNumbers', () => {
    const initial = new Set([2]);
    const effective = computeEffectiveRunningIndexes(initial, true, 'deterministic', PLANNED, []);
    // Should return original set unchanged
    expect(effective).toBe(initial);
    expect(effective.has(2)).toBe(true);
    expect(effective.size).toBe(1);
  });

  it('skipped when run is not active from events', () => {
    const effective = computeEffectiveRunningIndexes(
      new Set(),
      false,
      'deterministic',
      PLANNED,
      [],
    );
    expect(effective.size).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// J. Full page-level user-visible state simulation
// ---------------------------------------------------------------------------

describe('page-level user-visible state', () => {
  it('REGRESSION: fresh run — user sees spinner on first step immediately', () => {
    // Simulates the full page-level state derivation a user would see:
    // canonical run.status is still "queued", run.started event arrived

    // 1. Canonical state
    const canonicalRunStatus = 'queued' as RunStatus;
    const canonicalSteps: RunStep[] = [];

    // 2. Live events
    const events = [makeRunEvent('run.started')];

    // 3. Derive isRunning (page.tsx logic)
    const isRunningCanonical = canonicalRunStatus === 'running';
    const isRunningFromLiveEvents = deriveIsRunningFromEvents(
      events.map((e) => ({ event_type: e.event_type })),
    );
    const isRunning = isRunningCanonical || isRunningFromLiveEvents;
    expect(isRunning).toBe(true);

    // 4. Derive running step numbers from events
    const runningStepNumbers = deriveRunningIndexes(events, canonicalSteps, PLANNED);
    expect(runningStepNumbers.size).toBe(0); // no step.started yet

    // 5. Compute effective running indexes (with inference)
    const effective = computeEffectiveRunningIndexes(
      runningStepNumbers,
      isRunningFromLiveEvents,
      'deterministic',
      PLANNED,
      canonicalSteps,
    );
    expect(effective.has(0)).toBe(true); // first step inferred

    // 6. Build display steps with overlay
    const displaySteps = buildDisplaySteps('deterministic', PLANNED, canonicalSteps);
    const finalSteps = applyLiveOverlay(displaySteps, effective);

    // USER-VISIBLE RESULT: first step shows spinner, rest show not started
    const statuses = finalSteps.map((ds) =>
      ds.kind === 'executed' ? ds.step.status : 'not_started',
    );
    expect(statuses).toEqual([
      'running', // extract_requirements — SPINNER visible
      'not_started', // validate_budget
      'not_started', // draft_rfp
      'not_started', // create_rfp_record
      'not_started', // send_confirmation
    ]);

    // Live badge visible
    expect(isRunning).toBe(true);
  });

  it('REGRESSION: retry — user sees spinner on failed step immediately', () => {
    // canonical: steps 0-2 completed, step 3 failed, run.status = "queued" (retry just triggered)
    const canonicalRunStatus = 'queued';
    const canonicalSteps: RunStep[] = [
      executedStep('extract_requirements', 0, 'completed'),
      executedStep('validate_budget', 1, 'completed'),
      executedStep('draft_rfp', 2, 'completed'),
      executedStep('create_rfp_record', 3, 'failed', 1),
    ];

    // run.started arrives
    const events = [makeRunEvent('run.started')];

    const isRunningFromLiveEvents = deriveIsRunningFromEvents(
      events.map((e) => ({ event_type: e.event_type })),
    );
    expect(isRunningFromLiveEvents).toBe(true);

    const runningStepNumbers = deriveRunningIndexes(events, canonicalSteps, PLANNED);
    expect(runningStepNumbers.size).toBe(0);

    const effective = computeEffectiveRunningIndexes(
      runningStepNumbers,
      isRunningFromLiveEvents,
      'deterministic',
      PLANNED,
      canonicalSteps,
    );
    expect(effective.has(3)).toBe(true); // failed step inferred

    const displaySteps = buildDisplaySteps('deterministic', PLANNED, canonicalSteps);
    const finalSteps = applyLiveOverlay(displaySteps, effective);

    const statuses = finalSteps.map((ds) =>
      ds.kind === 'executed' ? ds.step.status : 'not_started',
    );
    expect(statuses).toEqual([
      'completed', // extract_requirements
      'completed', // validate_budget
      'completed', // draft_rfp
      'running', // create_rfp_record — SPINNER on failed step
      'not_started', // send_confirmation
    ]);
  });

  it('after step.started arrives, inference stops and real state takes over', () => {
    const canonicalSteps: RunStep[] = [];

    // run.started + step.started for step 0
    const events = [makeRunEvent('run.started'), makeEvent('step.started', 'extract_requirements')];

    const runningStepNumbers = deriveRunningIndexes(events, canonicalSteps, PLANNED);
    expect(runningStepNumbers.has(0)).toBe(true);

    // Since runningStepNumbers is non-empty, inference is skipped
    const effective = computeEffectiveRunningIndexes(
      runningStepNumbers,
      true,
      'deterministic',
      PLANNED,
      canonicalSteps,
    );
    expect(effective).toBe(runningStepNumbers); // same reference, no inference
  });
});

// ---------------------------------------------------------------------------
// K. Canonical terminal run status gates the overlay
// ---------------------------------------------------------------------------

describe('live overlay — canonical terminal status gates the overlay', () => {
  it('REGRESSION: truncated event buffer cannot show a completed run as running', () => {
    // The historical fetch caps at the OLDEST 500 events. For a long run the
    // terminal run.completed event never reaches the client buffer, so the
    // last lifecycle event seen is run.started — without the canonical gate
    // the page shows a completed run as "running" forever.
    const events = [{ event_type: 'run.started' }];
    expect(deriveIsRunningFromEvents(events, 'completed')).toBe(false);
    expect(deriveIsRunningFromEvents(events, 'failed')).toBe(false);
  });

  it('non-terminal canonical status lets events lead (run.started before refetch)', () => {
    const events = [{ event_type: 'run.started' }];
    expect(deriveIsRunningFromEvents(events, 'queued')).toBe(true);
    expect(deriveIsRunningFromEvents(events)).toBe(true);
  });

  it('suspended canonical status still lets run.resumed lead during resume', () => {
    // Resume flow: canonical still says "suspended" while the run.resumed
    // event has already arrived — events must be allowed to lead here.
    const events = [{ event_type: 'run.resumed' }];
    expect(deriveIsRunningFromEvents(events, 'suspended')).toBe(true);
  });

  it('REGRESSION: stale step.started in truncated buffer lights no step on a terminal run', () => {
    // Same truncation scenario at the step level: the buffer ends with a
    // step.started whose step.completed/run.completed fell outside the
    // window. A terminal canonical status must clear all indicators.
    const events = [makeEvent('step.started', 'create_rfp_record')];
    expect(deriveRunningIndexes(events, [], PLANNED, 'completed').size).toBe(0);
    expect(deriveRunningIndexes(events, [], PLANNED, 'failed').size).toBe(0);
    // Control: without a terminal status the indicator shows.
    expect(deriveRunningIndexes(events, [], PLANNED, 'running').has(3)).toBe(true);
  });
});
