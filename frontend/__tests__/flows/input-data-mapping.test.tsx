import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { InputDataMapping } from '@/components/flows/register/guided/step-editors/ai-fields/input-data-mapping';
import { emptyDraft, type FlowDraft, type WorkflowStepDraft } from '@/lib/flows/types';

afterEach(cleanup);

function Harness({ initial }: { initial?: Partial<WorkflowStepDraft> }) {
  const [step, setStep] = useState<WorkflowStepDraft>({ id: 'a1', type: 'ai.assess', ...initial });
  const draft: FlowDraft = {
    ...emptyDraft(),
    form: { fields: [{ name: 'target_environment', type: 'string', title: 'Environment' }] },
    workflow: { planner_mode: 'deterministic', steps: [step] },
  };
  return (
    <div>
      <InputDataMapping
        step={step}
        draft={draft}
        priorStepIds={[]}
        onChange={(u) => setStep((s) => ({ ...s, ...u }))}
      />
      <pre data-testid="params">{JSON.stringify(step.params)}</pre>
    </div>
  );
}

describe('InputDataMapping', () => {
  it('maps a form field into params.data without exposing template syntax', () => {
    render(<Harness initial={{ params: { data: { env: '' } } }} />);
    // No raw {{ }} text visible.
    expect(screen.queryByText(/\{\{/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/source for mapping 1/i), { target: { value: 'form' } });
    fireEvent.change(screen.getByLabelText(/form field for mapping 1/i), {
      target: { value: 'target_environment' },
    });
    const params = JSON.parse(screen.getByTestId('params').textContent || '{}');
    expect(params).toEqual({ data: { env: '{{ $form.target_environment }}' } });
  });

  it('falls back to a raw editor for non-string params.data values', () => {
    render(<Harness initial={{ params: { data: { nested: { a: 1 } } } }} />);
    expect(screen.getByText(/can't be shown in the visual editor/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/a1-params/i)).toBeInTheDocument();
  });
});
