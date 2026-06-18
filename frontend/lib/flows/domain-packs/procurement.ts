// Procurement domain pack — the first domain pack for the Business Builder.
//
// It maps the generic business patterns onto procurement (RFQ/RFP) language.
// Nothing here is referenced by the generic core directly; the registry exposes
// it and generic components resolve it through business-step-metadata.

import type { WorkflowStepDraft } from '../types';
import type { DomainPack } from './types';

const STANDARD_RFQ_TEMPLATE =
  "{{ $env('SAZ_RFQ_TEMPLATE', 'saz/examples/templates/rfq_template.docx') }}";

function documentPurpose(step: WorkflowStepDraft): 'draft' | 'final' {
  const params = (step.params ?? {}) as Record<string, unknown>;
  if (params.require_all === true) return 'final';
  if (typeof params.output_name === 'string' && params.output_name.includes('final')) {
    return 'final';
  }
  return 'draft';
}

export const procurementPack: DomainPack = {
  id: 'procurement',
  label: 'Procurement (RFQ/RFP)',
  templatePresets: [{ label: 'Standard RFQ template', value: STANDARD_RFQ_TEMPLATE }],
  stepOverrides: {
    intake_form: {
      friendlyLabel: 'Collect RFQ/RFP request information',
      description: 'Gather the project and procurement intake details.',
    },
    rule_check: {
      friendlyLabel: 'Check procurement requirements',
      description: 'Check the request against procurement rules (budget, PONT, weights).',
    },
    approval: {
      friendlyLabel: 'Procurement review',
      description: 'Ask procurement to review before continuing.',
    },
    document_generation: {
      friendlyLabel: 'Create RFQ/RFP document',
      description: 'Generate the RFQ/RFP document from the procurement template.',
      labelFor: (step) => `Create ${documentPurpose(step)} RFQ/RFP document`,
      fieldLabels: {
        'params.output_name': 'RFQ/RFP file name',
        'params.template': 'RFQ/RFP template',
      },
    },
    wait_for_response: {
      friendlyLabel: 'Wait for supplier feedback',
      description: 'Pause for supplier market-consultation feedback.',
    },
    audit_trail: {
      friendlyLabel: 'Save procurement audit trail',
      description: 'Store the full RFQ/RFP audit record.',
    },
  },
};
