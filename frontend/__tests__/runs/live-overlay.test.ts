/**
 * Tests for the live WebSocket overlay logic on the run detail page.
 *
 * The canonical step list comes from `buildDisplaySteps` (tested separately).
 * The live overlay derives `runningStepNumbers` from WebSocket events and
 * injects running state into display steps and the timeline.
 *
 * Previous tests only covered the canonical mapping helpers. These tests
 * cover the page-level overlay logic that was the root cause of the
 * "running indicator not showing after retry" bug.
 *
 * Covers:
 * - resolveCanonicalStepIndex mapping from events to canonical positions
 * - Live overlay applying to both 'planned' and 'executed' (failed) display steps
 * - Attempt number derivation on synthetic/overridden running steps
 * - Repeated execution segments (retry) not resetting running indicator
 * - Timeline integration with liveRunningIndexes
 */

import { describe, it, expect } from 'vitest';
import {
  buildDisplaySteps,
  resolveCanonicalStepIndex,
  type DisplayStep,
} from '@/lib/runs/display-steps';
import type { PlannedStep, RunStep } from '@/lib/types';

// ---------------------------------------------------------------------------
// Helpers — mirror page-level overlay logic from app/runs/[id]/page.tsx
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

/**
 * Simulate the page-level runningStepNumbers derivation from events.
 * This MUST mirror the exact logic in page.tsx's useMemo so that tests
 * exercise the real lifecycle behavior, not a stale copy.
 */
function deriveRunningIndexes(
  events: Array<{ event_type: string; step_id: string | null; payload: Record<string, any>; summary: string }>,
  executedSteps: RunStep[],
  plannedSteps: PlannedStep[],
): Set<number> {
  const running = new Set<number>();
  events.forEach(event => {
    // Run-level terminal / pause events: clear ALL running indicators.
    if (
      event.event_type === 'run.suspended' ||
      event.event_type === 'run.completed' ||
      event.event_type === 'run.failed'
    ) {
      running.clear();
      return;
    }

    // Step-level suspension
    if (event.event_type === 'step.suspended') {
      const idx = resolveCanonicalStepIndex(event, executedSteps, plannedSteps);
      if (idx !== undefined) running.delete(idx);
      return;
    }

    // Step lifecycle: started adds, completed/failed removes
    if (
      event.event_type !== 'step.started' &&
      event.event_type !== 'step.completed' &&
      event.event_type !== 'step.failed'
    ) {
      return;
    }
    const canonicalIndex = resolveCanonicalStepIndex(event, executedSteps, plannedSteps);
    if (canonicalIndex !== undefined) {
      if (event.event_type === 'step.started') {
        running.add(canonicalIndex);
      } else {
        running.delete(canonicalIndex);
      }
    }
  });
  return running;
}

/**
 * Simulate the page-level display step overlay from page.tsx's useMemo.
 * Applies live running state to canonical display steps.
 */
function applyLiveOverlay(
  steps: DisplayStep[],
  runningIndexes: Set<number>,
): DisplayStep[] {
  return steps.map(displayStep => {
    if (!runningIndexes.has(displayStep.index)) {
      return displayStep;
    }

    if (displayStep.kind === 'planned') {
      return {
        ...displayStep,
        kind: 'executed' as const,
        step: {
          id: `ws-running-${displayStep.index}`,
          number: displayStep.index,
          name: displayStep.planned.name,
          attempt: 1,
          step_type: displayStep.planned.step_type || 'unknown',
          status: 'running' as const,
          retry_count: 0,
        },
      };
    }

    if (displayStep.kind === 'executed' && displayStep.step.status !== 'running') {
      return {
        ...displayStep,
        step: {
          ...displayStep.step,
          status: 'running' as const,
          attempt: displayStep.step.attempt + 1,
        },
      };
    }

    return displayStep;
  });
}

function makeEvent(
  type: string,
  stepName: string,
  stepId?: string,
) {
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
    const events = [
      makeEvent('step.started', 'create_rfp_record'),
    ];

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
    const executed: RunStep[] = [
      executedStep('create_rfp_record', 3, 'failed', 1),
    ];

    const events = [
      makeEvent('step.started', 'create_rfp_record'),
      makeEvent('step.completed', 'create_rfp_record'),
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.size).toBe(0);
  });

  it('step.failed after retry clears running indicator', () => {
    const executed: RunStep[] = [
      executedStep('create_rfp_record', 3, 'failed', 1),
    ];

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

    const events = [
      makeEvent('step.started', 'extract_requirements'),
    ];

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
      makeEvent('step.started', 'create_rfp_record'),   // approval step starts
      makeRunEvent('run.suspended'),                      // run suspends — must clear
      // ... time passes, approval granted, run resumes ...
      makeEvent('step.started', 'send_confirmation'),     // next step starts
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

    const events = [
      makeEvent('step.started', 'draft_rfp'),
    ];

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

    const events = [
      makeEvent('step.started', 'send_confirmation'),
      makeRunEvent('run.completed'),
    ];

    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);
    expect(runningIndexes.size).toBe(0);
  });

  it('run.failed clears all running indicators', () => {
    const executed: RunStep[] = [];

    const events = [
      makeEvent('step.started', 'create_rfp_record'),
      makeRunEvent('run.failed'),
    ];

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

    const events = [
      makeEvent('step.started', 'create_rfp_record'),
    ];

    // Step 1: Build canonical steps
    const canonical = buildDisplaySteps('deterministic', PLANNED, executed);

    // Step 2: Derive running indexes from events
    const runningIndexes = deriveRunningIndexes(events, executed, PLANNED);

    // Step 3: Apply overlay
    const final = applyLiveOverlay(canonical, runningIndexes);

    // Verify all 5 steps
    const statuses = final.map(ds =>
      ds.kind === 'executed' ? ds.step.status : 'not_started'
    );
    expect(statuses).toEqual([
      'completed',    // extract_requirements
      'completed',    // validate_budget
      'completed',    // draft_rfp
      'running',      // create_rfp_record — LIVE OVERLAY
      'not_started',  // send_confirmation
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

    const statuses = final.map(ds =>
      ds.kind === 'executed' ? ds.step.status : 'not_started'
    );
    expect(statuses).toEqual([
      'completed',    // extract_requirements
      'completed',    // validate_budget
      'completed',    // draft_rfp
      'completed',    // create_rfp_record — approved
      'running',      // send_confirmation — ONLY running step
    ]);

    // Exactly one running step
    expect(runningIndexes.size).toBe(1);
    expect(runningIndexes.has(4)).toBe(true);
  });
});