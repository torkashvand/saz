/**
 * Live WebSocket overlay derivations for the run detail page.
 *
 * The canonical source of truth is the persisted run (status + steps). The
 * WebSocket events provide a live overlay so the operator sees activity
 * before the next refetch lands. Two invariants keep the overlay honest:
 *
 *   1. Events may make the page MORE current than canonical state (e.g.
 *      run.started arrives before the refetch), but must never contradict a
 *      terminal canonical status. The historical event fetch is capped (the
 *      oldest 500 events), so a long run's terminal events can be missing
 *      from the client buffer — without the canonical gate the last
 *      lifecycle event the client sees is run.started/run.resumed and the
 *      page shows a completed run as "running" forever.
 *
 *   2. Step indicators resolve to canonical planned-step positions by step
 *      NAME, never by the segment-local step_number in event payloads
 *      (which restarts at 0 after resume/retry).
 */

import type { PlannedStep, PlannerMode, RunStatus, RunStep } from '@/lib/types';
import { buildDisplaySteps, resolveCanonicalStepIndex, type DisplayStep } from './display-steps';

/** Structural subset of lib/types Event that the overlay derivations read. */
export interface LiveEvent {
  event_type: string;
  step_id: string | null;
  payload: Record<string, any>;
  summary: string;
}

/** Terminal statuses: the run can never be running again without a retry. */
export function isTerminalRunStatus(status: RunStatus | undefined): boolean {
  return status === 'completed' || status === 'failed';
}

/**
 * Detect run activity from lifecycle events (last event wins), gated on the
 * canonical run status: a terminal canonical status always wins over the
 * event buffer, which may be truncated and missing the terminal event.
 * 'suspended' is NOT gated — during resume the run.resumed event legitimately
 * leads the canonical status.
 */
export function deriveIsRunningFromEvents(
  events: Array<Pick<LiveEvent, 'event_type'>>,
  canonicalStatus?: RunStatus,
): boolean {
  if (isTerminalRunStatus(canonicalStatus)) {
    return false;
  }
  let active = false;
  for (const e of events) {
    if (e.event_type === 'run.started' || e.event_type === 'run.resumed') {
      active = true;
    } else if (
      e.event_type === 'run.completed' ||
      e.event_type === 'run.failed' ||
      e.event_type === 'run.suspended'
    ) {
      active = false;
    }
  }
  return active;
}

/**
 * Derive the set of canonical step indexes currently running, from step
 * lifecycle events. Run-level terminal/pause events clear all indicators;
 * a terminal canonical status clears everything regardless of the buffer.
 */
export function deriveRunningIndexes(
  events: LiveEvent[],
  executedSteps: RunStep[],
  plannedSteps: PlannedStep[],
  canonicalStatus?: RunStatus,
): Set<number> {
  const running = new Set<number>();
  if (isTerminalRunStatus(canonicalStatus)) {
    return running;
  }

  events.forEach((event) => {
    // Run-level terminal / pause events: clear ALL running indicators.
    // When a run suspends (approval gate), completes, or fails, no step
    // should remain in the live "running" set. Without this, a step
    // that was started before suspension stays falsely lit as running,
    // and after retry/resume the UI shows two running steps at once.
    if (
      event.event_type === 'run.suspended' ||
      event.event_type === 'run.completed' ||
      event.event_type === 'run.failed'
    ) {
      running.clear();
      return;
    }

    // Step-level suspension (approval step marked suspended)
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
 * When the run is active but no step.started event has arrived yet (planner
 * is generating the plan), infer which step will run next so the step cards
 * and timeline show immediate feedback. Returns the input set untouched when
 * confirmed running steps exist or the run is not active.
 */
export function computeEffectiveRunningIndexes(
  runningStepNumbers: Set<number>,
  isRunningFromEvents: boolean,
  plannerMode: PlannerMode,
  plannedSteps: PlannedStep[] | undefined,
  executedSteps: RunStep[],
): Set<number> {
  if (runningStepNumbers.size > 0 || !isRunningFromEvents) {
    return runningStepNumbers;
  }
  const steps = buildDisplaySteps(plannerMode, plannedSteps, executedSteps);
  const nextStep = steps.find(
    (s) => s.kind === 'planned' || (s.kind === 'executed' && s.step.status === 'failed'),
  );
  if (nextStep !== undefined) {
    const inferred = new Set(runningStepNumbers);
    inferred.add(nextStep.index);
    return inferred;
  }
  return runningStepNumbers;
}

/**
 * Overlay live running state onto canonical display steps.
 *
 * After retry, the canonical step may still be "failed" (old attempt) while
 * a new attempt is running. The overlay handles BOTH cases:
 *   1. kind === 'planned' (step never executed) → synthetic running step
 *   2. kind === 'executed' with a terminal status (older attempt) → override
 *      with running status and the next attempt number
 */
export function applyLiveOverlay(steps: DisplayStep[], runningIndexes: Set<number>): DisplayStep[] {
  return steps.map((displayStep) => {
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
          // Signal that this is the next attempt beyond what's persisted
          attempt: displayStep.step.attempt + 1,
        },
      };
    }

    return displayStep;
  });
}
