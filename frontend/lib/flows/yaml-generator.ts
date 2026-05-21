import jsYaml from 'js-yaml';
import type {
  FlowDraft,
  FlowFormField,
  FlowPolicies,
  FlowTelemetry,
  FlowTriggers,
  WorkflowStepDraft,
} from './types';

/**
 * Build the canonical DSL object (matches backend/saz/compiler/dsl.py) from
 * a nested FlowDraft. The draft already mirrors the DSL one-to-one, so this
 * mostly just normalizes / removes UI-only fields.
 */
export function draftToDsl(draft: FlowDraft): Record<string, unknown> {
  const dsl: Record<string, unknown> = {
    schema_version: draft.schema_version || 1,
  };

  const flow: Record<string, unknown> = { name: draft.flow.name };
  if (draft.flow.version) flow.version = draft.flow.version;
  if (draft.flow.description) flow.description = draft.flow.description;
  if (draft.flow.owners && draft.flow.owners.length > 0) flow.owners = [...draft.flow.owners];
  if (draft.flow.labels && Object.keys(draft.flow.labels).length > 0) {
    flow.labels = { ...draft.flow.labels };
  }
  dsl.flow = flow;

  if (draft.credentials && draft.credentials.uses.length > 0) {
    dsl.credentials = { uses: [...draft.credentials.uses] };
  }

  const triggers = serializeTriggers(draft.triggers);
  if (triggers) dsl.triggers = triggers;

  const policies = serializePolicies(draft.policies);
  if (policies) dsl.policies = policies;

  const telemetry = serializeTelemetry(draft.telemetry);
  if (telemetry) dsl.telemetry = telemetry;

  if (draft.form && draft.form.fields.length > 0) {
    dsl.form = { fields: draft.form.fields.map(serializeFormField) };
  }

  dsl.workflow = {
    planner_mode: draft.workflow.planner_mode || 'deterministic',
    steps: draft.workflow.steps.map(serializeStep),
  };

  return dsl;
}

export function draftToUnifiedYaml(draft: FlowDraft): string {
  const dsl = draftToDsl(draft);
  return jsYaml.dump(dsl, {
    lineWidth: 100,
    noRefs: true,
    quotingType: '"',
    sortKeys: false,
  });
}

function serializeFormField(field: FlowFormField): Record<string, unknown> {
  const out: Record<string, unknown> = { name: field.name, type: field.type };
  if (field.required) out.required = true;
  if (field.description) out.description = field.description;
  if (field.title) out.title = field.title;
  if (field.format) out.format = field.format;
  if (field.default !== undefined) out.default = field.default;
  if (field.enum && field.enum.length > 0) out.enum = [...field.enum];
  if (field.pattern) out.pattern = field.pattern;
  if (field.minLength !== undefined) out.minLength = field.minLength;
  if (field.maxLength !== undefined) out.maxLength = field.maxLength;
  if (field.minimum !== undefined) out.minimum = field.minimum;
  if (field.maximum !== undefined) out.maximum = field.maximum;
  return out;
}

function serializeTriggers(triggers: FlowTriggers | undefined): Record<string, unknown> | null {
  if (!triggers) return null;
  const out: Record<string, unknown> = {};
  let touched = false;
  if (triggers.manual !== undefined) {
    out.manual = triggers.manual;
    touched = true;
  }
  if (triggers.webhook?.enabled) {
    const w: Record<string, unknown> = {};
    if (triggers.webhook.event) w.event = triggers.webhook.event;
    if (triggers.webhook.path) w.path = triggers.webhook.path;
    if (triggers.webhook.signature_header) w.signature_header = triggers.webhook.signature_header;
    out.webhook = w;
    touched = true;
  }
  if (triggers.schedule?.enabled) {
    const s: Record<string, unknown> = {};
    if (triggers.schedule.cron) s.cron = triggers.schedule.cron;
    if (triggers.schedule.timezone) s.timezone = triggers.schedule.timezone;
    out.schedule = s;
    touched = true;
  }
  return touched ? out : null;
}

function serializePolicies(policies: FlowPolicies | undefined): Record<string, unknown> | null {
  if (!policies) return null;
  const out: Record<string, unknown> = {};
  let touched = false;

  if (policies.budget_usd !== undefined) {
    out.budget_usd = policies.budget_usd;
    touched = true;
  }

  if (policies.concurrency) {
    const c: Record<string, unknown> = {};
    if (policies.concurrency.per_flow !== undefined) c.per_flow = policies.concurrency.per_flow;
    if (policies.concurrency.per_user !== undefined) c.per_user = policies.concurrency.per_user;
    if (Object.keys(c).length > 0) {
      out.concurrency = c;
      touched = true;
    }
  }

  if (policies.defaults) {
    const d: Record<string, unknown> = {};
    if (policies.defaults.timeout_ms !== undefined) d.timeout_ms = policies.defaults.timeout_ms;
    if (policies.defaults.continue_on_fail !== undefined) {
      d.continue_on_fail = policies.defaults.continue_on_fail;
    }
    const retry = serializeRetry(policies.defaults.retry);
    if (retry) d.retry = retry;
    if (Object.keys(d).length > 0) {
      out.defaults = d;
      touched = true;
    }
  }

  if (policies.pii) {
    const p: Record<string, unknown> = {};
    if (policies.pii.allow !== undefined) p.allow = policies.pii.allow;
    if (policies.pii.tokenize_model_inputs !== undefined) {
      p.tokenize_model_inputs = policies.pii.tokenize_model_inputs;
    }
    if (policies.pii.exceptions?.tools) {
      const tools: Record<string, unknown> = {};
      for (const [name, spec] of Object.entries(policies.pii.exceptions.tools)) {
        if (Array.isArray(spec)) {
          tools[name] = [...spec];
        } else if (spec && Array.isArray(spec.allow)) {
          tools[name] = { allow: [...spec.allow] };
        }
      }
      if (Object.keys(tools).length > 0) {
        p.exceptions = { tools };
      }
    }
    if (Object.keys(p).length > 0) {
      out.pii = p;
      touched = true;
    }
  }

  if (policies.rate_limits) {
    const limits: Record<string, unknown> = {};
    for (const [tool, spec] of Object.entries(policies.rate_limits)) {
      if (spec && typeof spec.rpm === 'number') {
        limits[tool] = { rpm: spec.rpm };
      }
    }
    if (Object.keys(limits).length > 0) {
      out.rate_limits = limits;
      touched = true;
    }
  }

  return touched ? out : null;
}

function serializeTelemetry(t: FlowTelemetry | undefined): Record<string, unknown> | null {
  if (!t) return null;
  const out: Record<string, unknown> = {};
  if (t.trace_level) out.trace_level = t.trace_level;
  if (t.sample_rate !== undefined) out.sample_rate = t.sample_rate;
  return Object.keys(out).length > 0 ? out : null;
}

function serializeRetry(retry: WorkflowStepDraft['retry']): Record<string, unknown> | null {
  if (!retry) return null;
  const out: Record<string, unknown> = {};
  if (retry.attempts !== undefined) out.attempts = retry.attempts;
  if (retry.backoff) {
    const b: Record<string, unknown> = { mode: retry.backoff.mode };
    if (retry.backoff.base_ms !== undefined) b.base_ms = retry.backoff.base_ms;
    if (retry.backoff.max_ms !== undefined) b.max_ms = retry.backoff.max_ms;
    if (retry.backoff.jitter !== undefined) b.jitter = retry.backoff.jitter;
    out.backoff = b;
  }
  return Object.keys(out).length > 0 ? out : null;
}

function serializeStep(step: WorkflowStepDraft): Record<string, unknown> {
  const out: Record<string, unknown> = { id: step.id, type: step.type };
  if (step.extras) {
    for (const [k, v] of Object.entries(step.extras)) {
      out[k] = v;
    }
  }
  if (step.description) out.description = step.description;
  if (step.instruction !== undefined) out.instruction = step.instruction;
  if (step.tool) out.tool = step.tool;
  if (step.if !== undefined) out.if = step.if;
  if (step.params !== undefined) out.params = step.params;
  if (step.expect !== undefined) out.expect = step.expect;
  if (step.branches_enum && step.branches_enum.length > 0) {
    out.branches_enum = [...step.branches_enum];
  }
  if (step.uses_credentials && step.uses_credentials.length > 0) {
    out.uses_credentials = [...step.uses_credentials];
  }
  const retry = serializeRetry(step.retry);
  if (retry) out.retry = retry;
  if (step.temperature !== undefined) out.temperature = step.temperature;
  if (step.max_tokens !== undefined) out.max_tokens = step.max_tokens;
  if (step.word_cap !== undefined) out.word_cap = step.word_cap;
  return out;
}
