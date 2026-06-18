'use client';

import type { WorkflowStepDraft } from '@/lib/flows/types';
import type { StepEditorProps } from '../step-editors/step-editor-shell';
import { classifyPattern } from '@/lib/flows/business-step-metadata';
import type { BusinessStepPattern } from '@/lib/flows/domain-packs/types';
import { DocumentGenerationEditor } from './document-generation-editor';
import { ApprovalEditor } from './approval-editor';
import { WaitForFeedbackEditor } from './wait-for-feedback-editor';
import { AuditTrailEditor } from './audit-trail-editor';
import { RuleCheckEditor } from './rule-check-editor';

type EditorComponent = (props: StepEditorProps) => React.ReactNode;

/**
 * Friendly editors keyed by generic business pattern. A pattern with no entry
 * falls back to the generic technical editor (clearly marked as an expert
 * step). These editors are pattern-generic; domain wording comes from the pack.
 */
const FRIENDLY_EDITORS: Partial<Record<BusinessStepPattern, EditorComponent>> = {
  document_generation: DocumentGenerationEditor,
  approval: ApprovalEditor,
  wait_for_response: WaitForFeedbackEditor,
  audit_trail: AuditTrailEditor,
  rule_check: RuleCheckEditor,
};

/** Returns the friendly editor for a step, or null when none applies. */
export function pickFriendlyEditor(step: WorkflowStepDraft): EditorComponent | null {
  return FRIENDLY_EDITORS[classifyPattern(step)] ?? null;
}

export {
  DocumentGenerationEditor,
  ApprovalEditor,
  WaitForFeedbackEditor,
  AuditTrailEditor,
  RuleCheckEditor,
};
