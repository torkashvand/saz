// Mirrors the Ansible change-review AI step an operator configures in the
// builder: input data is a flat map of form bindings; the output schema uses
// `description` + `enum` + `minItems`, all inside the widened v1 subset, so it
// round-trips fully through the visual editor.
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { useState } from 'react';
import { AiStepEditor } from '@/components/flows/register/guided/step-editors/ai-step-editor';
import { readInputData } from '@/lib/flows/ai-input-data';
import { schemaToFriendly, friendlyToSchema } from '@/lib/flows/output-schema';
import { emptyDraft, type FlowDraft, type WorkflowStepDraft } from '@/lib/flows/types';

afterEach(cleanup);

const CHANGE_REVIEW_PARAMS = {
  data: {
    change_title: '{{ $form.change_title }}',
    target_environment: '{{ $form.target_environment }}',
    target_hosts: '{{ $form.target_hosts }}',
    requested_action: '{{ $form.requested_action }}',
    maintenance_window: '{{ $form.maintenance_window }}',
    rollback_plan: '{{ $form.rollback_plan }}',
    risk_hint: '{{ $form.risk_hint }}',
    requester: '{{ $form.requester }}',
  },
};

const CHANGE_REVIEW_EXPECT = {
  type: 'object',
  additionalProperties: false,
  properties: {
    change_intent: { type: 'string', description: 'One-sentence restatement' },
    affected_targets: { type: 'array', items: { type: 'string' } },
    risk_level: { type: 'string', enum: ['low', 'medium', 'high', 'critical'] },
    blast_radius: { type: 'string' },
    pre_checks: { type: 'array', items: { type: 'string' }, minItems: 1 },
    rollback_summary: { type: 'string' },
    approval_recommendation: {
      type: 'string',
      enum: ['approve', 'review_required', 'reject'],
    },
    reasoning: { type: 'string' },
  },
  required: [
    'change_intent',
    'affected_targets',
    'risk_level',
    'blast_radius',
    'pre_checks',
    'rollback_summary',
    'approval_recommendation',
    'reasoning',
  ],
};

function Harness() {
  const [step, setStep] = useState<WorkflowStepDraft>({
    id: 'review_change',
    type: 'ai.assess',
    params: CHANGE_REVIEW_PARAMS,
    expect: CHANGE_REVIEW_EXPECT,
  });
  const draft: FlowDraft = {
    ...emptyDraft(),
    form: {
      fields: [
        { name: 'change_title', type: 'string', title: 'Change title' },
        { name: 'target_environment', type: 'string', title: 'Environment' },
      ],
    },
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

describe('change-review regression', () => {
  it('reads all eight form bindings as visual input rows', () => {
    const { supported, values } = readInputData(CHANGE_REVIEW_PARAMS);
    expect(supported).toBe(true);
    expect(Object.keys(values)).toHaveLength(8);
  });

  it('round-trips the full example output schema (description + enum + minItems all supported)', () => {
    const parsed = schemaToFriendly(CHANGE_REVIEW_EXPECT);
    expect(parsed.supported).toBe(true);
    expect(friendlyToSchema(parsed.schema)).toEqual(CHANGE_REVIEW_EXPECT);
  });

  it('still falls back safely for a genuinely unsupported (nested object) schema', () => {
    const nested = {
      type: 'object',
      properties: { detail: { type: 'object', properties: { a: { type: 'string' } } } },
    };
    expect(schemaToFriendly(nested).supported).toBe(false);
  });

  it('renders the example fully visually — no raw template text, no fallback warning', () => {
    render(<Harness />);
    // Input maps visually (no raw template text).
    expect(screen.getByText(/input data/i)).toBeInTheDocument();
    expect(screen.queryByText(/\{\{ \$form/)).not.toBeInTheDocument();
    // Output schema renders as visual fields, not the raw fallback.
    expect(screen.getByText(/expected output fields/i)).toBeInTheDocument();
    expect(screen.queryByText(/can't be shown in the visual editor/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/review_change-expect/i)).not.toBeInTheDocument();
  });
});
