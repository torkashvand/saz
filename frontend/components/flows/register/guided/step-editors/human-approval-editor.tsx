'use client';

import type { StepEditorProps } from './step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';

export function HumanApprovalEditor({ step, onChange }: StepEditorProps) {
  return (
    <div className="space-y-3">
      <JsonObjectEditor
        label="Approval payload (params)"
        value={step.params}
        onChange={(next) =>
          onChange({
            params: next === undefined ? undefined : (next as Record<string, unknown>),
          })
        }
        placeholder='{ "title": "Approve change", "approvers": ["sre"] }'
        testId={`step-${step.id}-params`}
      />
      <JsonObjectEditor
        label="Expected approval result (optional)"
        value={step.expect}
        onChange={(next) => onChange({ expect: next })}
        placeholder='{ "type": "object", "properties": { "approved": { "type": "boolean" } } }'
        testId={`step-${step.id}-expect`}
      />
    </div>
  );
}
