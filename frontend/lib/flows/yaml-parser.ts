import jsYaml from 'js-yaml';
import type {
  FlowDraft,
  FlowFormField,
  FlowPolicies,
  FlowSection,
  FlowTelemetry,
  FormFieldType,
  PiiToolException,
  PlannerMode,
  RetrySpec,
  StepType,
  WorkflowStepDraft,
} from './types';
import { piiPolicyFromBackend } from './types';
import type { CompileFlowResponse } from '../types';
import { api } from '../api';

export interface ParsedError {
  message: string;
  section?: string;
  step_id?: string;
  code?: string;
}

export type FlowDraftParseResult =
  | { ok: true; draft: FlowDraft; warnings?: string[]; compileResponse: CompileFlowResponse }
  | { ok: false; errors: ParsedError[]; advanced?: boolean };

const KNOWN_STEP_TYPES: ReadonlySet<StepType> = new Set([
  'tool.call',
  'condition',
  'human.approval',
  'webhook.wait',
  'artifact.store',
  'artifact.retrieve',
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

const KNOWN_STEP_KEYS = new Set([
  'id',
  'type',
  'description',
  'instruction',
  'tool',
  'if',
  'params',
  'expect',
  'branches_enum',
  'uses_credentials',
  'retry',
  'temperature',
  'max_tokens',
  'word_cap',
]);

/**
 * Parse YAML into FlowDraft. Validates against the backend compile endpoint
 * to keep the builder honest about what the runtime will accept, then maps
 * the parsed YAML into our semantic nested draft.
 */
export async function yamlToDraft(yaml: string): Promise<FlowDraftParseResult> {
  if (!yaml.trim()) {
    return { ok: false, errors: [{ message: 'YAML content is required' }] };
  }

  let raw: unknown;
  try {
    raw = jsYaml.load(yaml);
  } catch (error: any) {
    return {
      ok: false,
      errors: [{ message: error?.message || 'Invalid YAML', section: 'yaml' }],
    };
  }

  let compileResponse: CompileFlowResponse;
  try {
    compileResponse = await api.compileFlow({ yaml });
  } catch (error: any) {
    return {
      ok: false,
      errors: [{ message: error?.message || 'Failed to validate YAML', section: 'validation' }],
    };
  }

  // The new /compile contract returns valid=false with structured errors
  // instead of throwing. Surface them so the builder can map per-section.
  if (compileResponse.valid === false) {
    const errors: ParsedError[] = (compileResponse.errors || []).map((e) => ({
      message: e.message,
      section: e.section || undefined,
      step_id: e.step_id || undefined,
      code: e.code,
    }));
    return {
      ok: false,
      errors: errors.length > 0 ? errors : [{ message: 'Validation failed' }],
    };
  }

  const draft = mapToDraft(raw, compileResponse);

  const advancedCheck = checkForAdvancedFeatures(raw);
  if (!advancedCheck.supported) {
    return {
      ok: false,
      advanced: true,
      errors: [
        {
          message: `Advanced DSL features detected: ${advancedCheck.reasons.join(', ')}. Guided Builder is disabled.`,
          section: 'advanced',
        },
      ],
    };
  }

  return { ok: true, draft, warnings: compileResponse.warnings, compileResponse };
}

function mapToDraft(raw: unknown, compileResponse: CompileFlowResponse): FlowDraft {
  const obj = isObject(raw) ? raw : {};
  const flowSrc = isObject(obj.flow) ? obj.flow : {};
  const formSrc = isObject(obj.form) ? obj.form : {};
  const policiesSrc = isObject(obj.policies) ? obj.policies : {};
  const telemetrySrc = isObject(obj.telemetry) ? obj.telemetry : {};
  const credsSrc = isObject(obj.credentials) ? obj.credentials : {};
  const workflowSrc = isObject(obj.workflow) ? obj.workflow : {};

  const flow: FlowSection = {
    name: asString(flowSrc.name) || compileResponse.flow_name || '',
    description: asString(flowSrc.description) || compileResponse.flow_description || '',
  };
  const version = asString(flowSrc.version) || compileResponse.flow_version;
  if (version) flow.version = version;
  const owners = asStringArray(flowSrc.owners);
  if (owners) flow.owners = owners;
  const labels = parseLabels(flowSrc.labels);
  if (labels) flow.labels = labels;

  const fields = parseFormFields(formSrc.fields);
  const formFields = fields.length > 0 ? fields : undefined;

  const credsUses = asStringArray(credsSrc.uses) || compileResponse.workflow_summary?.credentials;
  const credentials = credsUses && credsUses.length > 0 ? { uses: credsUses } : undefined;

  const draft: FlowDraft = {
    schema_version: 1,
    flow,
    workflow: {
      planner_mode: parsePlannerMode(workflowSrc.planner_mode),
      steps: parseSteps(workflowSrc.steps),
    },
  };

  if (formFields) draft.form = { fields: formFields };
  const policies = parsePolicies(policiesSrc);
  if (policies) draft.policies = policies;
  const telemetry = parseTelemetry(telemetrySrc);
  if (telemetry) draft.telemetry = telemetry;
  if (credentials) draft.credentials = credentials;

  return draft;
}

function parsePlannerMode(value: unknown): PlannerMode {
  return value === 'agentic' ? 'agentic' : 'deterministic';
}

function parseLabels(value: unknown): Record<string, string> | undefined {
  if (!isObject(value)) return undefined;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(value)) {
    if (typeof v === 'string') out[k] = v;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function parseFormFields(value: unknown): FlowFormField[] {
  if (!Array.isArray(value)) return [];
  const out: FlowFormField[] = [];
  for (const raw of value) {
    if (!isObject(raw)) continue;
    const name = asString(raw.name);
    if (!name) continue;
    const type = parseFormFieldType(raw.type);
    const field: FlowFormField = { name, type };
    if (raw.required === true) field.required = true;
    if (typeof raw.description === 'string') field.description = raw.description;
    if (typeof raw.title === 'string') field.title = raw.title;
    if (raw.default !== undefined) field.default = raw.default;
    if (Array.isArray(raw.enum)) field.enum = [...raw.enum];
    const pattern = typeof raw.pattern === 'string' ? raw.pattern : asString(raw.regex);
    if (pattern) field.pattern = pattern;
    if (typeof raw.minLength === 'number') field.minLength = raw.minLength;
    if (typeof raw.maxLength === 'number') field.maxLength = raw.maxLength;
    const minimum =
      typeof raw.minimum === 'number'
        ? raw.minimum
        : typeof raw.min === 'number'
          ? raw.min
          : undefined;
    if (minimum !== undefined) field.minimum = minimum;
    const maximum =
      typeof raw.maximum === 'number'
        ? raw.maximum
        : typeof raw.max === 'number'
          ? raw.max
          : undefined;
    if (maximum !== undefined) field.maximum = maximum;
    if (raw.format === 'email' || raw.format === 'uri') field.format = raw.format;
    out.push(field);
  }
  return out;
}

function parseFormFieldType(value: unknown): FormFieldType {
  if (
    value === 'string' ||
    value === 'integer' ||
    value === 'number' ||
    value === 'boolean' ||
    value === 'text'
  ) {
    return value;
  }
  return 'string';
}

function parsePolicies(value: Record<string, unknown>): FlowPolicies | undefined {
  const out: FlowPolicies = {};
  let touched = false;
  if (typeof value.budget_usd === 'number') {
    out.budget_usd = value.budget_usd;
    touched = true;
  }

  if (isObject(value.concurrency)) {
    const c: { per_flow?: number; per_user?: number } = {};
    if (typeof value.concurrency.per_flow === 'number') c.per_flow = value.concurrency.per_flow;
    if (typeof value.concurrency.per_user === 'number') c.per_user = value.concurrency.per_user;
    if (Object.keys(c).length > 0) {
      out.concurrency = c;
      touched = true;
    }
  }

  if (isObject(value.defaults)) {
    const d: NonNullable<FlowPolicies['defaults']> = {};
    if (typeof value.defaults.timeout_ms === 'number') d.timeout_ms = value.defaults.timeout_ms;
    if (typeof value.defaults.continue_on_fail === 'boolean') {
      d.continue_on_fail = value.defaults.continue_on_fail;
    }
    const retry = parseRetry(value.defaults.retry);
    if (retry) d.retry = retry;
    if (Object.keys(d).length > 0) {
      out.defaults = d;
      touched = true;
    }
  }

  if (isObject(value.pii)) {
    const p: NonNullable<FlowPolicies['pii']> = {};
    if (typeof value.pii.allow === 'boolean') p.allow = value.pii.allow;
    if (typeof value.pii.tokenize_model_inputs === 'boolean') {
      p.tokenize_model_inputs = value.pii.tokenize_model_inputs;
    }
    if (isObject(value.pii.exceptions) && isObject(value.pii.exceptions.tools)) {
      const tools: Record<string, PiiToolException | string[]> = {};
      for (const [toolName, spec] of Object.entries(value.pii.exceptions.tools)) {
        if (Array.isArray(spec)) {
          const allow = spec.filter((s): s is string => typeof s === 'string');
          if (allow.length > 0) tools[toolName] = allow;
        } else if (isObject(spec) && Array.isArray(spec.allow)) {
          const allow = spec.allow.filter((s): s is string => typeof s === 'string');
          if (allow.length > 0) tools[toolName] = { allow };
        }
      }
      if (Object.keys(tools).length > 0) p.exceptions = { tools };
    }
    if (Object.keys(p).length > 0) {
      out.pii = p;
      touched = true;
    }
  }

  if (isObject(value.rate_limits)) {
    const limits: Record<string, { rpm: number }> = {};
    for (const [tool, spec] of Object.entries(value.rate_limits)) {
      if (isObject(spec) && typeof spec.rpm === 'number') {
        limits[tool] = { rpm: spec.rpm };
      }
    }
    if (Object.keys(limits).length > 0) {
      out.rate_limits = limits;
      touched = true;
    }
  }

  return touched ? out : undefined;
}

function parseTelemetry(value: Record<string, unknown>): FlowTelemetry | undefined {
  const out: FlowTelemetry = {};
  if (
    value.trace_level === 'off' ||
    value.trace_level === 'meta' ||
    value.trace_level === 'brief' ||
    value.trace_level === 'verbose'
  ) {
    out.trace_level = value.trace_level;
  }
  if (typeof value.sample_rate === 'number') out.sample_rate = value.sample_rate;
  return Object.keys(out).length > 0 ? out : undefined;
}

function parseRetry(value: unknown): RetrySpec | undefined {
  if (!isObject(value)) return undefined;
  const out: RetrySpec = {};
  if (typeof value.attempts === 'number') out.attempts = value.attempts;
  if (isObject(value.backoff)) {
    const mode = value.backoff.mode;
    if (mode === 'constant' || mode === 'linear' || mode === 'exponential') {
      const backoff: RetrySpec['backoff'] = { mode };
      if (typeof value.backoff.base_ms === 'number') backoff.base_ms = value.backoff.base_ms;
      if (typeof value.backoff.max_ms === 'number') backoff.max_ms = value.backoff.max_ms;
      if (typeof value.backoff.jitter === 'boolean') backoff.jitter = value.backoff.jitter;
      out.backoff = backoff;
    }
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function parseSteps(value: unknown): WorkflowStepDraft[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isObject).map(parseStep);
}

function parseStep(raw: Record<string, unknown>): WorkflowStepDraft {
  const id = asString(raw.id) || 'unknown';
  const type = parseStepType(raw.type);
  const step: WorkflowStepDraft = { id, type, name: id };

  if (typeof raw.description === 'string') step.description = raw.description;
  if (typeof raw.instruction === 'string') step.instruction = raw.instruction;
  if (typeof raw.tool === 'string') step.tool = raw.tool;
  if (typeof raw.if === 'string') step.if = raw.if;
  if (isObject(raw.params)) step.params = { ...raw.params };
  if (raw.expect !== undefined) step.expect = raw.expect;
  if (Array.isArray(raw.branches_enum)) {
    step.branches_enum = raw.branches_enum.filter((s): s is string => typeof s === 'string');
  }
  const creds = asStringArray(raw.uses_credentials);
  if (creds && creds.length > 0) step.uses_credentials = creds;
  const retry = parseRetry(raw.retry);
  if (retry) step.retry = retry;
  if (typeof raw.temperature === 'number') step.temperature = raw.temperature;
  if (typeof raw.max_tokens === 'number') step.max_tokens = raw.max_tokens;
  if (typeof raw.word_cap === 'number') step.word_cap = raw.word_cap;

  const extras: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (!KNOWN_STEP_KEYS.has(k)) extras[k] = v;
  }
  if (Object.keys(extras).length > 0) step.extras = extras;

  return step;
}

function parseStepType(value: unknown): StepType {
  return typeof value === 'string' && KNOWN_STEP_TYPES.has(value as StepType)
    ? (value as StepType)
    : 'ai.extract';
}

function checkForAdvancedFeatures(raw: unknown): { supported: boolean; reasons: string[] } {
  const reasons: string[] = [];
  const obj = isObject(raw) ? raw : {};
  const workflow = isObject(obj.workflow) ? obj.workflow : {};
  const steps = Array.isArray(workflow.steps) ? workflow.steps : [];
  for (const step of steps) {
    if (!isObject(step)) continue;
    const type = step.type;
    if (type === 'group.parallel' || type === 'group.map') {
      reasons.push(`step "${asString(step.id) || '?'}" uses ${type}`);
    } else if (typeof type === 'string' && !KNOWN_STEP_TYPES.has(type as StepType)) {
      reasons.push(`step "${asString(step.id) || '?'}" uses unknown type "${type}"`);
    }
  }
  return { supported: reasons.length === 0, reasons };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | undefined {
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return String(value);
  return undefined;
}

function asStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const out = value.filter((v): v is string => typeof v === 'string');
  return out.length > 0 ? out : undefined;
}

export { piiPolicyFromBackend };
