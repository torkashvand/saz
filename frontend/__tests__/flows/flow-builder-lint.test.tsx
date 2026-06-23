/**
 * Live consistency-lint feedback in the flow builder: findings surface in the
 * UI and blocking (error) findings disable Save, while warnings do not.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { StrictMode } from 'react';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FlowBuilder } from '@/components/flows/register/flow-builder';
import jsYaml from 'js-yaml';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const lintFlow = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    compileFlow: vi.fn(async () => ({
      valid: true,
      flow_name: 'demo_flow',
      form_schema: { properties: {} },
      workflow_summary: { steps_count: 1, ai_steps: 1, credentials: [] },
      warnings: [],
      errors: [],
    })),
    lintFlow: (...args: unknown[]) => lintFlow(...args),
    registerFlow: vi.fn(),
    updateFlow: vi.fn(),
    getDslMetadata: vi.fn(async () => ({ tools: [] })),
    getTemplate: vi.fn(),
  },
}));

vi.mock('@/components/ui/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

afterEach(() => cleanup());

function wrapped(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <StrictMode>
      <QueryClientProvider client={client}>{node}</QueryClientProvider>
    </StrictMode>
  );
}

const INITIAL_YAML = jsYaml.dump({
  schema_version: 1,
  flow: { name: 'lint_ui_flow', version: '1.0', description: 'lint ui test' },
  workflow: {
    planner_mode: 'deterministic',
    steps: [
      {
        id: 'classify',
        type: 'ai.extract',
        description: 'classify',
        instruction: 'do the thing',
        expect: { type: 'object', properties: { out: { type: 'string' } }, required: ['out'] },
      },
    ],
  },
});

function finding(severity: 'error' | 'warning') {
  return {
    code: severity === 'error' ? 'PROSE_SCHEMA_COUNT_MISMATCH' : 'LLM_SEMANTIC_AMBIGUITY',
    severity,
    step_id: 'classify',
    field: 'instruction',
    message:
      severity === 'error' ? 'pre_checks count mismatch here' : 'instruction is ambiguous here',
    suggested_fix: null,
    source: severity === 'error' ? 'deterministic' : 'llm',
    confidence: 1,
    suppressed: false,
    suppress_reason: null,
  };
}

describe('FlowBuilder — live consistency lint', () => {
  beforeEach(() => vi.clearAllMocks());

  it('calls lintFlow with the current YAML', async () => {
    lintFlow.mockResolvedValue({ valid: true, findings: [], llm_ran: false, compile_error: null });
    render(wrapped(<FlowBuilder initialYaml={INITIAL_YAML} />));
    await waitFor(() => expect(lintFlow).toHaveBeenCalled(), { timeout: 3000 });
  });

  it('surfaces a blocking finding and disables Save', async () => {
    lintFlow.mockResolvedValue({
      valid: false,
      findings: [finding('error')],
      llm_ran: false,
      compile_error: null,
    });
    render(wrapped(<FlowBuilder initialYaml={INITIAL_YAML} />));

    // Wait for the async lint result to surface (the real signal), then assert
    // it blocks Save.
    await waitFor(
      () => expect(document.body.textContent).toContain('pre_checks count mismatch here'),
      { timeout: 5000 },
    );
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
  });

  it('does not block Save on warning-only findings', async () => {
    lintFlow.mockResolvedValue({
      valid: true,
      findings: [finding('warning')],
      llm_ran: true,
      compile_error: null,
    });
    render(wrapped(<FlowBuilder initialYaml={INITIAL_YAML} />));

    await waitFor(() => expect(lintFlow).toHaveBeenCalled(), { timeout: 3000 });
    // Once validation settles, a warning-only lint result must not block Save.
    await waitFor(() => expect(screen.getByRole('button', { name: /save/i })).not.toBeDisabled(), {
      timeout: 5000,
    });
  });
});
