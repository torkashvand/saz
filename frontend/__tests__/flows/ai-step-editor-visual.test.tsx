import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { AiStepEditor } from '@/components/flows/register/guided/step-editors/ai-step-editor';
import { emptyDraft, type FlowDraft, type WorkflowStepDraft } from '@/lib/flows/types';

afterEach(cleanup);

function Harness({ initial }: { initial?: Partial<WorkflowStepDraft> }) {
  const [step, setStep] = useState<WorkflowStepDraft>({ id: 'a1', type: 'ai.assess', ...initial });
  const draft: FlowDraft = {
    ...emptyDraft(),
    form: { fields: [{ name: 'env', type: 'string', title: 'Environment' }] },
    workflow: { planner_mode: 'deterministic', steps: [step] },
  };
  return (
    <AiStepEditor
      step={step}
      draft={draft}
      priorStepIds={[]}
      onChange={(u) => setStep((s) => ({ ...s, ...u }))}
    />
  );
}

describe('AiStepEditor visual fields', () => {
  it('shows visual input + output editors and no raw JSON textareas by default', () => {
    render(
      <Harness
        initial={{ params: { data: { env: '' } }, expect: { type: 'object', properties: {} } }}
      />,
    );
    expect(screen.getByText(/input data/i)).toBeInTheDocument();
    expect(screen.getByText(/expected output fields/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/a1-params/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/a1-expect/i)).not.toBeInTheDocument();
  });

  it('reveals the raw output schema only behind Advanced', () => {
    render(<Harness initial={{ expect: { type: 'object', properties: {} } }} />);
    expect(screen.queryByLabelText(/a1-expect/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /advanced \(raw schema\)/i }));
    expect(screen.getByLabelText(/a1-expect/i)).toBeInTheDocument();
  });
});
