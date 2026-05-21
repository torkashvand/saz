import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, within, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SectionNav } from '@/components/flows/register/guided/section-nav';
import { WorkflowStepsSection } from '@/components/flows/register/guided/workflow-steps-section';
import { ExpressionPicker } from '@/components/flows/register/guided/expression-picker';
import { useRef, useState } from 'react';
import type { FlowDraft } from '@/lib/flows/types';
import { emptyDraft } from '@/lib/flows/types';

vi.mock('@/lib/hooks', async () => {
  const actual = await vi.importActual<typeof import('@/lib/hooks')>('@/lib/hooks');
  return {
    ...actual,
    useDslMetadata: () => ({ data: { tools: [] } }),
  };
});

afterEach(() => cleanup());

function wrapped(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

describe('Accessibility — guided builder shell', () => {
  it('SectionNav exposes a labelled nav and aria-current on the active section', () => {
    render(<SectionNav activeSection="steps" onSectionClick={() => {}} />);
    expect(screen.getByRole('navigation', { name: /Guided builder sections/ })).toBeInTheDocument();
    const stepsBtn = screen.getByRole('button', { name: /Workflow Steps/ });
    expect(stepsBtn.getAttribute('aria-current')).toBe('true');
  });

  it('SectionNav error badges have descriptive aria-labels (not just "1")', () => {
    render(
      <SectionNav
        onSectionClick={() => {}}
        errors={[{ section: 'workflow', step_id: 's1', message: 'bad' }]}
      />,
    );
    const badge = screen.getByLabelText(/1 error in Workflow Steps/);
    expect(badge).toBeInTheDocument();
  });

  it('Step cards expose aria-label for duplicate and delete actions', () => {
    const draft: FlowDraft = {
      ...emptyDraft(),
      workflow: {
        planner_mode: 'deterministic',
        steps: [{ id: 'step_1', type: 'ai.extract', name: 'Step 1' }],
      },
    };
    render(wrapped(<WorkflowStepsSection draft={draft} onChange={() => {}} />));
    expect(screen.getByRole('button', { name: /Duplicate step step_1/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Delete step step_1/ })).toBeInTheDocument();
  });
});

describe('Accessibility — expression picker', () => {
  function Harness() {
    const inputRef = useRef<HTMLInputElement | null>(null);
    const [value, setValue] = useState('');
    return (
      <div>
        <input
          ref={inputRef}
          aria-label="target"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <ExpressionPicker
          inputRef={inputRef as React.RefObject<HTMLInputElement>}
          value={value}
          onChange={setValue}
          draft={emptyDraft()}
          triggerLabel="Insert expression into step body"
        />
      </div>
    );
  }

  it('trigger button has an accessible name and aria-expanded', () => {
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: /Insert expression into step body/ });
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
  });

  it('opened picker has a dialog role and aria-label', () => {
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: /Insert expression into step body/ });
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: /Expression picker/ });
    expect(dialog).toBeInTheDocument();
    // The $env helper is always present so the dialog has at least one option.
    expect(within(dialog).getByText('$env(VAR)')).toBeInTheDocument();
  });
});
