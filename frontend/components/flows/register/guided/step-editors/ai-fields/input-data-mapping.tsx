'use client';

import type { StepEditorProps } from '../step-editor-shell';
import { MappingRows } from '../../business-step-editors/mapping-rows';
import { JsonObjectEditor } from '../../json-object-editor';
import { readInputData, writeInputData } from '@/lib/flows/ai-input-data';
import { bindingContextFor } from '@/lib/flows/business-step-metadata';

/**
 * Friendly editor for an AI step's `params.data` — a flat map of input field
 * -> binding. Reuses MappingRows + BindingPicker so a user never types a
 * template expression. Falls back to a raw JSON editor (with a warning) when
 * the params are not a flat all-string `{ data: {...} }` map.
 */
export function InputDataMapping({ step, draft, priorStepIds, onChange }: StepEditorProps) {
  const params = (step.params as Record<string, unknown>) ?? undefined;
  const { supported, values } = readInputData(params);

  const context = bindingContextFor(draft.form?.fields, priorStepIds, draft.workflow.steps);

  if (!supported) {
    return (
      <div className="space-y-2">
        <label className="block text-xs font-medium text-slate-600">Input data</label>
        <div className="px-3 py-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-700">
          This step&apos;s input data can&apos;t be shown in the visual editor. Edit the raw value
          below — it is kept exactly as-is.
        </div>
        <JsonObjectEditor
          label="Input data (params.data) — raw"
          value={step.params}
          onChange={(next) =>
            onChange({
              params: next === undefined ? undefined : (next as Record<string, unknown>),
            })
          }
          testId={`step-${step.id}-params`}
        />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-slate-600">Input data</label>
      <MappingRows
        values={values}
        context={context}
        onChange={(next) => onChange({ params: writeInputData(params, next) })}
        addLabel="Add input field"
        namePlaceholder="Input field name"
      />
    </div>
  );
}
