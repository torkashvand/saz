/**
 * Utilities for building display steps from planned and executed steps
 */

import type { PlannedStep, RunStep, PlannerMode } from '@/lib/types';

export type DisplayStep =
  | { kind: 'executed'; index: number; planned?: PlannedStep; step: RunStep }
  | { kind: 'planned'; index: number; planned: PlannedStep };

/**
 * Reduce a run's step rows to the latest attempt per step name.
 *
 * A run may contain multiple attempts for the same workflow step (from
 * retry). The latest attempt (highest attempt number) is the current
 * effective state. Earlier attempts are historical.
 */
export function latestAttemptsByName(executedSteps: RunStep[]): RunStep[] {
  const latestByName = new Map<string, RunStep>();
  for (const step of executedSteps) {
    const existing = latestByName.get(step.name);
    if (!existing || (step.attempt ?? 1) > (existing.attempt ?? 1)) {
      latestByName.set(step.name, step);
    }
  }
  return [...latestByName.values()];
}

/**
 * Find the latest-attempt executed step matching a planned step by name.
 *
 * A run may contain multiple attempts for the same workflow step (from
 * retry). The latest attempt (highest attempt number) is the
 * current effective state. Earlier attempts are historical.
 */
export function findExecutedStepForPlanned(
  executedSteps: RunStep[],
  planned: PlannedStep,
): RunStep | undefined {
  const matches = executedSteps.filter((s) => s.name === planned.id || s.name === planned.name);
  if (matches.length === 0) return undefined;
  // Return the latest attempt
  return matches.reduce((latest, s) => ((s.attempt ?? 1) > (latest.attempt ?? 1) ? s : latest));
}

/**
 * Build display steps based on planner mode
 * For deterministic: merge planned + executed steps
 * For agentic: show only executed steps
 */
export function buildDisplaySteps(
  plannerMode: PlannerMode,
  plannedSteps: PlannedStep[] | undefined,
  executedSteps: RunStep[],
): DisplayStep[] {
  // For agentic or when no planned steps available, show only executed.
  // After retry, a step name may appear multiple times (one per attempt).
  // Only show the latest attempt per step name so the user sees effective
  // state, not duplicated historical entries.
  if (plannerMode !== 'deterministic' || !plannedSteps || plannedSteps.length === 0) {
    return latestAttemptsByName(executedSteps)
      .sort((a, b) => a.number - b.number)
      .map((step) => ({
        kind: 'executed' as const,
        index: step.number,
        step,
      }));
  }

  // For deterministic: show all planned steps, fill in with executed data
  return plannedSteps.map((planned, index) => {
    // Match by workflow step name, not by number — number is local to
    // each execution segment and becomes wrong after resume.
    const executedStep = findExecutedStepForPlanned(executedSteps, planned);

    if (executedStep) {
      return {
        kind: 'executed' as const,
        index,
        planned,
        step: executedStep,
      };
    }

    return {
      kind: 'planned' as const,
      index,
      planned,
    };
  });
}

/**
 * Map a live WebSocket event to the correct canonical planned-step index
 * by matching the step name from the event against planned steps.
 *
 * This avoids using event.payload.step_number which is local to each
 * execution segment and becomes wrong after resume.
 */
export function resolveCanonicalStepIndex(
  event: { step_id: string | null; payload: Record<string, any>; summary: string },
  executedSteps: RunStep[],
  plannedSteps: PlannedStep[],
): number | undefined {
  let stepName: string | undefined;

  // 1. Best source: step_name from event payload (set by backend emitter)
  if (event.payload?.step_name) {
    stepName = event.payload.step_name;
  }

  // 2. Match event.step_id (DB UUID) against executed steps to get workflow name
  if (!stepName && event.step_id) {
    const matchingStep = executedSteps.find((s) => s.id === event.step_id);
    if (matchingStep) {
      stepName = matchingStep.name;
    }
  }

  // 3. Extract step name from summary (format: "Step started: step_name")
  if (!stepName) {
    const match = event.summary.match(/:\s*(\S+)/);
    if (match) {
      stepName = match[1];
    }
  }

  // Map step name to canonical planned step index
  if (stepName) {
    const idx = plannedSteps.findIndex((p) => p.id === stepName || p.name === stepName);
    if (idx >= 0) return idx;
  }

  return undefined;
}

/**
 * Generate help text for a planned step
 */
export function getStepHelpText(planned: PlannedStep): string {
  const stepType = planned.step_type || 'unknown';

  // Try to generate meaningful help text based on step type
  if (stepType.startsWith('ai.extract')) {
    return 'This step will extract structured data from unstructured text using AI.';
  }
  if (stepType.startsWith('ai.route')) {
    return 'This step will determine the routing path based on the input data.';
  }
  if (stepType.startsWith('ai.score')) {
    return 'This step will generate a numerical score or rating using AI analysis.';
  }
  if (stepType.startsWith('ai.generate')) {
    return 'This step will generate content or responses using AI.';
  }
  if (stepType.startsWith('ai.assess')) {
    return 'This step will assess or evaluate the input data using AI.';
  }
  if (stepType.startsWith('tool.call') || stepType.startsWith('http')) {
    return 'This step will call an external tool or API.';
  }
  if (stepType === 'webhook.wait') {
    return 'This step will wait for an external webhook callback.';
  }
  if (stepType === 'human.approval') {
    return 'This step requires human approval before proceeding.';
  }
  if (stepType.startsWith('artifact.store')) {
    return 'This step will store data as an artifact for later retrieval.';
  }
  if (stepType === 'condition') {
    return 'This step will evaluate a condition and branch accordingly.';
  }

  // Generic fallback
  return 'This step will run after the previous steps complete.';
}
