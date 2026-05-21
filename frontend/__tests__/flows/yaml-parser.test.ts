import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/lib/api', () => ({
  api: {
    compileFlow: vi.fn(),
  },
}));

import jsYaml from 'js-yaml';
import { yamlToDraft } from '@/lib/flows/yaml-parser';
import { api } from '@/lib/api';
import { draftToDsl } from '@/lib/flows/yaml-generator';

const mockedCompile = vi.mocked(api.compileFlow);

const STUB_OK = {
  valid: true,
  flow_name: 'demo',
  flow_version: '1.0',
  flow_description: 'demo',
  form_schema: { properties: {}, required: [] },
  workflow_summary: { steps_count: 0, ai_steps: 0, credentials: [] },
  warnings: [],
  errors: [],
};

beforeEach(() => {
  mockedCompile.mockReset();
  mockedCompile.mockResolvedValue(STUB_OK as any);
});

function asYaml(obj: unknown): string {
  return jsYaml.dump(obj);
}

describe('yamlToDraft — nested draft shape', () => {
  it('places labels under draft.flow.labels as object map', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo', labels: { team: 'ops' } },
      workflow: { planner_mode: 'deterministic', steps: [] },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.draft.flow.labels).toEqual({ team: 'ops' });
  });

  it('reads workflow.planner_mode into draft.workflow.planner_mode', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      workflow: { planner_mode: 'agentic', steps: [] },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.draft.workflow.planner_mode).toBe('agentic');
  });
});

describe('yamlToDraft — form constraints', () => {
  it('preserves integer vs number type', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      form: {
        fields: [
          { name: 'i', type: 'integer', required: true },
          { name: 'f', type: 'number', required: false },
        ],
      },
      workflow: { planner_mode: 'deterministic', steps: [] },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.draft.form?.fields[0].type).toBe('integer');
    expect(result.draft.form?.fields[1].type).toBe('number');
  });

  it('preserves enum, pattern, min/max length, default, title, format', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      form: {
        fields: [
          {
            name: 'severity',
            type: 'string',
            required: true,
            enum: ['low', 'medium', 'high'],
            pattern: '^[a-z]+$',
            minLength: 2,
            maxLength: 16,
            default: 'low',
            title: 'Severity',
            format: 'email',
          },
        ],
      },
      workflow: { planner_mode: 'deterministic', steps: [] },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.draft.form?.fields[0]).toMatchObject({
      type: 'string',
      enum: ['low', 'medium', 'high'],
      pattern: '^[a-z]+$',
      minLength: 2,
      maxLength: 16,
      default: 'low',
      title: 'Severity',
      format: 'email',
    });
  });

  it('accepts regex/min/max aliases', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      form: {
        fields: [
          { name: 'code', type: 'string', regex: '^x' },
          { name: 'n', type: 'number', min: 0, max: 5 },
        ],
      },
      workflow: { planner_mode: 'deterministic', steps: [] },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.draft.form?.fields[0].pattern).toBe('^x');
    expect(result.draft.form?.fields[1].minimum).toBe(0);
    expect(result.draft.form?.fields[1].maximum).toBe(5);
  });
});

describe('yamlToDraft — policies and telemetry', () => {
  it('parses the full policies tree', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      workflow: { planner_mode: 'deterministic', steps: [] },
      policies: {
        budget_usd: 0.5,
        concurrency: { per_flow: 2, per_user: 1 },
        defaults: {
          timeout_ms: 60000,
          retry: { attempts: 3, backoff: { mode: 'exponential', base_ms: 250 } },
        },
        pii: {
          allow: false,
          tokenize_model_inputs: true,
          exceptions: {
            tools: {
              'artifact.store': { allow: ['content.requester'] },
              http_request: ['url'],
            },
          },
        },
        rate_limits: { http_request: { rpm: 100 } },
      },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const p = result.draft.policies!;
    expect(p.budget_usd).toBe(0.5);
    expect(p.concurrency).toEqual({ per_flow: 2, per_user: 1 });
    expect(p.defaults?.retry).toEqual({
      attempts: 3,
      backoff: { mode: 'exponential', base_ms: 250 },
    });
    expect(p.pii?.exceptions?.tools).toEqual({
      'artifact.store': { allow: ['content.requester'] },
      http_request: ['url'],
    });
    expect(p.rate_limits).toEqual({ http_request: { rpm: 100 } });
  });

  it('parses telemetry block', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      telemetry: { trace_level: 'brief', sample_rate: 0.5 },
      workflow: { planner_mode: 'deterministic', steps: [] },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.draft.telemetry).toEqual({ trace_level: 'brief', sample_rate: 0.5 });
  });
});

describe('yamlToDraft — workflow steps', () => {
  it('preserves retry, uses_credentials, if, branches_enum, params, expect, word_cap', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      credentials: { uses: ['api_token'] },
      workflow: {
        planner_mode: 'deterministic',
        steps: [
          { id: 'gate', type: 'condition', description: 'd', if: "{{ $form.env == 'prod' }}" },
          {
            id: 'classify',
            type: 'ai.extract',
            description: 'd',
            instruction: 'do it',
            params: { data: { x: 1 } },
            expect: { type: 'object' },
            uses_credentials: ['api_token'],
            retry: { attempts: 2, backoff: { mode: 'constant', base_ms: 100 } },
          },
          {
            id: 'r',
            type: 'ai.route',
            description: 'd',
            instruction: 'd',
            expect: { type: 'object' },
            branches_enum: ['a', 'b'],
          },
          {
            id: 's',
            type: 'ai.summarize',
            description: 'd',
            instruction: 'd',
            expect: { type: 'object' },
            word_cap: 60,
          },
        ],
      },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const steps = result.draft.workflow.steps;
    expect(steps[0]).toMatchObject({ type: 'condition', if: "{{ $form.env == 'prod' }}" });
    expect(steps[1]).toMatchObject({
      uses_credentials: ['api_token'],
      retry: { attempts: 2, backoff: { mode: 'constant', base_ms: 100 } },
    });
    expect(steps[2].branches_enum).toEqual(['a', 'b']);
    expect(steps[3].word_cap).toBe(60);
  });

  it('preserves unknown step-specific fields under extras', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      workflow: {
        planner_mode: 'deterministic',
        steps: [
          {
            id: 't',
            type: 'ai.translate',
            description: 'd',
            instruction: 'd',
            expect: { type: 'object' },
            target_locale: 'fr-FR',
          },
        ],
      },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.draft.workflow.steps[0].extras).toEqual({ target_locale: 'fr-FR' });
  });

  it('does NOT disable Guided Builder for condition steps', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      workflow: {
        planner_mode: 'deterministic',
        steps: [{ id: 'gate', type: 'condition', description: 'gate', if: 'true' }],
      },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.draft.workflow.steps[0].type).toBe('condition');
  });

  it('flags unknown step types as advanced', async () => {
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'demo' },
      workflow: {
        planner_mode: 'deterministic',
        steps: [{ id: 'x', type: 'group.parallel' }],
      },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.advanced).toBe(true);
  });
});

describe('yamlToDraft — structured compile errors pass through', () => {
  it('surfaces backend valid=false errors with step_id and section', async () => {
    mockedCompile.mockResolvedValue({
      valid: false,
      flow_name: '',
      form_schema: { properties: {} },
      workflow_summary: { steps_count: 0, ai_steps: 0, credentials: [] },
      warnings: [],
      errors: [
        {
          code: 'step.empty_field',
          message: "step 'bad' requires non-empty 'description' field",
          section: 'workflow',
          step_id: 'bad',
          json_pointer: '/workflow/steps',
        },
      ],
    } as any);
    const yaml = asYaml({
      schema_version: 1,
      flow: { name: 'd' },
      workflow: { planner_mode: 'deterministic', steps: [] },
    });
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors[0].step_id).toBe('bad');
    expect(result.errors[0].section).toBe('workflow');
    expect(result.errors[0].code).toBe('step.empty_field');
  });
});

describe('round-trip — YAML → draft → YAML → draft', () => {
  it('preserves the nested draft across one round trip', async () => {
    const sourceDsl = {
      schema_version: 1,
      flow: { name: 'demo', version: '1.0', description: 'd', labels: { team: 'ops' } },
      credentials: { uses: ['t'] },
      triggers: { manual: true, webhook: { path: '/x', signature_header: 'X-Sig' } },
      policies: {
        budget_usd: 0.2,
        defaults: { timeout_ms: 1000, retry: { attempts: 1, backoff: { mode: 'constant' } } },
        pii: { allow: false, tokenize_model_inputs: true },
      },
      telemetry: { trace_level: 'meta' },
      form: {
        fields: [
          { name: 'env', type: 'string', required: true, enum: ['dev', 'prod'] },
          { name: 'n', type: 'integer', required: false, minimum: 0, maximum: 10 },
        ],
      },
      workflow: {
        planner_mode: 'deterministic',
        steps: [
          {
            id: 'classify',
            type: 'ai.extract',
            description: 'd',
            instruction: 'do',
            params: { data: { x: 1 } },
            expect: { type: 'object', properties: {} },
            uses_credentials: ['t'],
            retry: { attempts: 2, backoff: { mode: 'constant', base_ms: 100 } },
          },
        ],
      },
    };
    const yaml1 = asYaml(sourceDsl);
    const result1 = await yamlToDraft(yaml1);
    expect(result1.ok).toBe(true);
    if (!result1.ok) return;
    const dsl2 = draftToDsl(result1.draft);
    const yaml2 = asYaml(dsl2);
    const result2 = await yamlToDraft(yaml2);
    expect(result2.ok).toBe(true);
    if (!result2.ok) return;
    expect(result2.draft).toEqual(result1.draft);
  });
});
