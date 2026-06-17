import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import NewRunPage from '@/app/runs/new/page';

const push = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams('flow=flow-1'),
}));

vi.mock('@/lib/use-error-toast', () => ({
  useErrorToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));

const getFlow = vi.fn();
const listFlows = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    listFlows: (...args: any[]) => listFlows(...args),
    getFlow: (...args: any[]) => getFlow(...args),
  },
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NewRunPage />
    </QueryClientProvider>,
  );
}

describe('NewRunPage form rendering', () => {
  beforeEach(() => {
    push.mockClear();
    listFlows.mockResolvedValue({ items: [], total: 0 });
    getFlow.mockResolvedValue({
      id: 'flow-1',
      name: 'RFQ',
      definition: {
        form: {
          fields: [
            { name: 'reference', type: 'string', required: true },
            { name: 'scope', type: 'text', widget: 'textarea', required: true },
            { name: 'consultation_required', type: 'boolean', required: true },
          ],
        },
      },
    });
  });

  it('renders a textarea for a widget: textarea field and a plain input otherwise', async () => {
    renderPage();

    const scope = await screen.findByLabelText(/scope/);
    expect(scope.tagName).toBe('TEXTAREA');

    const reference = screen.getByLabelText(/reference/);
    expect(reference.tagName).toBe('INPUT');
  });

  it('captures textarea input into the form value', async () => {
    renderPage();

    const scope = (await screen.findByLabelText(/scope/)) as HTMLTextAreaElement;
    fireEvent.change(scope, { target: { value: 'A multi-line\nscope description' } });

    await waitFor(() => {
      expect(scope.value).toBe('A multi-line\nscope description');
    });
  });

  it('renders a boolean field as a checkbox and captures a real boolean', async () => {
    renderPage();

    const checkbox = (await screen.findByLabelText(/consultation_required/)) as HTMLInputElement;
    expect(checkbox.tagName).toBe('INPUT');
    expect(checkbox.type).toBe('checkbox');
    expect(checkbox.checked).toBe(false);

    fireEvent.click(checkbox);
    await waitFor(() => {
      expect(checkbox.checked).toBe(true);
    });
  });
});
