import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { WorkflowStepsSection } from '@/components/flows/register/guided/workflow-steps-section';
import { setActiveDomainPack } from '@/lib/flows/domain-packs/registry';
import type { FlowDraft } from '@/lib/flows/types';
import { emptyDraft } from '@/lib/flows/types';

vi.mock('@/lib/hooks', async () => {
  const actual = await vi.importActual<typeof import('@/lib/hooks')>('@/lib/hooks');
  return { ...actual, useDslMetadata: () => ({ data: { tools: [] } }) };
});

afterEach(() => {
  cleanup();
  setActiveDomainPack('generic');
});

function wrapped(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

function draftWithDocStep(): FlowDraft {
  return {
    ...emptyDraft(),
    form: { fields: [{ name: 'reference_number', type: 'string', title: 'Reference number' }] },
    workflow: {
      planner_mode: 'deterministic',
      steps: [
        {
          id: 'render_draft',
          type: 'tool.call',
          tool: 'docx_render',
          params: { require_all: false, values: {} },
        },
      ],
    },
  };
}

describe('WorkflowStepsSection — business mode', () => {
  it('shows a business label and hides the internal Step ID by default', () => {
    render(wrapped(<WorkflowStepsSection draft={draftWithDocStep()} onChange={() => {}} />));
    // Default pack is generic — neutral label, no domain wording.
    expect(screen.getByText(/create document/i)).toBeInTheDocument();
    expect(screen.queryByText(/RFQ/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Step ID')).not.toBeInTheDocument();
  });

  it('uses domain-pack labels once a pack is active', () => {
    setActiveDomainPack('procurement');
    render(wrapped(<WorkflowStepsSection draft={draftWithDocStep()} onChange={() => {}} />));
    expect(screen.getByText(/create draft.*document/i)).toBeInTheDocument();
  });

  it('reveals the internal Step ID and type once expert mode is enabled', () => {
    render(wrapped(<WorkflowStepsSection draft={draftWithDocStep()} onChange={() => {}} />));
    fireEvent.click(screen.getByRole('switch', { name: /expert mode/i }));
    expect(screen.getByText('Step ID')).toBeInTheDocument();
    expect(screen.getByDisplayValue('render_draft')).toBeInTheDocument();
  });

  it('keeps duplicate and delete actions available in business mode', () => {
    render(wrapped(<WorkflowStepsSection draft={draftWithDocStep()} onChange={() => {}} />));
    expect(screen.getByRole('button', { name: /Duplicate step render_draft/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Delete step render_draft/ })).toBeInTheDocument();
  });
});

describe('WorkflowStepsSection — Add business step picker', () => {
  function StatefulHarness() {
    const [draft, setDraft] = useState<FlowDraft>(emptyDraft());
    return (
      <WorkflowStepsSection draft={draft} onChange={(u) => setDraft((d) => ({ ...d, ...u }))} />
    );
  }

  it('adds a document step via the business pattern picker', () => {
    render(wrapped(<StatefulHarness />));
    fireEvent.click(screen.getByRole('button', { name: /add step/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /create document/i }));

    expect(screen.getByText(/create document/i)).toBeInTheDocument();
    // Created in business mode — no internal Step ID exposed.
    expect(screen.queryByText('Step ID')).not.toBeInTheDocument();
  });

  it('adds a review & approval step via the picker', () => {
    render(wrapped(<StatefulHarness />));
    fireEvent.click(screen.getByRole('button', { name: /add step/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /review/i }));
    expect(screen.getByText('Reviewers')).toBeInTheDocument();
  });

  it('exposes the picker as an accessible menu button with aria-expanded', () => {
    render(wrapped(<StatefulHarness />));
    const trigger = screen.getByRole('button', { name: /add step/i });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    // Every option is reachable as a named menuitem.
    const items = screen.getAllByRole('menuitem');
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) expect(item).toHaveAccessibleName();
  });

  it('offers an Advanced group covering the AI / technical step types', () => {
    render(wrapped(<StatefulHarness />));
    fireEvent.click(screen.getByRole('button', { name: /add step/i }));
    // Business patterns plus the AI family, generic tool call and artifact retrieve.
    expect(screen.getByRole('menuitem', { name: /AI · AI Extract/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /AI · AI Generate/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Integration · Tool Call/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Data · Retrieve Artifact/i })).toBeInTheDocument();
  });

  it('scrolls the newly added step into view', () => {
    const spy = vi.spyOn(HTMLElement.prototype, 'scrollIntoView');
    render(wrapped(<StatefulHarness />));
    fireEvent.click(screen.getByRole('button', { name: /add step/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /create.*document/i }));
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });

  it('adds an AI step from the Advanced group while staying in business mode', () => {
    render(wrapped(<StatefulHarness />));
    fireEvent.click(screen.getByRole('button', { name: /add step/i }));
    fireEvent.click(screen.getByRole('menuitem', { name: /AI · AI Extract/i }));
    // Rendered as a generic technical step — no expert switch needed.
    expect(screen.getByText('Advanced step')).toBeInTheDocument();
    expect(screen.getByText(/Expert step/)).toBeInTheDocument();
    // Still business mode: the internal Step ID stays hidden.
    expect(screen.queryByText('Step ID')).not.toBeInTheDocument();
  });
});

describe('WorkflowStepsSection — expert mode toggle', () => {
  it('is a switch whose checked state reflects expert mode', () => {
    render(wrapped(<WorkflowStepsSection draft={draftWithDocStep()} onChange={() => {}} />));
    const toggle = screen.getByRole('switch', { name: /expert mode/i });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText('Step ID')).toBeInTheDocument();
  });
});

describe('WorkflowStepsSection — step presentation', () => {
  function draftWith(steps: FlowDraft['workflow']['steps'], fields: FlowDraft['form'] = undefined) {
    return {
      ...emptyDraft(),
      form: fields,
      workflow: { planner_mode: 'deterministic' as const, steps },
    };
  }

  it('flags a document step with no mappings as Missing mappings', () => {
    render(wrapped(<WorkflowStepsSection draft={draftWithDocStep()} onChange={() => {}} />));
    expect(screen.getByText('Missing mappings')).toBeInTheDocument();
  });

  it('shows the reviewer for an approval step', () => {
    const draft = draftWith(
      [
        {
          id: 'review',
          type: 'human.approval',
          params: { approvers: ['{{ $form.contact_email }}'] },
        },
      ],
      { fields: [{ name: 'contact_email', type: 'string', title: 'Contact email' }] },
    );
    render(wrapped(<WorkflowStepsSection draft={draft} onChange={() => {}} />));
    // Scope to the presentation reviewer line (the approval editor also echoes the email).
    expect(screen.getByText(/Reviewer:/)).toHaveTextContent(/Contact email/);
  });

  it('marks an unsupported technical step with the Advanced step status and expert fallback', () => {
    const draft = draftWith([{ id: 'classify', type: 'ai.extract' }]);
    render(wrapped(<WorkflowStepsSection draft={draft} onChange={() => {}} />));
    expect(screen.getByText('Advanced step')).toBeInTheDocument();
    expect(screen.getByText(/Expert step/)).toBeInTheDocument();
  });
});
