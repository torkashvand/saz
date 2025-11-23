/**
 * Utilities for building display steps from planned and executed steps
 */

import type { PlannedStep, RunStep, PlannerMode } from '@/lib/types';

export type DisplayStep =
  | { kind: 'executed'; index: number; planned?: PlannedStep; step: RunStep }
  | { kind: 'planned'; index: number; planned: PlannedStep };

/**
 * Build display steps based on planner mode
 * For deterministic: merge planned + executed steps
 * For agentic: show only executed steps
 */
export function buildDisplaySteps(
  plannerMode: PlannerMode,
  plannedSteps: PlannedStep[] | undefined,
  executedSteps: RunStep[]
): DisplayStep[] {
  // For agentic or when no planned steps available, show only executed
  if (plannerMode !== 'deterministic' || !plannedSteps || plannedSteps.length === 0) {
    return executedSteps.map(step => ({
      kind: 'executed' as const,
      index: step.number,
      step,
    }));
  }

  // For deterministic: show all planned steps, fill in with executed data
  return plannedSteps.map((planned, index) => {
    // Match executed step by number (which should be index for deterministic)
    const executedStep = executedSteps.find(s => s.number === index);

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
