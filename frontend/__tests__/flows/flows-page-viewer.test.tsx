/**
 * Viewer-tier UX: the flows catalog hides the "Register Flow" entry point
 * for read-only viewers (the backend would 403 the register call anyway).
 * Operators still see it.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

afterEach(cleanup);

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const listFlows = vi.fn().mockResolvedValue({ items: [], total: 0 });
vi.mock('@/lib/api', () => ({ api: { listFlows: (...a: unknown[]) => listFlows(...a) } }));

const useAuthMock = vi.fn();
vi.mock('@/lib/auth', () => ({ useAuth: () => useAuthMock() }));

import FlowsPage from '@/app/flows/page';

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FlowsPage />
    </QueryClientProvider>,
  );
}

describe('FlowsPage register gating', () => {
  it('hides Register Flow for a viewer', async () => {
    useAuthMock.mockReturnValue({ canWrite: false });
    renderPage();
    await waitFor(() => expect(screen.getByText('Workflow Catalog')).toBeInTheDocument());
    expect(screen.queryByText('+ Register Flow')).toBeNull();
  });

  it('shows Register Flow for an operator', async () => {
    useAuthMock.mockReturnValue({ canWrite: true });
    renderPage();
    await waitFor(() => expect(screen.getByText('+ Register Flow')).toBeInTheDocument());
  });
});
