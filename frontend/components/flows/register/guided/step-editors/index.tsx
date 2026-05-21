'use client';

import type { StepType } from '@/lib/flows/types';
import { AI_STEP_TYPES } from '@/lib/flows/types';
import type { StepEditorProps } from './step-editor-shell';
import { AiStepEditor } from './ai-step-editor';
import { ToolCallEditor } from './tool-call-editor';
import { ConditionEditor } from './condition-editor';
import { HumanApprovalEditor } from './human-approval-editor';
import { WebhookWaitEditor } from './webhook-wait-editor';
import { ArtifactStoreEditor, ArtifactRetrieveEditor } from './artifact-editors';

type EditorComponent = (props: StepEditorProps) => React.ReactNode;

const REGISTRY: Partial<Record<StepType, EditorComponent>> = {
  'tool.call': ToolCallEditor,
  condition: ConditionEditor,
  'human.approval': HumanApprovalEditor,
  'webhook.wait': WebhookWaitEditor,
  'artifact.store': ArtifactStoreEditor,
  'artifact.retrieve': ArtifactRetrieveEditor,
};

export function pickStepEditor(type: StepType): EditorComponent {
  if (AI_STEP_TYPES.has(type)) return AiStepEditor;
  return REGISTRY[type] ?? AiStepEditor;
}

export type { StepEditorProps };
export { AiStepEditor };
