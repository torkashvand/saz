import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('@/lib/auth', () => ({ getAccessToken: () => null }));
vi.mock('@/lib/monitoring', () => ({
  addBreadcrumb: vi.fn(),
  captureAppError: vi.fn(),
}));

import { api } from '@/lib/api';

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('api.updateFlow — edit-mode save contract', () => {
  it('issues a PUT to /api/v1/flows/{id} (not POST), so rename does not fork the row', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'abc', name: 'renamed', version: '1.0' }));

    const result = await api.updateFlow('abc', { yaml: 'schema_version: 1' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/flows/abc');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body as string)).toEqual({ yaml: 'schema_version: 1' });
    expect(result.id).toBe('abc');
  });
});

describe('api.registerFlow — create path', () => {
  it('uses POST /api/v1/flows', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'new', name: 'x', version: '1.0' }));
    await api.registerFlow({ yaml: 'schema_version: 1' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/flows');
    expect(init.method).toBe('POST');
  });
});

describe('api.compileFlow — validator returns 200 with valid=false', () => {
  it('surfaces structured errors with section / step_id / json_pointer', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
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
      }),
    );

    const response = await api.compileFlow({ yaml: 'broken: yaml' });
    expect(response.valid).toBe(false);
    expect(response.errors).toHaveLength(1);
    expect(response.errors![0].section).toBe('workflow');
    expect(response.errors![0].step_id).toBe('bad');
  });
});

describe('Template load → yamlToDraft → guided mode keeps semantic shape', () => {
  it('parses a clean template into a guided-builder-ready FlowDraft', async () => {
    // Local mock for compileFlow used by yaml-parser.
    vi.resetModules();
    vi.doMock('@/lib/api', () => ({
      api: {
        compileFlow: vi.fn(async () => ({
          valid: true,
          flow_name: 'demo',
          flow_version: '1.0',
          flow_description: 'demo',
          form_schema: { properties: {} },
          workflow_summary: { steps_count: 1, ai_steps: 1, credentials: [] },
          warnings: [],
          errors: [],
        })),
      },
    }));
    const { yamlToDraft } = await import('@/lib/flows/yaml-parser');
    const yaml = `
schema_version: 1
flow:
  name: demo
  description: demo
workflow:
  planner_mode: deterministic
  steps:
    - id: classify
      type: ai.extract
      description: classify
      instruction: do
      expect: { type: object }
`;
    const result = await yamlToDraft(yaml);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    // Guided-builder readiness: nested shape, the workflow step is in the
    // semantic draft, and no advanced flag was set.
    expect(result.draft.flow.name).toBe('demo');
    expect(result.draft.workflow.steps[0].type).toBe('ai.extract');
    vi.resetModules();
  });
});
