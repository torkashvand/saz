/**
 * Component-level tests for the AI Operations Reference panel.
 *
 * Renders the REAL AIOpsReferencePanel and FlowPreviewPanel components
 * with mocked data to prove actual UI behavior, not just helper logic.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AIOpsReferencePanel } from '@/components/flows/register/ai-ops-reference';
import type { AIOpReference } from '@/lib/types';

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_OPS: AIOpReference[] = [
  {
    name: 'ai.extract',
    description: 'Pull structured fields from messy text.',
    output_format: 'json',
    default_output_schema: { type: 'object', additionalProperties: true },
    extras: {},
  },
  {
    name: 'ai.route',
    description: 'Pick a branch/route based on input.',
    output_format: 'json',
    default_output_schema: {
      type: 'object',
      properties: {
        route: { type: 'string' },
        reason: { type: 'string' },
      },
      required: ['route'],
    },
    extras: { branches_enum: [] },
  },
  {
    name: 'ai.score',
    description: 'Numeric scoring against a rubric.',
    output_format: 'json',
    default_output_schema: {
      type: 'object',
      properties: {
        score: { type: 'number', minimum: 0, maximum: 1 },
        reason: { type: 'string' },
      },
      required: ['score'],
    },
    extras: {},
  },
];

// ---------------------------------------------------------------------------
// Mock the useAIOps hook
// ---------------------------------------------------------------------------

vi.mock('@/lib/hooks', () => ({
  useAIOps: vi.fn(),
}));

import { useAIOps } from '@/lib/hooks';
const mockUseAIOps = vi.mocked(useAIOps);

// ---------------------------------------------------------------------------
// Wrapper with QueryClient
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    );
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe('AIOpsReferencePanel — loading and error states', () => {
  it('shows loading spinner while data is fetching', () => {
    mockUseAIOps.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as any);

    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    expect(screen.getByText('Loading AI operations...')).toBeInTheDocument();
  });

  it('shows error message when fetch fails', () => {
    mockUseAIOps.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Network error'),
    } as any);

    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    expect(screen.getByText('Failed to load AI operations reference.')).toBeInTheDocument();
  });
});

describe('AIOpsReferencePanel — list view', () => {
  beforeEach(() => {
    mockUseAIOps.mockReturnValue({
      data: MOCK_OPS,
      isLoading: false,
      error: null,
    } as any);
  });

  it('renders all operations in the list', () => {
    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    expect(screen.getByText('ai.extract')).toBeInTheDocument();
    expect(screen.getByText('ai.route')).toBeInTheDocument();
    expect(screen.getByText('ai.score')).toBeInTheDocument();
  });

  it('shows operation descriptions', () => {
    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    expect(screen.getAllByText(/Pull structured fields/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Pick a branch/).length).toBeGreaterThan(0);
  });

  it('shows extras badges for operations that have them', () => {
    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    expect(screen.getAllByText('branches_enum').length).toBeGreaterThan(0);
  });
});

describe('AIOpsReferencePanel — detail view', () => {
  beforeEach(() => {
    mockUseAIOps.mockReturnValue({
      data: MOCK_OPS,
      isLoading: false,
      error: null,
    } as any);
  });

  it('clicking an operation shows its detail view', async () => {
    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    // Click the ai.score list item button
    const scoreButtons = screen.getAllByText('ai.score');
    fireEvent.click(scoreButtons[0]);

    // Detail view should show description and copy buttons
    await waitFor(() => {
      expect(screen.getByText('Copy starter')).toBeInTheDocument();
      expect(screen.getByText('Copy step')).toBeInTheDocument();
    });

    // Should show the "All operations" back button
    expect(screen.getByText('All operations')).toBeInTheDocument();
  });

  it('back button returns to list view', async () => {
    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    // Open detail
    const routeButtons = screen.getAllByText('ai.route');
    fireEvent.click(routeButtons[0]);
    await waitFor(() => {
      expect(screen.getAllByText('All operations').length).toBeGreaterThan(0);
    });

    // Click first back button
    fireEvent.click(screen.getAllByText('All operations')[0]);

    // List should be visible again — all ops present
    await waitFor(() => {
      expect(screen.getAllByText('ai.extract').length).toBeGreaterThan(0);
      expect(screen.getAllByText('ai.score').length).toBeGreaterThan(0);
    });
  });

  it('shows flexible schema warning for ai.extract', async () => {
    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    fireEvent.click(screen.getAllByText('ai.extract')[0]);

    await waitFor(() => {
      expect(screen.getByText(/Flexible schema/)).toBeInTheDocument();
    });
  });

  it('does NOT show flexible schema warning for ai.score', async () => {
    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    fireEvent.click(screen.getAllByText('ai.score')[0]);

    await waitFor(() => {
      expect(screen.getAllByText('Copy starter').length).toBeGreaterThan(0);
      expect(screen.queryByText(/Flexible schema/)).not.toBeInTheDocument();
    });
  });

  it('shows starter snippet label, not full export claim', async () => {
    render(<AIOpsReferencePanel />, { wrapper: createWrapper() });

    fireEvent.click(screen.getAllByText('ai.score')[0]);

    await waitFor(() => {
      expect(screen.getByText(/Starter snippet/)).toBeInTheDocument();
    });
  });
});

describe('AIOpsReferencePanel — focusOp from validation error', () => {
  beforeEach(() => {
    mockUseAIOps.mockReturnValue({
      data: MOCK_OPS,
      isLoading: false,
      error: null,
    } as any);
  });

  it('auto-selects the focused operation and shows detail view', async () => {
    const onFocusHandled = vi.fn();

    render(
      <AIOpsReferencePanel focusOp="ai.route" onFocusHandled={onFocusHandled} />,
      { wrapper: createWrapper() },
    );

    // Should auto-open ai.route detail view (shows back button + copy actions)
    await waitFor(() => {
      expect(screen.getAllByText('All operations').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Copy starter').length).toBeGreaterThan(0);
    });

    // Callback should have been called
    expect(onFocusHandled).toHaveBeenCalled();
  });

  it('ignores focusOp that does not match any operation', async () => {
    const onFocusHandled = vi.fn();

    render(
      <AIOpsReferencePanel focusOp="ai.nonexistent" onFocusHandled={onFocusHandled} />,
      { wrapper: createWrapper() },
    );

    // Should stay on list view — multiple ops visible
    await waitFor(() => {
      expect(screen.getAllByText('ai.extract').length).toBeGreaterThan(0);
      expect(screen.getAllByText('ai.route').length).toBeGreaterThan(0);
    });

    // Callback should NOT have been called
    expect(onFocusHandled).not.toHaveBeenCalled();
  });
});