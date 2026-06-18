import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, within, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SectionNav } from '@/components/flows/register/guided/section-nav';
import { WorkflowStepsSection } from '@/components/flows/register/guided/workflow-steps-section';
import { ExpressionPicker } from '@/components/flows/register/guided/expression-picker';
import { BindingPicker } from '@/components/flows/register/guided/binding-picker';
import { DocumentGenerationEditor } from '@/components/flows/register/guided/business-step-editors/document-generation-editor';
import { useRef, useState } from 'react';
import type { FlowDraft, WorkflowStepDraft } from '@/lib/flows/types';
import { emptyDraft } from '@/lib/flows/types';
import type { BindingContext, FriendlyBinding } from '@/lib/flows/bindings';

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

describe('Accessibility — binding picker', () => {
  const context: BindingContext = {
    formFields: [{ name: 'project_name', type: 'string', title: 'Project name' }],
    steps: [{ id: 'draft_narrative', name: 'Draft narrative' }],
  };

  function Harness() {
    const [binding, setBinding] = useState<FriendlyBinding | null>(null);
    return (
      <BindingPicker
        label="output value"
        binding={binding}
        context={context}
        onChange={setBinding}
      />
    );
  }

  it('names the source picker and the active value control', () => {
    render(<Harness />);
    expect(screen.getByLabelText('Source for output value')).toBeInTheDocument();
    expect(screen.getByLabelText('Form field for output value')).toBeInTheDocument();
  });

  it('selects a previous-step value through accessible controls and shows a readable chip', () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText('Source for output value'), {
      target: { value: 'previous_step' },
    });
    fireEvent.change(screen.getByLabelText('Step for output value'), {
      target: { value: 'draft_narrative' },
    });
    fireEvent.change(screen.getByLabelText('Output field for output value'), {
      target: { value: 'background' },
    });
    expect(screen.getByText(/Draft narrative → background/)).toBeInTheDocument();
    expect(screen.queryByText(/\{\{/)).not.toBeInTheDocument();
  });

  it('names the system value and fallback controls', () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText('Source for output value'), {
      target: { value: 'system' },
    });
    expect(screen.getByLabelText('System value for output value')).toBeInTheDocument();
    expect(screen.getByLabelText('Fallback for output value')).toBeInTheDocument();
  });
});

describe('Accessibility — advanced disclosure', () => {
  function DocHarness() {
    const [step, setStep] = useState<WorkflowStepDraft>({
      id: 'render_draft',
      type: 'tool.call',
      tool: 'docx_render',
      params: { require_all: false, values: {} },
    });
    const draft: FlowDraft = {
      ...emptyDraft(),
      workflow: { planner_mode: 'deterministic', steps: [step] },
    };
    return (
      <DocumentGenerationEditor
        step={step}
        draft={draft}
        priorStepIds={[]}
        onChange={(u) => setStep((s) => ({ ...s, ...u }))}
      />
    );
  }

  it('controls the advanced section through a button whose accessible name reflects state', () => {
    render(<DocHarness />);
    const toggle = screen.getByRole('button', { name: /advanced \(technical settings\)/i });
    fireEvent.click(toggle);
    expect(screen.getByRole('button', { name: /hide advanced/i })).toBeInTheDocument();
  });
});
