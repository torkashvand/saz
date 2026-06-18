// Generic domain-pack model.
//
// Saz is a generic workflow framework. The Business Builder presents workflow
// steps as a small set of generic *business patterns*. A DomainPack maps those
// generic patterns onto a specific domain's language (procurement, HR, IT…)
// without the generic layer hardcoding any domain. Generic components consume
// pack metadata through the resolvers in business-step-metadata.ts.

import type { WorkflowStepDraft } from '../types';

export type BusinessStepPattern =
  | 'intake_form'
  | 'rule_check'
  | 'approval'
  | 'document_generation'
  | 'wait_for_response'
  | 'audit_trail'
  | 'technical';

export type BusinessControl =
  | 'text'
  | 'textarea'
  | 'select'
  | 'number'
  | 'boolean'
  | 'date'
  | 'binding'
  | 'binding-list'
  | 'reviewer-picker'
  | 'template-picker';

export interface BusinessFieldMetadata {
  /** Dot path into the step, e.g. "params.output_name". */
  path: string;
  label: string;
  description?: string;
  control: BusinessControl;
  required?: boolean;
  defaultValue?: unknown;
  /** Hidden behind the advanced/expert disclosure. */
  advanced?: boolean;
  /** Never shown in the friendly UI. */
  hidden?: boolean;
  validationMessage?: string;
  options?: Array<{ label: string; value: string }>;
}

export interface BusinessFieldGroup {
  id: string;
  label: string;
  description?: string;
  fields: BusinessFieldMetadata[];
}

export interface BusinessStepPreset {
  id: string;
  label: string;
  description?: string;
  /** Partial step merged onto the seed when the preset is chosen. */
  patch: Partial<WorkflowStepDraft>;
}

export interface BusinessStepMetadata {
  pattern: BusinessStepPattern;
  friendlyLabel: string;
  description: string;
  /** Short display word for the category chip. */
  category: string;
  icon: string;
  groups?: BusinessFieldGroup[];
  presets?: BusinessStepPreset[];
}

export type StepStatusKind =
  | 'ready'
  | 'needs_setup'
  | 'missing_mappings'
  | 'reviewer_missing'
  | 'advanced';

export interface StepStatus {
  kind: StepStatusKind;
  label: string;
}

export interface StepPresentationMetadata {
  pattern: BusinessStepPattern;
  label: string;
  icon: string;
  category: string;
  summary: string;
  status: StepStatus;
  reviewer?: string;
  conditionSummary?: string;
}

/** Per-pattern overrides a domain pack can apply to the generic metadata. */
export interface DomainStepOverride {
  friendlyLabel?: string;
  description?: string;
  icon?: string;
  /** Resolve a label for a specific step instance (e.g. draft vs final). */
  labelFor?: (step: WorkflowStepDraft) => string | undefined;
  /** Override field labels by path. */
  fieldLabels?: Record<string, string>;
  presets?: BusinessStepPreset[];
}

export interface DomainPack {
  id: string;
  label: string;
  stepOverrides: Partial<Record<BusinessStepPattern, DomainStepOverride>>;
  /** Document templates this domain offers (template-picker control). */
  templatePresets?: ReadonlyArray<{ label: string; value: string }>;
}

import type { BindingContext } from '../bindings';

export interface BusinessStepEditorContext {
  draft: import('../types').FlowDraft;
  priorStepIds: string[];
  bindingContext: BindingContext;
  pack: DomainPack;
}
