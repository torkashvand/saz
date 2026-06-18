// Structured binding model for the generic Business Builder.
//
// Business users select where a value comes from (a form field, a previous
// step's output, or a fixed value) through chips/pickers. A FriendlyBinding
// is the UI-side shape; it compiles down to the existing Saz template syntax
// ({{ $form.x }}, {{ $step('id').field }}, or a raw constant) before YAML is
// generated, so nothing about the backend DSL changes.

import type { FlowFormField } from './types';

export type BindingSourceType = 'form' | 'previous_step' | 'constant' | 'system';

export interface FriendlyBinding {
  sourceType: BindingSourceType;
  /** Step id for `previous_step`; unused otherwise. */
  sourceStepId?: string;
  /**
   * Field name for `form`/`previous_step`, the env var for `system`, or the
   * literal value for `constant`. May be empty for a whole-output step ref.
   */
  sourceField: string;
  label?: string;
  /** Literal suffix appended after the expression, e.g. "%". */
  formatter?: string;
  /** Default value used when the source is empty. Only `system` ($env) compiles it. */
  fallback?: string;
  required?: boolean;
}

export interface BindingContext {
  formFields?: FlowFormField[];
  steps?: Array<{ id: string; name?: string }>;
}

export interface BindingValidation {
  valid: boolean;
  message?: string;
}

const STEP_FIELD_RE = /^\{\{\s*\$step\('([^']+)'\)(?:\.([\w.]+))?\s*\}\}(.*)$/;
const FORM_RE = /^\{\{\s*\$form(?:\.([\w.]+))?\s*\}\}(.*)$/;
const ENV_RE = /^\{\{\s*\$env\('([^']+)'(?:,\s*'([^']*)')?\)\s*\}\}(.*)$/;

/** Compile a binding down to a Saz template expression or raw constant. */
export function bindingToExpression(binding: FriendlyBinding): string {
  const suffix = binding.formatter ?? '';
  switch (binding.sourceType) {
    case 'form':
      return binding.sourceField
        ? `{{ $form.${binding.sourceField} }}${suffix}`
        : `{{ $form }}${suffix}`;
    case 'previous_step': {
      const ref = binding.sourceField
        ? `{{ $step('${binding.sourceStepId}').${binding.sourceField} }}`
        : `{{ $step('${binding.sourceStepId}') }}`;
      return `${ref}${suffix}`;
    }
    case 'system': {
      const arg = binding.fallback
        ? `'${binding.sourceField}', '${binding.fallback}'`
        : `'${binding.sourceField}'`;
      return `{{ $env(${arg}) }}${suffix}`;
    }
    case 'constant':
    default:
      return binding.sourceField;
  }
}

/**
 * Best-effort reverse of bindingToExpression. Returns null only for inputs
 * that are not strings; any non-matching string becomes a constant binding so
 * existing YAML always maps to *something* the friendly UI can show.
 */
export function expressionToBinding(value: unknown): FriendlyBinding | null {
  if (typeof value !== 'string') return null;

  const step = value.match(STEP_FIELD_RE);
  if (step) {
    const binding: FriendlyBinding = {
      sourceType: 'previous_step',
      sourceStepId: step[1],
      sourceField: step[2] ?? '',
    };
    if (step[3]) binding.formatter = step[3];
    return binding;
  }

  const form = value.match(FORM_RE);
  if (form) {
    const binding: FriendlyBinding = { sourceType: 'form', sourceField: form[1] ?? '' };
    if (form[2]) binding.formatter = form[2];
    return binding;
  }

  const env = value.match(ENV_RE);
  if (env) {
    const binding: FriendlyBinding = { sourceType: 'system', sourceField: env[1] };
    if (env[2]) binding.fallback = env[2];
    if (env[3]) binding.formatter = env[3];
    return binding;
  }

  return { sourceType: 'constant', sourceField: value };
}

/** Human-readable label for a chip, never showing raw template syntax. */
export function renderBindingLabel(binding: FriendlyBinding, context: BindingContext): string {
  const suffix = binding.formatter ? ` ${binding.formatter}` : '';
  switch (binding.sourceType) {
    case 'form': {
      const field = context.formFields?.find((f) => f.name === binding.sourceField);
      const name = field?.title || field?.name || binding.sourceField;
      return `Form: ${name}${suffix}`;
    }
    case 'previous_step': {
      const step = context.steps?.find((s) => s.id === binding.sourceStepId);
      const name = step?.name || binding.sourceStepId || 'step';
      return binding.sourceField ? `${name} → ${binding.sourceField}${suffix}` : `${name}${suffix}`;
    }
    case 'system':
      return `System: ${binding.sourceField}${suffix}`;
    case 'constant':
    default:
      return binding.sourceField ? `"${binding.sourceField}"` : 'Not set';
  }
}

/** Validate a binding against the fields/steps currently available. */
export function validateBinding(
  binding: FriendlyBinding,
  context: BindingContext,
): BindingValidation {
  if (binding.required) {
    const empty =
      binding.sourceType === 'constant'
        ? !binding.sourceField.trim()
        : binding.sourceType === 'previous_step'
          ? !binding.sourceStepId
          : !binding.sourceField.trim();
    if (empty) {
      return { valid: false, message: 'Choose where this value comes from.' };
    }
  }

  switch (binding.sourceType) {
    case 'form': {
      if (!binding.sourceField) return { valid: true };
      const exists = context.formFields?.some((f) => f.name === binding.sourceField);
      return exists
        ? { valid: true }
        : { valid: false, message: 'This mapping points to a field that no longer exists.' };
    }
    case 'previous_step': {
      if (!binding.sourceStepId) return { valid: true };
      const exists = context.steps?.some((s) => s.id === binding.sourceStepId);
      return exists
        ? { valid: true }
        : { valid: false, message: 'This mapping points to a step that no longer exists.' };
    }
    default:
      return { valid: true };
  }
}
