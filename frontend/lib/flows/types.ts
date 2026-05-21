// Flow Draft Types for Guided Builder.
//
// The shape below mirrors the backend DSL exactly (one nested key per
// top-level section). UI-only state (active section, expanded cards, etc.)
// lives in `BuilderUiState`, not on the semantic draft.

export type PlannerMode = 'deterministic' | 'agentic';

export type FormFieldType = 'string' | 'integer' | 'number' | 'boolean' | 'text';
export type FormFieldFormat = 'email' | 'uri';

export interface FlowFormField {
  name: string;
  type: FormFieldType;
  required?: boolean;
  description?: string;
  title?: string;
  default?: unknown;
  enum?: unknown[];
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  format?: FormFieldFormat;
}

export interface FlowSection {
  name: string;
  version?: string;
  description: string;
  owners?: string[];
  labels?: Record<string, string>;
}

export interface FormSection {
  fields: FlowFormField[];
}

export interface FlowTriggers {
  manual?: boolean;
  webhook?: {
    enabled: boolean;
    event?: string;
    path?: string;
    signature_header?: string;
  };
  schedule?: {
    enabled: boolean;
    cron?: string;
    timezone?: string;
  };
}

export type RetryBackoffMode = 'constant' | 'linear' | 'exponential';

export interface RetryBackoff {
  mode: RetryBackoffMode;
  base_ms?: number;
  max_ms?: number;
  jitter?: boolean;
}

export interface RetrySpec {
  attempts?: number;
  backoff?: RetryBackoff;
}

export interface PiiToolException {
  allow: string[];
}

export interface FlowPolicies {
  budget_usd?: number;
  concurrency?: {
    per_flow?: number;
    per_user?: number;
  };
  defaults?: {
    retry?: RetrySpec;
    timeout_ms?: number;
    continue_on_fail?: boolean;
  };
  pii?: {
    allow?: boolean;
    tokenize_model_inputs?: boolean;
    exceptions?: {
      tools?: Record<string, PiiToolException | string[]>;
    };
  };
  rate_limits?: Record<string, { rpm: number }>;
}

export interface FlowTelemetry {
  trace_level?: 'off' | 'meta' | 'brief' | 'verbose';
  sample_rate?: number;
}

export interface FlowCredentials {
  uses: string[];
}

export type StepType =
  | 'tool.call'
  | 'condition'
  | 'human.approval'
  | 'webhook.wait'
  | 'artifact.store'
  | 'artifact.retrieve'
  | 'ai.extract'
  | 'ai.generate'
  | 'ai.route'
  | 'ai.score'
  | 'ai.assess'
  | 'ai.normalize'
  | 'ai.match'
  | 'ai.evaluate'
  | 'ai.compare'
  | 'ai.translate'
  | 'ai.summarize'
  | 'ai.plan';

export interface WorkflowStepDraft {
  id: string;
  type: StepType;
  // UI-only convenience for display; not serialized.
  name?: string;
  description?: string;
  instruction?: string;
  tool?: string;
  params?: Record<string, unknown>;
  expect?: unknown;
  if?: string;
  branches_enum?: string[];
  uses_credentials?: string[];
  retry?: RetrySpec;
  temperature?: number;
  max_tokens?: number;
  word_cap?: number;
  // Step-type-specific extras (locale, top_k, etc.). Preserved verbatim.
  extras?: Record<string, unknown>;
}

export interface WorkflowSection {
  planner_mode: PlannerMode;
  steps: WorkflowStepDraft[];
}

/**
 * The semantic draft. One nested key per DSL top-level section. The
 * generator and parser both treat this as the canonical in-memory shape.
 */
export interface FlowDraft {
  schema_version: 1;
  flow: FlowSection;
  form?: FormSection;
  triggers?: FlowTriggers;
  policies?: FlowPolicies;
  telemetry?: FlowTelemetry;
  credentials?: FlowCredentials;
  workflow: WorkflowSection;
}

/** UI-only state — never serialized, never sent to the backend. */
export interface BuilderUiState {
  activeSection: string;
}

export interface ValidationError {
  section?: string;
  step_id?: string;
  code?: string;
  message: string;
  line?: number;
  json_pointer?: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
  warnings?: string[];
  validated_at?: Date;
  flow_name?: string;
  workflow_summary?: {
    steps_count: number;
    ai_steps: number;
    credentials: string[];
  };
  form_schema?: any;
  normalized_dsl?: Record<string, unknown>;
}

export type FlowBuilderMode = 'guided' | 'yaml';

// User-facing step type catalog.
export const STEP_TYPES = [
  { value: 'ai.extract', label: 'AI Extract', category: 'AI' },
  { value: 'ai.generate', label: 'AI Generate', category: 'AI' },
  { value: 'ai.route', label: 'AI Route', category: 'AI' },
  { value: 'ai.score', label: 'AI Score', category: 'AI' },
  { value: 'ai.assess', label: 'AI Assess', category: 'AI' },
  { value: 'ai.normalize', label: 'AI Normalize', category: 'AI' },
  { value: 'ai.match', label: 'AI Match', category: 'AI' },
  { value: 'ai.evaluate', label: 'AI Evaluate', category: 'AI' },
  { value: 'ai.compare', label: 'AI Compare', category: 'AI' },
  { value: 'ai.translate', label: 'AI Translate', category: 'AI' },
  { value: 'ai.summarize', label: 'AI Summarize', category: 'AI' },
  { value: 'ai.plan', label: 'AI Plan', category: 'AI' },
  { value: 'condition', label: 'Condition', category: 'Control' },
  { value: 'human.approval', label: 'Human Approval', category: 'Control' },
  { value: 'webhook.wait', label: 'Webhook Wait', category: 'Integration' },
  { value: 'tool.call', label: 'Tool Call', category: 'Integration' },
  { value: 'artifact.store', label: 'Store Artifact', category: 'Data' },
  { value: 'artifact.retrieve', label: 'Retrieve Artifact', category: 'Data' },
] as const satisfies ReadonlyArray<{ value: StepType; label: string; category: string }>;

export const AI_STEP_TYPES: ReadonlySet<StepType> = new Set([
  'ai.extract',
  'ai.generate',
  'ai.route',
  'ai.score',
  'ai.assess',
  'ai.normalize',
  'ai.match',
  'ai.evaluate',
  'ai.compare',
  'ai.translate',
  'ai.summarize',
  'ai.plan',
]);

export const FIELD_TYPES = [
  { value: 'string', label: 'Text' },
  { value: 'text', label: 'Long text' },
  { value: 'integer', label: 'Integer' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
] as const satisfies ReadonlyArray<{ value: FormFieldType; label: string }>;

export const PII_POLICIES = [
  { value: 'disallow', label: 'Disallow' },
  { value: 'tokenize', label: 'Tokenize' },
  { value: 'allow_with_warning', label: 'Allow with Warning' },
] as const;

export type PiiPolicyValue = (typeof PII_POLICIES)[number]['value'];

export function piiPolicyToBackend(value: PiiPolicyValue): {
  allow: boolean;
  tokenize_model_inputs: boolean;
} {
  switch (value) {
    case 'allow_with_warning':
      return { allow: true, tokenize_model_inputs: false };
    case 'tokenize':
      return { allow: false, tokenize_model_inputs: true };
    case 'disallow':
    default:
      return { allow: false, tokenize_model_inputs: false };
  }
}

export function piiPolicyFromBackend(pii?: {
  allow?: boolean;
  tokenize_model_inputs?: boolean;
}): PiiPolicyValue {
  if (!pii) return 'disallow';
  if (pii.allow === true) return 'allow_with_warning';
  if (pii.tokenize_model_inputs === true) return 'tokenize';
  return 'disallow';
}

// ---- Default factories ---------------------------------------------------

export function emptyDraft(overrides?: Partial<FlowDraft>): FlowDraft {
  return {
    schema_version: 1,
    flow: { name: 'new_flow', version: '1.0', description: '' },
    triggers: { manual: true },
    policies: {
      budget_usd: 1.0,
      pii: { allow: false, tokenize_model_inputs: false },
    },
    workflow: { planner_mode: 'deterministic', steps: [] },
    ...overrides,
  };
}
