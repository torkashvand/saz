import { describe, it, expect } from 'vitest';
import {
  classifyPattern,
  resolveStepMetadata,
  resolvePresentation,
  computeStepStatus,
  createBusinessStep,
  addStepMenu,
  getFieldLabel,
  getFieldOptions,
} from '@/lib/flows/business-step-metadata';
import { GENERIC_PACK } from '@/lib/flows/domain-packs/registry';
import { procurementPack } from '@/lib/flows/domain-packs/procurement';
import type { WorkflowStepDraft } from '@/lib/flows/types';

function step(o: Partial<WorkflowStepDraft>): WorkflowStepDraft {
  return { id: 's1', type: 'ai.extract', ...o };
}

describe('classifyPattern (generic core)', () => {
  it('maps step shapes to generic business patterns', () => {
    expect(classifyPattern(step({ type: 'tool.call', tool: 'docx_render' }))).toBe(
      'document_generation',
    );
    expect(classifyPattern(step({ type: 'human.approval' }))).toBe('approval');
    expect(classifyPattern(step({ type: 'webhook.wait' }))).toBe('wait_for_response');
    expect(classifyPattern(step({ type: 'artifact.store' }))).toBe('audit_trail');
    expect(classifyPattern(step({ type: 'condition' }))).toBe('rule_check');
    expect(classifyPattern(step({ type: 'ai.extract' }))).toBe('technical');
  });
});

describe('domain-pack label resolution', () => {
  const docStep = step({ type: 'tool.call', tool: 'docx_render', params: { require_all: false } });

  it('uses generic labels with no domain pack', () => {
    const p = resolvePresentation(docStep, GENERIC_PACK);
    expect(p.label).toMatch(/document/i);
    expect(p.label).not.toMatch(/RFQ/i);
  });

  it('lets the procurement pack override the label for the same pattern', () => {
    const p = resolvePresentation(docStep, procurementPack);
    expect(p.label).toMatch(/RFQ\/RFP/);
    expect(p.label).toMatch(/draft/i);
  });

  it('overrides field labels per pack while generic stays generic', () => {
    const generic = getFieldLabel('document_generation', 'params.output_name', GENERIC_PACK);
    const proc = getFieldLabel('document_generation', 'params.output_name', procurementPack);
    expect(generic).toBeTruthy();
    expect(proc).not.toBe(generic);
  });
});

describe('resolveStepMetadata exposes declarative field metadata', () => {
  it('returns groups with fields, controls, labels and defaults', () => {
    const md = resolveStepMetadata('document_generation', GENERIC_PACK);
    expect(md.pattern).toBe('document_generation');
    expect(md.groups && md.groups.length).toBeGreaterThan(0);
    const allFields = (md.groups ?? []).flatMap((g) => g.fields);
    const purpose = allFields.find((f) => f.path === 'params.require_all');
    expect(purpose?.control).toBeTruthy();
    expect(purpose?.label).toBeTruthy();
  });

  it('resolves select options declaratively from metadata', () => {
    const options = getFieldOptions('document_generation', 'params.require_all');
    expect(options.map((o) => o.value)).toEqual(['draft', 'final']);
    expect(getFieldOptions('document_generation', 'params.output_name')).toEqual([]);
  });
});

describe('computeStepStatus', () => {
  it('flags a document step with no mappings as missing mappings', () => {
    const s = step({ type: 'tool.call', tool: 'docx_render', params: { values: {} } });
    expect(computeStepStatus(s).kind).toBe('missing_mappings');
  });

  it('flags an approval step with no reviewer', () => {
    expect(computeStepStatus(step({ type: 'human.approval', params: {} })).kind).toBe(
      'reviewer_missing',
    );
  });

  it('marks a ready document step', () => {
    const s = step({
      type: 'tool.call',
      tool: 'docx_render',
      description: 'Render the draft document',
      params: { template: 't', values: { a: '{{ $form.x }}' } },
    });
    expect(computeStepStatus(s).kind).toBe('ready');
  });

  it('does not mark a step Ready when the compile-required description is missing', () => {
    const s = step({
      type: 'tool.call',
      tool: 'docx_render',
      params: { template: 't', values: { a: '{{ $form.x }}' } },
    });
    expect(computeStepStatus(s).kind).toBe('needs_setup');
  });

  it('marks non-AI technical steps as advanced', () => {
    expect(computeStepStatus(step({ type: 'artifact.retrieve' })).kind).toBe('advanced');
  });

  it('marks an AI step ready once it has an instruction, else needs setup', () => {
    expect(computeStepStatus(step({ type: 'ai.extract' })).kind).toBe('needs_setup');
    expect(
      computeStepStatus(step({ type: 'ai.extract', instruction: 'Extract fields' })).kind,
    ).toBe('ready');
  });
});

describe('resolvePresentation summary + reviewer', () => {
  it('summarises a document step by mapping count', () => {
    const s = step({
      type: 'tool.call',
      tool: 'docx_render',
      params: { values: { a: '{{ $form.x }}', b: '0.1 DRAFT' } },
    });
    expect(resolvePresentation(s, GENERIC_PACK).summary).toMatch(/2/);
  });

  it('presents an AI step with a friendly label, icon, category and summary', () => {
    const p = resolvePresentation(step({ type: 'ai.extract' }), GENERIC_PACK);
    expect(p.label).toBe('AI Extract');
    expect(p.icon).toBe('🤖');
    expect(p.category).toBe('AI');
    expect(p.summary).not.toMatch(/expert/i);
  });

  it('falls back to the step description for non-document steps', () => {
    const s = step({ type: 'human.approval', description: 'Procurement reviews the draft.' });
    expect(resolvePresentation(s, GENERIC_PACK).summary).toContain(
      'Procurement reviews the draft.',
    );
  });

  it('exposes the reviewer for an approval step', () => {
    const s = step({
      type: 'human.approval',
      params: { approvers: ['{{ $form.contact_email }}'] },
    });
    const p = resolvePresentation(s, GENERIC_PACK, {
      formFields: [{ name: 'contact_email', type: 'string', title: 'Contact email' }],
    });
    expect(p.reviewer).toMatch(/contact email/i);
  });
});

describe('createBusinessStep + addStepMenu consume the pack', () => {
  it('seeds a document step with the active pack template preset', () => {
    const s = createBusinessStep('document_generation', [], procurementPack);
    expect(classifyPattern(s)).toBe('document_generation');
    expect((s.params as any).template).toBe(procurementPack.templatePresets?.[0].value);
  });

  it('offers a business group with pack-resolved labels', () => {
    const generic = addStepMenu(GENERIC_PACK)[0].options.map((o) => o.label);
    const proc = addStepMenu(procurementPack)[0].options.map((o) => o.label);
    expect(generic.some((l) => /RFQ/i.test(l))).toBe(false);
    expect(proc.some((l) => /RFQ/i.test(l))).toBe(true);
  });
});
