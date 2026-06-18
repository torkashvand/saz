// Human-language validation layer.
//
// Compile errors and editor errors arrive in technical terms (codes, field
// names, "params"). This maps them to business-language messages a business
// user can act on, while preserving the original text for expert mode.

import type { ValidationError, WorkflowStepDraft } from './types';
import { classifyPattern } from './business-step-metadata';

export interface FriendlyError {
  message: string;
  /** The original technical message, kept for expert mode. */
  technical: string;
  stepId?: string;
  section?: string;
  code?: string;
}

function translate(error: ValidationError, step?: WorkflowStepDraft): string {
  const code = error.code ?? '';
  const raw = error.message ?? '';

  if (code === 'json.invalid' || /invalid json|json\.parse|in json/i.test(raw)) {
    return 'The technical settings contain invalid JSON.';
  }
  if (code === 'yaml.invalid') {
    return 'The technical settings contain invalid YAML.';
  }
  if (code === 'step.webhook_wait_missing_event') {
    return 'Choose which response this step should wait for.';
  }
  if (
    code.startsWith('expression.') ||
    code === 'binding.unknown_field' ||
    /unknown form field|no longer exists/i.test(raw)
  ) {
    return 'This mapping points to a field that no longer exists.';
  }

  const isMissing =
    code === 'step.missing_field' ||
    code === 'step.empty_field' ||
    code === 'step.params_not_object';

  if (isMissing && step) {
    const pattern = classifyPattern(step);
    if (pattern === 'approval') return 'Choose who should review this step.';
    if (pattern === 'document_generation') {
      return 'This document step is missing required document settings.';
    }
    if (pattern === 'wait_for_response') {
      return 'Choose which response this step should wait for.';
    }
    if (pattern === 'audit_trail') {
      return 'Choose what this step should save to the audit trail.';
    }
  }

  if (isMissing && /\b(name|description)\b/i.test(raw)) {
    return 'This step needs a visible name.';
  }
  if (code === 'workflow.steps_empty') {
    return 'Add at least one step to this workflow.';
  }
  if (code === 'workflow.planner_mode_required' || code === 'workflow.planner_mode_invalid') {
    return 'This workflow is missing its run mode.';
  }
  if (code === 'step.duplicate_id') {
    return 'Two steps share the same internal name.';
  }

  return raw;
}

export function toFriendlyError(error: ValidationError, step?: WorkflowStepDraft): FriendlyError {
  return {
    message: translate(error, step),
    technical: error.message,
    stepId: error.step_id,
    section: error.section,
    code: error.code,
  };
}

export function toFriendlyErrors(
  errors: ValidationError[],
  stepsById: Record<string, WorkflowStepDraft> = {},
): FriendlyError[] {
  return errors.map((e) => toFriendlyError(e, e.step_id ? stepsById[e.step_id] : undefined));
}
