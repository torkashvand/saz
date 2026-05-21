/**
 * Strict-mode regression: pin the initial-YAML parse so a future cleanup
 * refactor can't silently re-break edit-mode load.
 *
 * The bug this guards against (found in browser testing): the initial-parse
 * useEffect used both a `useRef` "ran once" guard AND a `cancelled` cleanup
 * flag. In React strict mode dev, useEffect runs twice — the first invocation
 * starts the async parse, the cleanup fires before it completes (flipping
 * `cancelled = true`), and the parsed result is silently dropped. The fix
 * removes the cancellation flag in favor of the ref guard alone.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { StrictMode } from 'react';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FlowBuilder } from '@/components/flows/register/flow-builder';
import jsYaml from 'js-yaml';

// next/navigation isn't available in jsdom; stub useRouter.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    compileFlow: vi.fn(async () => ({
      valid: true,
      flow_name: 'demo_flow',
      flow_version: '1.0',
      flow_description: 'demo',
      form_schema: { properties: {} },
      workflow_summary: { steps_count: 1, ai_steps: 1, credentials: [] },
      warnings: [],
      errors: [],
    })),
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

describe('FlowBuilder — initial YAML parse under React.StrictMode', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('parses initialYaml into the guided draft without being dropped by cleanup', async () => {
    const initialYaml = jsYaml.dump({
      schema_version: 1,
      flow: { name: 'pinned_flow', version: '1.0', description: 'pin the fix' },
      workflow: {
        planner_mode: 'deterministic',
        steps: [
          {
            id: 'classify',
            type: 'ai.extract',
            description: 'classify',
            instruction: 'do',
            expect: { type: 'object' },
          },
        ],
      },
    });

    render(wrapped(<FlowBuilder initialYaml={initialYaml} flowId="abc" isEditMode />));

    // After the async parse settles, the flow name input must show the
    // parsed value (not the default `new_flow`). If the strict-mode race
    // returns, this assertion fails because the draft stays at emptyDraft().
    await waitFor(() => {
      expect(screen.getByDisplayValue('pinned_flow')).toBeInTheDocument();
    });
  });
});
