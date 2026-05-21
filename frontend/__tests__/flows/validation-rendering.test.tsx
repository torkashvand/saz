import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import { SectionNav } from '@/components/flows/register/guided/section-nav';
import { FlowPreviewPanel } from '@/components/flows/register/flow-preview-panel';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { FlowDraft, ValidationError, ValidationResult } from '@/lib/flows/types';
import { emptyDraft } from '@/lib/flows/types';

afterEach(() => cleanup());

function wrapped(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

describe('SectionNav — per-section error badges', () => {
  it('shows error count badge for the workflow section when step errors exist', () => {
    const errors: ValidationError[] = [
      { section: 'workflow', step_id: 's1', message: 'bad step' },
      { section: 'workflow', step_id: 's2', message: 'also bad' },
    ];
    render(<SectionNav onSectionClick={() => {}} errors={errors} />);
    const stepsBtn = screen.getByRole('button', { name: /Workflow Steps/ });
    const badge = within(stepsBtn).getByText('2');
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute('aria-label')).toMatch(/2 errors in Workflow Steps/);
  });

  it('routes flow-section errors to the basics nav entry', () => {
    const errors: ValidationError[] = [{ section: 'flow', message: 'flow.name required' }];
    render(<SectionNav onSectionClick={() => {}} errors={errors} />);
    const basicsBtn = screen.getByRole('button', { name: /^Basics/ });
    expect(within(basicsBtn).getByText('1')).toBeInTheDocument();
  });

  it('renders no badges when there are no errors', () => {
    render(<SectionNav onSectionClick={() => {}} />);
    expect(screen.queryByText(/^[1-9]$/)).not.toBeInTheDocument();
  });

  it('marks the active section with aria-current', () => {
    render(<SectionNav activeSection="policies" onSectionClick={() => {}} />);
    const policiesBtn = screen.getByRole('button', { name: /Policies/ });
    expect(policiesBtn.getAttribute('aria-current')).toBe('true');
  });
});

describe('FlowPreviewPanel — error list', () => {
  function makeDraft(): FlowDraft {
    return emptyDraft();
  }

  it('renders [section] and step_id labels in the error summary', () => {
    const result: ValidationResult = {
      valid: false,
      errors: [
        { section: 'workflow', step_id: 'classify', message: 'expect is required' },
        { section: 'policies', message: 'budget must be >= 0' },
      ],
    };
    render(wrapped(<FlowPreviewPanel validationResult={result} draft={makeDraft()} />));
    // section labels are wrapped like [workflow]
    expect(screen.getByText(/\[workflow\]/)).toBeInTheDocument();
    expect(screen.getByText(/classify:/)).toBeInTheDocument();
    expect(screen.getByText(/\[policies\]/)).toBeInTheDocument();
  });

  it('shows "Valid" status when the validation result is valid', () => {
    const result: ValidationResult = { valid: true, errors: [] };
    render(wrapped(<FlowPreviewPanel validationResult={result} draft={makeDraft()} />));
    expect(screen.getByText(/Flow is ready to register/)).toBeInTheDocument();
  });
});
