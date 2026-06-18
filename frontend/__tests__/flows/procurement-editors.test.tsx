import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import jsYaml from 'js-yaml';
import {
  ApprovalEditor,
  WaitForFeedbackEditor,
  AuditTrailEditor,
  RuleCheckEditor,
} from '@/components/flows/register/guided/business-step-editors';
import { draftToUnifiedYaml } from '@/lib/flows/yaml-generator';
import { bindingToExpression } from '@/lib/flows/bindings';
import { emptyDraft, type FlowDraft, type WorkflowStepDraft } from '@/lib/flows/types';

afterEach(() => cleanup());

function makeHarness(Editor: typeof ApprovalEditor, initial: WorkflowStepDraft) {
  return function Harness() {
    const [step, setStep] = useState<WorkflowStepDraft>(initial);
    const draft: FlowDraft = {
      ...emptyDraft(),
      form: { fields: [{ name: 'contact_email', type: 'string', title: 'Contact email' }] },
      workflow: { planner_mode: 'deterministic', steps: [step] },
    };
    return (
      <div>
        <Editor
          step={step}
          draft={draft}
          priorStepIds={[]}
          onChange={(u) => setStep((s) => ({ ...s, ...u }))}
        />
        <pre data-testid="yaml">{draftToUnifiedYaml(draft)}</pre>
      </div>
    );
  };
}

describe('ApprovalEditor', () => {
  const Harness = makeHarness(ApprovalEditor, { id: 'review', type: 'human.approval', params: {} });

  it('shows business fields and hides the approval payload JSON by default', () => {
    render(<Harness />);
    expect(screen.getByText('Reviewers')).toBeInTheDocument();
    expect(screen.getByText(/approval title/i)).toBeInTheDocument();
    expect(screen.getByText(/message to the reviewer/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/review-params/i)).not.toBeInTheDocument();
  });

  it('reveals the raw params editor only in advanced mode', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /advanced/i }));
    expect(screen.getByLabelText(/review-params/i)).toBeInTheDocument();
  });
});

describe('WaitForFeedbackEditor', () => {
  const Harness = makeHarness(WaitForFeedbackEditor, {
    id: 'wait',
    type: 'webhook.wait',
    params: {},
  });

  it('writes the expected response name into params.event_name', () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/expected response name/i), {
      target: { value: 'rfq.supplier_feedback' },
    });
    expect(screen.getByTestId('yaml').textContent).toContain('event_name: rfq.supplier_feedback');
  });
});

describe('AuditTrailEditor', () => {
  const Harness = makeHarness(AuditTrailEditor, {
    id: 'audit_record',
    type: 'artifact.store',
    params: {},
  });

  it('maps saved items through binding chips into params.content', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: /add item to save/i }));
    fireEvent.change(screen.getByLabelText(/field name for mapping 1/i), {
      target: { value: 'contact' },
    });
    fireEvent.change(screen.getByLabelText(/source for mapping 1/i), { target: { value: 'form' } });
    fireEvent.change(screen.getByLabelText(/form field for mapping 1/i), {
      target: { value: 'contact_email' },
    });
    expect(screen.getByTestId('yaml').textContent).toContain(
      'contact: "{{ $form.contact_email }}"',
    );
  });
});

describe('RuleCheckEditor', () => {
  const Harness = makeHarness(RuleCheckEditor, { id: 'gate', type: 'condition' });

  it('builds a boolean condition without raw expression syntax in the default UI', () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/source for rule subject/i), {
      target: { value: 'form' },
    });
    fireEvent.change(screen.getByLabelText(/form field for rule subject/i), {
      target: { value: 'contact_email' },
    });
    fireEvent.change(screen.getByLabelText(/comparison value/i), { target: { value: 'true' } });
    expect(screen.getByTestId('yaml').textContent).toContain(
      'if: "{{ $form.contact_email == true }}"',
    );
  });
});

describe('RFQ document step regression — friendly state compiles to valid YAML', () => {
  it('produces a valid docx_render step from binding-built values', () => {
    const draft: FlowDraft = {
      ...emptyDraft(),
      workflow: {
        planner_mode: 'deterministic',
        steps: [
          {
            id: 'render_draft',
            type: 'tool.call',
            tool: 'docx_render',
            params: {
              template:
                "{{ $env('SAZ_RFQ_TEMPLATE', 'saz/examples/templates/rfq_template.docx') }}",
              output_name: `rfq_draft_${bindingToExpression({
                sourceType: 'form',
                sourceField: 'reference_number',
              })}`,
              require_all: false,
              values: {
                title_system_name: bindingToExpression({
                  sourceType: 'form',
                  sourceField: 'project_name',
                }),
                version: bindingToExpression({ sourceType: 'constant', sourceField: '0.1 DRAFT' }),
                background: bindingToExpression({
                  sourceType: 'previous_step',
                  sourceStepId: 'draft_narrative',
                  sourceField: 'background',
                }),
              },
            },
          },
        ],
      },
    };

    const reparsed = jsYaml.load(draftToUnifiedYaml(draft)) as any;
    const step = reparsed.workflow.steps[0];
    expect(step.type).toBe('tool.call');
    expect(step.tool).toBe('docx_render');
    expect(step.params.require_all).toBe(false);
    expect(step.params.output_name).toBe('rfq_draft_{{ $form.reference_number }}');
    expect(step.params.values.title_system_name).toBe('{{ $form.project_name }}');
    expect(step.params.values.version).toBe('0.1 DRAFT');
    expect(step.params.values.background).toBe("{{ $step('draft_narrative').background }}");
  });
});
