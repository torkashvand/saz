/**
 * Regression: a freshly opened /flows/new page serialized emptyDraft() into
 * the YAML buffer on mount and immediately flagged "Unsaved changes" (plus a
 * beforeunload prompt) before the user touched anything. A pristine builder
 * must be clean until a real edit occurs.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FlowBuilder } from '@/components/flows/register/flow-builder';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    compileFlow: vi.fn(async () => ({
      valid: true,
      flow_name: 'new_flow',
      flow_version: '1.0',
      flow_description: '',
      form_schema: { properties: {} },
      workflow_summary: { steps_count: 0, ai_steps: 0, credentials: [] },
      warnings: [],
      errors: [],
    })),
    lintFlow: vi.fn(async () => ({ findings: [], compile_error: false })),
    registerFlow: vi.fn(),
    updateFlow: vi.fn(),
    getTemplate: vi.fn(),
  },
}));

vi.mock('@/components/ui/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

afterEach(() => cleanup());

function wrapped(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

describe('FlowBuilder — pristine new flow', () => {
  beforeEach(() => vi.clearAllMocks());

  it('does not show "Unsaved changes" before any edit', async () => {
    render(wrapped(<FlowBuilder />));
    // Let the mount-time regenerate effect run.
    await waitFor(() => {
      expect(screen.getByDisplayValue('new_flow')).toBeInTheDocument();
    });
    expect(screen.queryByText(/unsaved changes/i)).toBeNull();
  });
});
