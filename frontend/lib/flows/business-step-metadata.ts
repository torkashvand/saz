// Generic Business Builder presentation/metadata layer.
//
// This maps the technical Saz step model (type/tool/params) onto generic
// business patterns and resolves how a step is presented and edited. It holds
// NO domain-specific labels — those come from the active DomainPack. Generic
// components call these resolvers; the domain pack only supplies overrides.

import type { FlowFormField, WorkflowStepDraft } from './types';
import { AI_STEP_TYPES, STEP_TYPES, type StepType } from './types';
import type { BindingContext } from './bindings';
import { expressionToBinding, renderBindingLabel } from './bindings';
import type {
  BusinessStepMetadata,
  BusinessStepPattern,
  DomainPack,
  StepPresentationMetadata,
  StepStatus,
} from './domain-packs/types';

/** Tools the document-generation editor understands (generic, not domain). */
export const DOCUMENT_TOOLS: ReadonlySet<string> = new Set(['docx_render']);

/** Generic metadata for each business pattern. No domain words here. */
export const GENERIC_STEP_METADATA: Record<BusinessStepPattern, BusinessStepMetadata> = {
  intake_form: {
    pattern: 'intake_form',
    friendlyLabel: 'Collect information',
    description: 'Gather details from the requester.',
    category: 'intake',
    icon: '📝',
  },
  rule_check: {
    pattern: 'rule_check',
    friendlyLabel: 'Rule check',
    description: 'Check the request against a business rule.',
    category: 'check',
    icon: '✔️',
  },
  approval: {
    pattern: 'approval',
    friendlyLabel: 'Review & approval',
    description: 'Ask a person to review before continuing.',
    category: 'approval',
    icon: '👤',
  },
  document_generation: {
    pattern: 'document_generation',
    friendlyLabel: 'Create document',
    description: 'Generate a document from a template.',
    category: 'document',
    icon: '📄',
    groups: [
      {
        id: 'document',
        label: 'Document',
        fields: [
          {
            path: 'params.require_all',
            label: 'Document purpose',
            control: 'select',
            defaultValue: false,
            options: [
              { label: 'Draft (allow missing fields)', value: 'draft' },
              { label: 'Final (all fields required)', value: 'final' },
            ],
          },
          { path: 'params.template', label: 'Template', control: 'template-picker' },
          { path: 'params.output_name', label: 'Output file name', control: 'text' },
        ],
      },
    ],
  },
  wait_for_response: {
    pattern: 'wait_for_response',
    friendlyLabel: 'Wait for a response',
    description: 'Pause until feedback arrives.',
    category: 'wait',
    icon: '⏳',
  },
  audit_trail: {
    pattern: 'audit_trail',
    friendlyLabel: 'Save audit trail',
    description: 'Store a record of what happened.',
    category: 'audit',
    icon: '🗂️',
  },
  technical: {
    pattern: 'technical',
    friendlyLabel: 'Technical step',
    description: 'An advanced step configured by an expert.',
    category: 'technical',
    icon: '⚙️',
  },
};

/** AI-op steps now have a friendly editor, so they get a friendly card
 * presentation (AI label/icon/summary) instead of the opaque-technical chrome,
 * even though they still classify as the `technical` pattern. */
function isAiStep(step: WorkflowStepDraft): boolean {
  return AI_STEP_TYPES.has(step.type);
}

function aiStepLabel(step: WorkflowStepDraft): string {
  return STEP_TYPES.find((t) => t.value === step.type)?.label ?? 'AI step';
}

export function classifyPattern(step: WorkflowStepDraft): BusinessStepPattern {
  if (step.type === 'tool.call' && step.tool && DOCUMENT_TOOLS.has(step.tool)) {
    return 'document_generation';
  }
  switch (step.type) {
    case 'human.approval':
      return 'approval';
    case 'webhook.wait':
      return 'wait_for_response';
    case 'artifact.store':
      return 'audit_trail';
    case 'condition':
      return 'rule_check';
    default:
      return 'technical';
  }
}

/** Merge generic metadata with a domain pack's overrides for one pattern. */
export function resolveStepMetadata(
  pattern: BusinessStepPattern,
  pack: DomainPack,
): BusinessStepMetadata {
  const base = GENERIC_STEP_METADATA[pattern];
  const override = pack.stepOverrides[pattern];
  if (!override) return base;
  return {
    ...base,
    friendlyLabel: override.friendlyLabel ?? base.friendlyLabel,
    description: override.description ?? base.description,
    icon: override.icon ?? base.icon,
  };
}

function findField(pattern: BusinessStepPattern, path: string) {
  return (GENERIC_STEP_METADATA[pattern].groups ?? [])
    .flatMap((g) => g.fields)
    .find((f) => f.path === path);
}

/** Resolve a field's label, allowing the pack to override it by path. */
export function getFieldLabel(
  pattern: BusinessStepPattern,
  path: string,
  pack: DomainPack,
): string {
  const override = pack.stepOverrides[pattern]?.fieldLabels?.[path];
  if (override) return override;
  return findField(pattern, path)?.label ?? path;
}

/** Resolve a field's select options from metadata (empty when not a choice). */
export function getFieldOptions(
  pattern: BusinessStepPattern,
  path: string,
): Array<{ label: string; value: string }> {
  return findField(pattern, path)?.options ?? [];
}

function paramsOf(step: WorkflowStepDraft): Record<string, unknown> {
  return (step.params as Record<string, unknown>) ?? {};
}

function mappingValues(step: WorkflowStepDraft, key: string): Record<string, unknown> {
  const raw = paramsOf(step)[key];
  return raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
}

const STATUS_LABELS: Record<StepStatus['kind'], string> = {
  ready: 'Ready',
  needs_setup: 'Needs setup',
  missing_mappings: 'Missing mappings',
  reviewer_missing: 'Reviewer missing',
  advanced: 'Advanced step',
};

function status(kind: StepStatus['kind']): StepStatus {
  return { kind, label: STATUS_LABELS[kind] };
}

export function computeStepStatus(step: WorkflowStepDraft): StepStatus {
  if (isAiStep(step)) {
    const ready = !!step.instruction && step.instruction.trim().length > 0;
    return status(ready ? 'ready' : 'needs_setup');
  }
  const pattern = classifyPattern(step);
  const params = paramsOf(step);
  switch (pattern) {
    case 'document_generation': {
      const values = mappingValues(step, 'values');
      const entries = Object.entries(values);
      if (entries.length === 0 || entries.some(([, v]) => !v || v === '')) {
        return status('missing_mappings');
      }
      if (!params.template) return status('needs_setup');
      return status('ready');
    }
    case 'approval': {
      const approvers = Array.isArray(params.approvers) ? params.approvers : [];
      if (approvers.filter((a) => typeof a === 'string' && a.trim()).length === 0) {
        return status('reviewer_missing');
      }
      return status('ready');
    }
    case 'wait_for_response':
      return params.event_name ? status('ready') : status('needs_setup');
    case 'audit_trail':
      return Object.keys(mappingValues(step, 'content')).length > 0
        ? status('ready')
        : status('needs_setup');
    case 'rule_check':
      return step.if && step.if.trim() ? status('ready') : status('needs_setup');
    case 'intake_form':
      return status('ready');
    default:
      return status('advanced');
  }
}

/** For approval steps, a readable label for the first reviewer, if set. */
export function stepReviewer(step: WorkflowStepDraft, context: BindingContext): string | undefined {
  if (classifyPattern(step) !== 'approval') return undefined;
  const approvers = paramsOf(step).approvers;
  const first = Array.isArray(approvers)
    ? approvers.find((a) => typeof a === 'string' && a.trim())
    : undefined;
  if (typeof first !== 'string') return undefined;
  const binding = expressionToBinding(first);
  return binding ? renderBindingLabel(binding, context) : first;
}

export function conditionSummary(step: WorkflowStepDraft): string | undefined {
  const when = (step.extras as Record<string, unknown> | undefined)?.when;
  if (typeof when === 'string' && when.trim()) return 'Runs only when an earlier condition is met.';
  if (step.if && step.if.trim() && classifyPattern(step) === 'rule_check') {
    return 'Branches on a business rule.';
  }
  return undefined;
}

function firstLine(text: string): string {
  const t = text.trim();
  const i = t.indexOf('\n');
  return i === -1 ? t : t.slice(0, i);
}

function defaultSummary(step: WorkflowStepDraft, pattern: BusinessStepPattern): string {
  if (pattern === 'document_generation') {
    const count = Object.keys(mappingValues(step, 'values')).length;
    return `Generates a document using ${count} ${count === 1 ? 'field mapping' : 'field mappings'}.`;
  }
  if (step.description) return firstLine(step.description);
  if (isAiStep(step)) return 'Uses AI to produce the expected output from the input data.';
  return GENERIC_STEP_METADATA[pattern].description;
}

export function resolveStepLabel(step: WorkflowStepDraft, pack: DomainPack): string {
  const pattern = classifyPattern(step);
  const override = pack.stepOverrides[pattern];
  const fromPack = override?.labelFor?.(step);
  if (fromPack) return fromPack;
  if (isAiStep(step)) return aiStepLabel(step);
  return resolveStepMetadata(pattern, pack).friendlyLabel;
}

export function resolvePresentation(
  step: WorkflowStepDraft,
  pack: DomainPack,
  context: BindingContext = {},
): StepPresentationMetadata {
  const pattern = classifyPattern(step);
  const md = resolveStepMetadata(pattern, pack);
  const ai = isAiStep(step);
  return {
    pattern,
    label: resolveStepLabel(step, pack),
    icon: ai ? '🤖' : md.icon,
    category: ai ? 'AI' : md.category,
    summary: defaultSummary(step, pattern),
    status: computeStepStatus(step),
    reviewer: stepReviewer(step, context),
    conditionSummary: conditionSummary(step),
  };
}

// ---- Step creation -------------------------------------------------------

/** Patterns offered by the "Add step" picker, in display order. */
const PICKER_PATTERNS: BusinessStepPattern[] = [
  'document_generation',
  'approval',
  'wait_for_response',
  'rule_check',
  'audit_trail',
];

const STEP_ID_BASE: Record<BusinessStepPattern, string> = {
  document_generation: 'create_document',
  approval: 'review',
  wait_for_response: 'wait_for_response',
  audit_trail: 'audit_trail',
  rule_check: 'rule_check',
  intake_form: 'intake',
  technical: 'step',
};

function uniqueId(base: string, existingIds: string[]): string {
  if (!existingIds.includes(base)) return base;
  let n = 2;
  while (existingIds.includes(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}

export function createBusinessStep(
  pattern: BusinessStepPattern,
  existingIds: string[] = [],
  pack: DomainPack,
): WorkflowStepDraft {
  const id = uniqueId(STEP_ID_BASE[pattern] ?? 'step', existingIds);
  let seed: WorkflowStepDraft;
  switch (pattern) {
    case 'document_generation':
      seed = {
        id,
        type: 'tool.call',
        tool: 'docx_render',
        params: {
          template: pack.templatePresets?.[0]?.value ?? '',
          require_all: false,
          values: {},
        },
      };
      break;
    case 'approval':
      seed = { id, type: 'human.approval', params: {} };
      break;
    case 'wait_for_response':
      seed = { id, type: 'webhook.wait', params: {} };
      break;
    case 'audit_trail':
      seed = { id, type: 'artifact.store', params: {} };
      break;
    case 'rule_check':
      seed = { id, type: 'condition' };
      break;
    default:
      seed = { id, type: 'ai.extract' };
  }
  return seed;
}

/** Seed a step of a concrete technical type (used by the Advanced menu group). */
export function createTechnicalStep(type: StepType, existingIds: string[] = []): WorkflowStepDraft {
  const base = type.split('.').pop() || 'step';
  const id = uniqueId(base, existingIds);
  // Step types with a params object get an empty one so their editors mount
  // cleanly; AI ops and conditions start bare.
  const withParams: ReadonlySet<StepType> = new Set([
    'tool.call',
    'human.approval',
    'webhook.wait',
    'artifact.store',
    'artifact.retrieve',
  ]);
  return withParams.has(type) ? { id, type, params: {} } : { id, type };
}

export interface AddStepOption {
  /** Stable key for React lists. */
  key: string;
  label: string;
  /** Set for a friendly business pattern. */
  pattern?: BusinessStepPattern;
  /** Set for a concrete technical step type (Advanced group). */
  stepType?: StepType;
}

export interface AddStepGroup {
  label: string;
  options: AddStepOption[];
}

/**
 * The grouped "Add step" menu for business mode: friendly business patterns on
 * top, then an Advanced group exposing every concrete step type by category so
 * no action requires switching to expert mode to be added.
 */
export function addStepMenu(pack: DomainPack): AddStepGroup[] {
  const business: AddStepOption[] = PICKER_PATTERNS.map((pattern) => ({
    key: `pattern:${pattern}`,
    label: resolveStepMetadata(pattern, pack).friendlyLabel,
    pattern,
  }));
  const advanced: AddStepOption[] = STEP_TYPES.map((t) => ({
    key: `type:${t.value}`,
    label: `${t.category} · ${t.label}`,
    stepType: t.value,
  }));
  return [
    { label: 'Business', options: business },
    { label: 'Advanced', options: advanced },
  ];
}

/** Build a BindingContext for a step from the form fields + prior steps. */
export function bindingContextFor(
  formFields: FlowFormField[] | undefined,
  priorStepIds: string[],
  allSteps: WorkflowStepDraft[],
): BindingContext {
  return {
    formFields: formFields ?? [],
    steps: priorStepIds.map((sid) => ({
      id: sid,
      name: allSteps.find((s) => s.id === sid)?.name,
    })),
  };
}
