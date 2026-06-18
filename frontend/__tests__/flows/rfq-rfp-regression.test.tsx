import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import jsYaml from 'js-yaml';
import { yamlToDraft } from '@/lib/flows/yaml-parser';
import { draftToUnifiedYaml } from '@/lib/flows/yaml-generator';
import { WorkflowStepsSection } from '@/components/flows/register/guided/workflow-steps-section';
import { classifyPattern, resolvePresentation } from '@/lib/flows/business-step-metadata';
import { procurementPack } from '@/lib/flows/domain-packs/procurement';
import { setActiveDomainPack } from '@/lib/flows/domain-packs/registry';

// Single constant compile response — parsing only needs valid=true here.
vi.mock('@/lib/api', () => ({
  api: {
    compileFlow: vi.fn(async () => ({
      valid: true,
      flow_name: 'rfq_rfp_drafting',
      flow_version: '1.0',
      flow_description: 'regression fixture',
      form_schema: { properties: {} },
      workflow_summary: { steps_count: 6, ai_steps: 1, credentials: [] },
      warnings: [],
      errors: [],
    })),
  },
}));

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

// REGRESSION FIXTURE — a faithful, trimmed copy of the structure of
// backend/saz/examples/unified/rfq_rfp_drafting.yaml. It is intentionally a
// frontend fixture (not an import of the backend file) so the test stays inside
// the frontend package, while exercising every important step type and the
// textarea/enum/boolean/email field shapes the real RFQ uses.
const RFQ_FIXTURE = `
schema_version: 1
flow:
  name: rfq_rfp_drafting
  description: Generate a formatted GÉANT RFQ document from structured intake.
form:
  fields:
    - name: project_name
      type: string
      required: true
    - name: scope_input
      type: text
      widget: textarea
      required: true
    - name: criticality
      type: string
      required: true
      enum: [low, medium, high]
    - name: estimated_value_eur
      type: number
      required: true
      minimum: 0
    - name: reference_number
      type: string
      required: true
    - name: contact_email
      type: string
      required: true
      format: email
    - name: consultation_required
      type: boolean
      required: true
      default: false
workflow:
  planner_mode: deterministic
  steps:
    - id: validate_inputs
      type: ai.extract
      description: Structure and validate the combined intake.
      instruction: Review the intake and return missing fields.
    - id: gate_budget
      type: condition
      if: "{{ $form.estimated_value_eur < 100000 }}"
    - id: procurement_review
      type: human.approval
      when: "{{ $step('gate_budget').result == true }}"
      params:
        title: "Review RFQ narrative: {{ $form.project_name }}"
        approvers:
          - "{{ $form.contact_email }}"
    - id: render_draft
      type: tool.call
      tool: docx_render
      when: "{{ $step('gate_budget').result == true }}"
      params:
        template: "{{ $env('SAZ_RFQ_TEMPLATE', 'saz/examples/templates/rfq_template.docx') }}"
        output_name: "rfq_draft_{{ $form.reference_number }}"
        require_all: false
        values:
          title_system_name: "{{ $form.project_name }}"
          version: "0.1 DRAFT"
          reference_number: "{{ $form.reference_number }}"
    - id: supplier_feedback
      type: webhook.wait
      when: "{{ $form.consultation_required == true }}"
      params:
        event_name: "rfq.supplier_feedback"
        timeout_minutes: 4320
    - id: audit_record
      type: artifact.store
      params:
        name: "rfq_audit_{{ $form.reference_number }}"
        content:
          reference_number: "{{ $form.reference_number }}"
`;

describe('RFQ/RFP regression — fixture → builder draft → valid YAML', () => {
  it('parses the fixture into a builder draft preserving field and step shapes', async () => {
    const result = await yamlToDraft(RFQ_FIXTURE);
    expect(result.ok).toBe(true);
    if (!result.ok) return;

    const fieldsByName = Object.fromEntries(
      (result.draft.form?.fields ?? []).map((f) => [f.name, f]),
    );
    // Long-text intake field round-trips its widget hint.
    expect(fieldsByName.scope_input.widget).toBe('textarea');
    expect(fieldsByName.criticality.enum).toEqual(['low', 'medium', 'high']);
    expect(fieldsByName.consultation_required.type).toBe('boolean');

    const ids = result.draft.workflow.steps.map((s) => s.id);
    expect(ids).toEqual([
      'validate_inputs',
      'gate_budget',
      'procurement_review',
      'render_draft',
      'supplier_feedback',
      'audit_record',
    ]);
  });

  it('shows the document-generation step as a friendly procurement business step', async () => {
    const result = await yamlToDraft(RFQ_FIXTURE);
    expect(result.ok).toBe(true);
    if (!result.ok) return;

    const renderStep = result.draft.workflow.steps.find((s) => s.id === 'render_draft')!;
    expect(classifyPattern(renderStep)).toBe('document_generation');
    const presentation = resolvePresentation(renderStep, procurementPack);
    expect(presentation.label).toMatch(/RFQ\/RFP/);
    expect(presentation.category).toBe('document');
  });

  it('regenerates valid YAML preserving the docx_render step and its when-guard', async () => {
    const result = await yamlToDraft(RFQ_FIXTURE);
    expect(result.ok).toBe(true);
    if (!result.ok) return;

    const yaml = draftToUnifiedYaml(result.draft);
    const reparsed = jsYaml.load(yaml) as any;
    const render = reparsed.workflow.steps.find((s: any) => s.id === 'render_draft');
    expect(render.type).toBe('tool.call');
    expect(render.tool).toBe('docx_render');
    expect(render.params.require_all).toBe(false);
    expect(render.params.values.title_system_name).toBe('{{ $form.project_name }}');
    // The when-guard (an "extra") survives the round-trip.
    expect(render.when).toBe("{{ $step('gate_budget').result == true }}");
  });

  it('renders the business view without a raw JSON editor for the document step', async () => {
    const result = await yamlToDraft(RFQ_FIXTURE);
    expect(result.ok).toBe(true);
    if (!result.ok) return;

    // This regression validates the procurement experience for an RFQ flow.
    setActiveDomainPack('procurement');
    render(wrapped(<WorkflowStepsSection draft={result.draft} onChange={() => {}} />));
    // The doc step appears with its friendly procurement label…
    expect(screen.getByText(/create draft.*document/i)).toBeInTheDocument();
    // …and no raw params JSON editor is shown by default.
    expect(screen.queryByLabelText(/render_draft-params/i)).not.toBeInTheDocument();
  });
});
