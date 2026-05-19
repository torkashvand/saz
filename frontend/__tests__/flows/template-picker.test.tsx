/**
 * Component tests for the TemplatePicker modal.
 *
 * The picker is the primary discovery surface for the wedge demos.
 * These tests pin the demo-critical UI:
 *  - Loading + error states are visible (no silent blank state).
 *  - Wedge demos surface first.
 *  - Recommended-only and search filters narrow the list.
 *  - Selecting a row invokes onSelect with the template id.
 *  - ESC and the X button close the modal.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TemplatePicker } from '@/components/flows/register/template-picker';
import type { TemplateSummary } from '@/lib/types';

vi.mock('@/lib/hooks', () => ({
  useTemplates: vi.fn(),
}));

import { useTemplates } from '@/lib/hooks';
const mockUseTemplates = vi.mocked(useTemplates);

const MOCK_TEMPLATES: TemplateSummary[] = [
  {
    id: 'incident_triage',
    title: 'Incident Triage Assistant',
    description: 'AI-assisted incident classification with audit artifact.',
    tags: ['wedge-demo', 'incidents', 'ops'],
    complexity: 'medium',
    recommended: true,
    flow_name: 'incident_triage',
    steps_count: 3,
    ai_steps: 2,
    credentials: [],
  },
  {
    id: 'change_approval_ansible',
    title: 'Change Approval with Ansible',
    description: 'Approve a change before Ansible apply runs.',
    tags: ['wedge-demo', 'ansible', 'approval'],
    complexity: 'advanced',
    recommended: true,
    flow_name: 'change_approval_ansible',
    steps_count: 6,
    ai_steps: 1,
    credentials: [],
  },
  {
    id: 'http_summary_report',
    title: 'HTTP API Summary Report',
    description: 'Fetch an API and summarize with AI.',
    tags: ['reporting'],
    complexity: 'medium',
    recommended: false,
    flow_name: 'http_summary_report',
    steps_count: 7,
    ai_steps: 2,
    credentials: ['api_key'],
  },
];

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe('TemplatePicker', () => {
  it('renders nothing when closed', () => {
    mockUseTemplates.mockReturnValue({
      data: MOCK_TEMPLATES,
      isLoading: false,
      error: null,
    } as any);

    const { container } = render(
      <TemplatePicker open={false} onClose={() => {}} onSelect={() => {}} />,
      { wrapper },
    );
    expect(container.querySelector('[data-testid="template-picker"]')).toBeNull();
  });

  it('shows a loading state', () => {
    mockUseTemplates.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as any);

    render(<TemplatePicker open={true} onClose={() => {}} onSelect={() => {}} />, { wrapper });
    expect(screen.getByText(/loading templates/i)).toBeInTheDocument();
  });

  it('shows an actionable error state on fetch failure', () => {
    mockUseTemplates.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('boom'),
    } as any);

    render(<TemplatePicker open={true} onClose={() => {}} onSelect={() => {}} />, { wrapper });
    expect(screen.getByTestId('template-picker-error')).toBeInTheDocument();
  });

  it('lists the wedge demos with their tags + step counts', () => {
    mockUseTemplates.mockReturnValue({
      data: MOCK_TEMPLATES.filter((t) => t.recommended),
      isLoading: false,
      error: null,
    } as any);

    render(<TemplatePicker open={true} onClose={() => {}} onSelect={() => {}} />, { wrapper });
    expect(screen.getByTestId('template-picker-row-incident_triage')).toBeInTheDocument();
    expect(screen.getByTestId('template-picker-row-change_approval_ansible')).toBeInTheDocument();
    // Wedge badge is rendered for wedge-demo templates
    const wedgeBadges = screen.getAllByText(/wedge demo/i);
    expect(wedgeBadges.length).toBeGreaterThan(0);
  });

  it('renders wedge-demo templates before non-wedge ones', () => {
    mockUseTemplates.mockReturnValue({
      data: MOCK_TEMPLATES,
      isLoading: false,
      error: null,
    } as any);

    render(<TemplatePicker open={true} onClose={() => {}} onSelect={() => {}} />, { wrapper });
    const rows = screen
      .getByTestId('template-picker-list')
      .querySelectorAll('[data-testid^="template-picker-row-"]');
    // First two rows should be the wedge demos, sorted alphabetically.
    expect(rows[0].getAttribute('data-testid')).toBe('template-picker-row-change_approval_ansible');
    expect(rows[1].getAttribute('data-testid')).toBe('template-picker-row-incident_triage');
  });

  it('filters by search query against title, description, and tags', () => {
    mockUseTemplates.mockReturnValue({
      data: MOCK_TEMPLATES,
      isLoading: false,
      error: null,
    } as any);

    render(<TemplatePicker open={true} onClose={() => {}} onSelect={() => {}} />, { wrapper });
    fireEvent.change(screen.getByTestId('template-picker-search'), {
      target: { value: 'ansible' },
    });
    expect(screen.getByTestId('template-picker-row-change_approval_ansible')).toBeInTheDocument();
    expect(screen.queryByTestId('template-picker-row-incident_triage')).toBeNull();
  });

  it('toggling recommended-only off re-queries with no filter', () => {
    mockUseTemplates.mockReturnValue({
      data: MOCK_TEMPLATES,
      isLoading: false,
      error: null,
    } as any);

    render(<TemplatePicker open={true} onClose={() => {}} onSelect={() => {}} />, { wrapper });
    // Default ON; the hook is called with recommendedOnly: true
    expect(mockUseTemplates).toHaveBeenCalledWith({ recommendedOnly: true });

    fireEvent.click(screen.getByTestId('template-picker-recommended-only'));
    // After toggle the hook is invoked with false
    expect(mockUseTemplates).toHaveBeenCalledWith({ recommendedOnly: false });
  });

  it('invokes onSelect with the template id when a row is clicked', () => {
    mockUseTemplates.mockReturnValue({
      data: MOCK_TEMPLATES,
      isLoading: false,
      error: null,
    } as any);
    const onSelect = vi.fn();

    render(<TemplatePicker open={true} onClose={() => {}} onSelect={onSelect} />, { wrapper });
    fireEvent.click(screen.getByTestId('template-picker-row-incident_triage'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith('incident_triage');
  });

  it('closes when the X button is clicked', () => {
    mockUseTemplates.mockReturnValue({
      data: MOCK_TEMPLATES,
      isLoading: false,
      error: null,
    } as any);
    const onClose = vi.fn();

    render(<TemplatePicker open={true} onClose={onClose} onSelect={() => {}} />, { wrapper });
    fireEvent.click(screen.getByLabelText(/close template picker/i));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on Escape key', async () => {
    mockUseTemplates.mockReturnValue({
      data: MOCK_TEMPLATES,
      isLoading: false,
      error: null,
    } as any);
    const onClose = vi.fn();

    render(<TemplatePicker open={true} onClose={onClose} onSelect={() => {}} />, { wrapper });
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
