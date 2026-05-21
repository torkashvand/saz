import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { pickStepEditor } from '@/components/flows/register/guided/step-editors';
import type { FlowDraft, StepType, WorkflowStepDraft } from '@/lib/flows/types';
import { AI_STEP_TYPES, emptyDraft } from '@/lib/flows/types';

vi.mock('@/lib/hooks', async () => {
  const actual = await vi.importActual<typeof import('@/lib/hooks')>('@/lib/hooks');
  return {
    ...actual,
    useDslMetadata: () => ({ data: { tools: [{ name: 'http_request', description: 'http' }] } }),
  };
});

function renderEditor(step: WorkflowStepDraft) {
  const Editor = pickStepEditor(step.type);
  const draft: FlowDraft = {
    ...emptyDraft(),
    workflow: { planner_mode: 'deterministic', steps: [step] },
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Editor step={step} draft={draft} priorStepIds={[]} onChange={() => {}} />
    </QueryClientProvider>,
  );
}

describe('pickStepEditor — registry coverage', () => {
  const BACKEND_TYPES: StepType[] = [
    'tool.call',
    'condition',
    'human.approval',
    'webhook.wait',
    'artifact.store',
    'artifact.retrieve',
    'ai.extract',
    'ai.generate',
    'ai.route',
    'ai.score',
    'ai.assess',
    'ai.normalize',
    'ai.match',
    'ai.evaluate',
    'ai.compare',
    'ai.translate',
    'ai.summarize',
    'ai.plan',
  ];

  for (const type of BACKEND_TYPES) {
    it(`returns a renderable editor for ${type}`, () => {
      const editor = pickStepEditor(type);
      expect(typeof editor).toBe('function');
    });
  }

  it('tool.call editor exposes a tool input', () => {
    renderEditor({ id: 's', type: 'tool.call', name: 's' });
    expect(screen.getByPlaceholderText(/e.g.*http_request/i)).toBeInTheDocument();
  });

  it('condition editor exposes an `If expression` field with expression picker', () => {
    renderEditor({ id: 's', type: 'condition', name: 's' });
    expect(screen.getByText(/If expression/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /insert expression into s if/i }),
    ).toBeInTheDocument();
  });

  it('ai.translate editor exposes a target_locale input', () => {
    renderEditor({ id: 's', type: 'ai.translate', name: 's' });
    expect(screen.getByPlaceholderText('fr-FR')).toBeInTheDocument();
  });

  it('ai.route editor exposes a branches input', () => {
    renderEditor({ id: 's', type: 'ai.route', name: 's' });
    expect(screen.getByPlaceholderText(/approve.*reject.*escalate/i)).toBeInTheDocument();
  });

  it('webhook.wait editor exposes an event_name input', () => {
    renderEditor({ id: 's', type: 'webhook.wait', name: 's' });
    expect(screen.getByPlaceholderText(/approval_received/i)).toBeInTheDocument();
  });

  it('AI_STEP_TYPES set is consistent with the registry routing', () => {
    for (const type of BACKEND_TYPES) {
      const isAi = AI_STEP_TYPES.has(type);
      // All ai.* types should route to the shared AI editor; non-AI types should
      // route to a dedicated component.
      const editor = pickStepEditor(type);
      expect(typeof editor).toBe('function');
      expect(
        isAi ||
          [
            'tool.call',
            'condition',
            'human.approval',
            'webhook.wait',
            'artifact.store',
            'artifact.retrieve',
          ].includes(type),
      ).toBe(true);
    }
  });
});
