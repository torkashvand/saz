import { describe, it, expect } from 'vitest';
import jsYaml from 'js-yaml';
import { draftToDsl, draftToUnifiedYaml } from '@/lib/flows/yaml-generator';
import type { FlowDraft } from '@/lib/flows/types';
import { STEP_TYPES, emptyDraft } from '@/lib/flows/types';

function baseDraft(overrides: Partial<FlowDraft> = {}): FlowDraft {
  return {
    ...emptyDraft(),
    flow: { name: 'my_flow', version: '1.0', description: 'demo' },
    workflow: { planner_mode: 'deterministic', steps: [] },
    ...overrides,
  };
}

describe('draftToDsl — flow-level fields', () => {
  it('places planner_mode under workflow, not under flow', () => {
    const dsl = draftToDsl(baseDraft({ workflow: { planner_mode: 'agentic', steps: [] } }));
    expect((dsl.workflow as any).planner_mode).toBe('agentic');
    expect((dsl.flow as any).planner_mode).toBeUndefined();
  });

  it('emits flow.labels as an object map', () => {
    const dsl = draftToDsl(
      baseDraft({
        flow: { name: 'x', description: '', labels: { team: 'ops', tier: 'prod' } },
      }),
    );
    expect((dsl.flow as any).labels).toEqual({ team: 'ops', tier: 'prod' });
  });

  it('omits flow.labels when empty', () => {
    const dsl = draftToDsl(baseDraft({ flow: { name: 'x', description: '', labels: {} } }));
    expect((dsl.flow as any).labels).toBeUndefined();
  });
});

describe('draftToDsl — form fields', () => {
  it('preserves constraints and integer type', () => {
    const dsl = draftToDsl(
      baseDraft({
        form: {
          fields: [
            {
              name: 'severity',
              type: 'string',
              required: true,
              enum: ['low', 'medium', 'high'],
              pattern: '^[a-z]+$',
              minLength: 3,
              maxLength: 16,
              default: 'low',
              title: 'Severity',
              description: 'Pick one',
              format: 'email',
            },
            { name: 'count', type: 'integer', required: false, minimum: 0, maximum: 100 },
          ],
        },
      }),
    );
    const fields = (dsl.form as any).fields;
    expect(fields[0]).toMatchObject({
      name: 'severity',
      type: 'string',
      required: true,
      enum: ['low', 'medium', 'high'],
      pattern: '^[a-z]+$',
      minLength: 3,
      maxLength: 16,
      default: 'low',
      title: 'Severity',
      description: 'Pick one',
      format: 'email',
    });
    expect(fields[1]).toMatchObject({ name: 'count', type: 'integer', minimum: 0, maximum: 100 });
    expect(fields[1].required).toBeUndefined();
  });
});

describe('draftToDsl — triggers', () => {
  it('emits webhook.signature_header when set', () => {
    const dsl = draftToDsl(
      baseDraft({
        triggers: {
          manual: false,
          webhook: {
            enabled: true,
            path: '/hook',
            event: 'evt',
            signature_header: 'X-Signature',
          },
        },
      }),
    );
    expect((dsl.triggers as any).webhook).toEqual({
      path: '/hook',
      event: 'evt',
      signature_header: 'X-Signature',
    });
  });

  it('drops disabled webhook/schedule blocks', () => {
    const dsl = draftToDsl(
      baseDraft({
        triggers: {
          manual: true,
          webhook: { enabled: false, path: '/x' },
          schedule: { enabled: false, cron: '* * * * *' },
        },
      }),
    );
    expect((dsl.triggers as any).webhook).toBeUndefined();
    expect((dsl.triggers as any).schedule).toBeUndefined();
  });
});

describe('draftToDsl — policies', () => {
  it('emits the full policies tree', () => {
    const dsl = draftToDsl(
      baseDraft({
        policies: {
          budget_usd: 0.5,
          concurrency: { per_flow: 2, per_user: 1 },
          defaults: {
            timeout_ms: 30000,
            continue_on_fail: true,
            retry: { attempts: 3, backoff: { mode: 'exponential', base_ms: 500, jitter: true } },
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
      }),
    );
    const p = dsl.policies as any;
    expect(p.budget_usd).toBe(0.5);
    expect(p.concurrency).toEqual({ per_flow: 2, per_user: 1 });
    expect(p.defaults.retry).toEqual({
      attempts: 3,
      backoff: { mode: 'exponential', base_ms: 500, jitter: true },
    });
    expect(p.pii.exceptions.tools).toEqual({
      'artifact.store': { allow: ['content.requester'] },
      http_request: ['url'],
    });
    expect(p.rate_limits).toEqual({ http_request: { rpm: 100 } });
  });
});

describe('draftToDsl — telemetry', () => {
  it('emits telemetry block', () => {
    const dsl = draftToDsl(baseDraft({ telemetry: { trace_level: 'brief', sample_rate: 0.5 } }));
    expect(dsl.telemetry).toEqual({ trace_level: 'brief', sample_rate: 0.5 });
  });
});

describe('draftToDsl — workflow steps', () => {
  it('emits retry, uses_credentials, if, branches_enum, params, expect, word_cap', () => {
    const dsl = draftToDsl(
      baseDraft({
        credentials: { uses: ['api_token'] },
        workflow: {
          planner_mode: 'deterministic',
          steps: [
            {
              id: 'gate',
              type: 'condition',
              description: 'only run on prod',
              if: "{{ $form.env == 'prod' }}",
            },
            {
              id: 'classify',
              type: 'ai.extract',
              description: 'classify',
              instruction: 'Classify the alert',
              params: { data: { x: 1 } },
              expect: { type: 'object', properties: { ok: { type: 'boolean' } } },
              uses_credentials: ['api_token'],
              retry: { attempts: 2, backoff: { mode: 'constant', base_ms: 100 } },
            },
            {
              id: 'route',
              type: 'ai.route',
              instruction: 'pick a branch',
              branches_enum: ['approve', 'reject'],
              expect: { type: 'object' },
            },
            {
              id: 'summary',
              type: 'ai.summarize',
              instruction: 'short',
              word_cap: 60,
              expect: { type: 'object' },
            },
          ],
        },
      }),
    );

    const steps = (dsl.workflow as any).steps;
    expect(steps[0]).toMatchObject({
      id: 'gate',
      type: 'condition',
      if: "{{ $form.env == 'prod' }}",
    });
    expect(steps[1]).toMatchObject({
      uses_credentials: ['api_token'],
      retry: { attempts: 2, backoff: { mode: 'constant', base_ms: 100 } },
    });
    expect(steps[2]).toMatchObject({ branches_enum: ['approve', 'reject'] });
    expect(steps[3]).toMatchObject({ word_cap: 60 });
  });

  it('preserves step.extras verbatim and drops UI-only name', () => {
    const dsl = draftToDsl(
      baseDraft({
        workflow: {
          planner_mode: 'deterministic',
          steps: [
            {
              id: 'translate',
              name: 'Friendly Translate',
              type: 'ai.translate',
              instruction: 't',
              expect: { type: 'object' },
              extras: { target_locale: 'fr-FR' },
            },
          ],
        },
      }),
    );
    const step = (dsl.workflow as any).steps[0];
    expect(step.target_locale).toBe('fr-FR');
    expect(step.name).toBeUndefined();
  });
});

describe('draftToDsl — STEP_TYPES catalog', () => {
  it('includes every backend-supported step type', () => {
    const values = STEP_TYPES.map((t) => t.value);
    const expected = [
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
    ];
    for (const t of expected) {
      expect(values).toContain(t);
    }
  });

  it('no longer includes the frontend-only `branching` pseudo-type', () => {
    const values = STEP_TYPES.map((t) => t.value as string);
    expect(values).not.toContain('branching');
  });
});

describe('draftToUnifiedYaml — string output', () => {
  it('produces YAML that re-parses to the same DSL object', () => {
    const draft = baseDraft({
      flow: { name: 'demo', description: '', version: '1.0', labels: { team: 'ops' } },
      policies: {
        budget_usd: 0.2,
        defaults: { timeout_ms: 10000, continue_on_fail: false },
        pii: { allow: false, tokenize_model_inputs: true },
      },
      workflow: {
        planner_mode: 'deterministic',
        steps: [
          {
            id: 's1',
            type: 'ai.extract',
            description: 'extract',
            instruction: 'do it',
            params: { data: {} },
            expect: { type: 'object', properties: { ok: { type: 'boolean' } } },
          },
        ],
      },
    });
    const yamlString = draftToUnifiedYaml(draft);
    const reparsed = jsYaml.load(yamlString);
    expect(reparsed).toEqual(draftToDsl(draft));
  });

  it('writes workflow.planner_mode (not under flow)', () => {
    const yamlString = draftToUnifiedYaml(baseDraft());
    const reparsed = jsYaml.load(yamlString) as Record<string, any>;
    expect(reparsed.workflow.planner_mode).toBe('deterministic');
    expect(reparsed.flow.planner_mode).toBeUndefined();
  });
});
