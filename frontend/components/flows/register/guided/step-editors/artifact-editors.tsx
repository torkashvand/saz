'use client';

import type { StepEditorProps } from './step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';

export function ArtifactStoreEditor({ step, onChange }: StepEditorProps) {
  return (
    <JsonObjectEditor
      label="Params (name, content_type, content, ...)"
      value={step.params}
      onChange={(next) =>
        onChange({
          params: next === undefined ? undefined : (next as Record<string, unknown>),
        })
      }
      placeholder='{ "name": "audit_record", "content_type": "json", "content": { } }'
      testId={`step-${step.id}-params`}
    />
  );
}

export function ArtifactRetrieveEditor({ step, onChange }: StepEditorProps) {
  return (
    <JsonObjectEditor
      label="Params (name or selector)"
      value={step.params}
      onChange={(next) =>
        onChange({
          params: next === undefined ? undefined : (next as Record<string, unknown>),
        })
      }
      placeholder='{ "name": "audit_record" }'
      testId={`step-${step.id}-params`}
    />
  );
}
