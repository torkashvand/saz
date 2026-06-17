import { render, screen, fireEvent, within, cleanup } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

afterEach(cleanup);

import { HumanApprovalPanel } from '@/components/runs/human-approval-panel';
import type {
  ApprovalBrief,
  HumanApprovalError,
  RunDetailResponse,
  RunStep,
  PlannedStep,
} from '@/lib/types';

const APPROVAL_ERROR: HumanApprovalError = {
  message: 'Procurement officer reviews narrative and PONT findings before drafting.',
  type: 'HumanApprovalRequired',
  step_id: 'procurement_review',
  callback_id: 'cb-123',
};

const PLANNED_STEPS: PlannedStep[] = [
  { index: 0, id: 'validate_inputs', name: 'validate_inputs', step_type: 'ai.extract' },
  { index: 1, id: 'pont_check', name: 'pont_check', step_type: 'ai.evaluate' },
  { index: 2, id: 'procurement_review', name: 'procurement_review', step_type: 'human.approval' },
  { index: 3, id: 'render_draft', name: 'render_draft', step_type: 'tool.call' },
  { index: 4, id: 'store_artifact', name: 'store_artifact', step_type: 'artifact.store' },
];

const SERVER_BRIEF: ApprovalBrief = {
  decision_title: 'Approve moving this RFQ package to draft generation?',
  readiness: 'review_required',
  readiness_label: 'Review required — PONT findings',
  main_reason: 'PONT check raised concerns that need review before drafting.',
  critical_issues: ['PONT/compliance check did not pass'],
  passed_checks: ['No missing fields', 'No inconsistencies'],
  key_facts: [
    { label: 'Project', value: 'HR Information System' },
    { label: 'Estimated value', value: '€30,000' },
  ],
  approval_consequence: 'If approved, Saz will draft the RFQ document and continue.',
  source_step_ids: ['validate_inputs', 'pont_check'],
  generation_status: 'generated',
  warnings: [],
};

function step(overrides: Partial<RunStep>): RunStep {
  return {
    id: overrides.id ?? overrides.name ?? 'step',
    number: 0,
    name: 'step',
    attempt: 1,
    step_type: 'ai.extract',
    status: 'completed',
    retry_count: 0,
    ...overrides,
  };
}

function makeRun(
  opts: { brief?: ApprovalBrief | null; overrides?: Partial<RunDetailResponse> } = {},
) {
  const briefInput = opts.brief === undefined ? SERVER_BRIEF : opts.brief;
  return {
    id: 'run-1',
    flow_id: 'flow-1',
    flow_name: 'rfq_rfp_drafting',
    status: 'suspended',
    planner_mode: 'deterministic',
    payload: {
      project_name: 'HR Information System',
      criticality: 'high',
      estimated_value_eur: 30000,
      // Non-curated raw fields that must stay out of the default view:
      budget_cap_licenses_eur: 20000,
      sourcing_strategy: 'open',
    },
    created_at: '2026-06-17T00:00:00Z',
    total_tokens: 0,
    total_cost_usd: 0,
    steps: [
      step({
        id: 's1',
        name: 'validate_inputs',
        step_type: 'ai.extract',
        output: { missing_fields: [], inconsistencies: [] },
      }),
      step({
        id: 's2',
        name: 'pont_check',
        step_type: 'ai.evaluate',
        output: { pass: false, issues: ['Criteria not measurable'] },
      }),
      step({
        id: 's3',
        name: 'procurement_review',
        step_type: 'human.approval',
        status: 'suspended',
        input: briefInput ? { approval_brief: briefInput } : undefined,
      }),
    ],
    planned_steps: PLANNED_STEPS,
    ...opts.overrides,
  } as RunDetailResponse;
}

function renderPanel(
  run: RunDetailResponse,
  error: HumanApprovalError = APPROVAL_ERROR,
  isPending = false,
) {
  const onApprove = vi.fn();
  const onReject = vi.fn();
  render(
    <HumanApprovalPanel
      approvalError={error}
      run={run}
      onApprove={onApprove}
      onReject={onReject}
      isPending={isPending}
    />,
  );
  return { onApprove, onReject };
}

describe('HumanApprovalPanel — server-generated brief', () => {
  it('renders the brief decision title, readiness, reason, issues, facts, and consequence', () => {
    renderPanel(makeRun());

    expect(screen.getByTestId('decision-question')).toHaveTextContent(
      'Approve moving this RFQ package to draft generation?',
    );
    expect(screen.getByTestId('decision-question')).toHaveTextContent(
      /PONT check raised concerns/i,
    );
    expect(screen.getByTestId('readiness-state')).toHaveTextContent(
      'Review required — PONT findings',
    );

    const issues = screen.getByTestId('critical-issues');
    expect(within(issues).getByText('PONT/compliance check did not pass')).toBeInTheDocument();

    const facts = screen.getByTestId('key-facts');
    expect(within(facts).getByText('Project')).toBeInTheDocument();
    expect(within(facts).getByText('HR Information System')).toBeInTheDocument();
    expect(within(facts).getByText('€30,000')).toBeInTheDocument();

    expect(screen.getByTestId('after-approval')).toHaveTextContent(
      'If approved, Saz will draft the RFQ document and continue.',
    );
  });

  it('uses amber (not red) for review_required readiness', () => {
    renderPanel(makeRun());
    expect(screen.getByTestId('readiness-state').className).toContain('amber');
    expect(screen.getByTestId('readiness-state').className).not.toContain('red');
  });

  it('uses a strong red treatment for blocked readiness', () => {
    const blocked: ApprovalBrief = {
      ...SERVER_BRIEF,
      readiness: 'blocked',
      readiness_label: 'Blocked — missing required information',
    };
    renderPanel(makeRun({ brief: blocked }));
    expect(screen.getByTestId('readiness-state').className).toContain('red');
  });

  it('does not show raw payload as primary content', () => {
    renderPanel(makeRun());
    expect(screen.queryByText('budget_cap_licenses_eur')).not.toBeInTheDocument();
    expect(screen.queryByText('sourcing_strategy')).not.toBeInTheDocument();
    expect(screen.queryByText('View full run payload')).not.toBeInTheDocument();
  });

  it('keeps raw details and the callback path under collapsed advanced details', () => {
    renderPanel(makeRun());
    expect(screen.queryByText('Full step outputs')).not.toBeInTheDocument();
    expect(screen.queryByTestId('callback-url-block')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Advanced details'));

    expect(screen.getByText('View full run payload')).toBeInTheDocument();
    expect(screen.getByText('Full step outputs')).toBeInTheDocument();
    expect(screen.getByTestId('callback-url-block')).toBeInTheDocument();
    expect(screen.getByText(/Approval brief \(generated\)/)).toBeInTheDocument();
  });
});

describe('HumanApprovalPanel — missing/malformed brief fallback', () => {
  it('renders a clear generic packet when no brief is present', () => {
    renderPanel(makeRun({ brief: null }));
    // A synthesized decision question still appears.
    expect(screen.getByTestId('decision-question')).toHaveTextContent(
      /Approve continuing to Render draft/i,
    );
    // Derived from the failed PONT output, not raw JSON.
    expect(screen.getByTestId('readiness-state')).toHaveTextContent('Review required');
    const issues = screen.getByTestId('critical-issues');
    expect(within(issues).getByText(/PONT\/compliance check did not pass/i)).toBeInTheDocument();
    // Key facts derived from payload.
    expect(
      within(screen.getByTestId('key-facts')).getByText('HR Information System'),
    ).toBeInTheDocument();
    // Raw payload still not primary.
    expect(screen.queryByText('budget_cap_licenses_eur')).not.toBeInTheDocument();
  });

  it('falls back when the brief is malformed', () => {
    const malformed = { decision_title: 123, readiness: 'banana' } as unknown as ApprovalBrief;
    renderPanel(makeRun({ brief: malformed }));
    // Does not crash; shows a synthesized question instead.
    expect(screen.getByTestId('decision-question')).toHaveTextContent(/Approve continuing/i);
  });
});

describe('HumanApprovalPanel — actions', () => {
  it('approves through the confirm step', () => {
    const { onApprove } = renderPanel(makeRun());
    fireEvent.click(screen.getByRole('button', { name: /Approve and continue/i }));
    fireEvent.change(screen.getByLabelText('Approval comments'), { target: { value: 'ok' } });
    const buttons = screen.getAllByRole('button', { name: /Approve and continue/i });
    fireEvent.click(buttons[buttons.length - 1]);
    expect(onApprove).toHaveBeenCalledWith({ approved: true, comments: 'ok' });
  });

  it('requires a reason before rejecting', () => {
    const { onReject } = renderPanel(makeRun());
    fireEvent.click(screen.getByRole('button', { name: /Reject and stop/i }));
    const buttons = screen.getAllByRole('button', { name: /Reject and stop/i });
    const confirm = buttons[buttons.length - 1];
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Rejection reason'), {
      target: { value: 'Budget exceeded' },
    });
    expect(confirm).not.toBeDisabled();
    fireEvent.click(confirm);
    expect(onReject).toHaveBeenCalledWith({ approved: false, reason: 'Budget exceeded' });
  });

  it('disables actions while a decision is pending', () => {
    renderPanel(makeRun(), APPROVAL_ERROR, true);
    expect(screen.getByRole('button', { name: /Approve and continue/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Reject and stop/i })).toBeDisabled();
  });
});

describe('HumanApprovalPanel — non-procurement workflow', () => {
  it('renders a useful generic packet without procurement labels', () => {
    const run = makeRun({
      brief: null,
      overrides: {
        flow_name: 'generic_approval',
        payload: { ticket: 'OPS-42' },
        steps: [
          step({ id: 'g1', name: 'fetch_data', step_type: 'tool.call', output: { rows: 12 } }),
          step({ id: 'g2', name: 'gate', step_type: 'human.approval', status: 'suspended' }),
        ],
        planned_steps: [
          { index: 0, id: 'fetch_data', name: 'fetch_data', step_type: 'tool.call' },
          { index: 1, id: 'gate', name: 'gate', step_type: 'human.approval' },
          { index: 2, id: 'notify', name: 'notify', step_type: 'tool.call' },
        ],
      },
    });
    renderPanel(run, { ...APPROVAL_ERROR, step_id: 'gate', callback_id: undefined });

    expect(screen.getByText('Approval needed: Gate')).toBeInTheDocument();
    expect(screen.getByTestId('decision-question')).toHaveTextContent(
      /Approve continuing to Notify/i,
    );
    expect(screen.getByTestId('readiness-state')).toHaveTextContent('Approval required');
    // No curated facts → no key-facts section, but actions still render.
    expect(screen.queryByTestId('key-facts')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Approve and continue/i })).toBeInTheDocument();
  });
});
