'use client';

import { useState } from 'react';
import type { StepEditorProps } from '../step-editors/step-editor-shell';
import { StaticField } from '../step-editors/step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';
import { MappingRows, readStringMap } from './mapping-rows';
import { bindingContextFor } from '@/lib/flows/business-step-metadata';

function asParams(step: StepEditorProps['step']): Record<string, unknown> {
  return (step.params as Record<string, unknown>) ?? {};
}

/**
 * Friendly editor for "Save audit trail" steps (artifact.store).
 *
 * Exposes the record name and what to save (as binding chips). The raw
 * artifact content stays in the advanced section.
 */
export function AuditTrailEditor({ step, draft, priorStepIds, onChange }: StepEditorProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const params = asParams(step);
  const { supported: contentSupported, values: content } = readStringMap(params.content);

  const context = bindingContextFor(draft.form?.fields, priorStepIds, draft.workflow.steps);

  const setParam = (key: string, value: unknown) => {
    const next = { ...params };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange({ params: next });
  };

  return (
    <div className="space-y-4">
      <StaticField
        label="Record name"
        value={typeof params.name === 'string' ? params.name : ''}
        onChange={(next) => setParam('name', next || undefined)}
        placeholder="e.g. rfq_audit"
      />

      <div>
        <h4 className="text-sm font-medium text-slate-800 mb-2">What to save</h4>
        {contentSupported ? (
          <MappingRows
            values={content}
            context={context}
            onChange={(next) => setParam('content', Object.keys(next).length ? next : undefined)}
            addLabel="Add item to save"
            namePlaceholder="Record field name"
          />
        ) : (
          // Nested/non-string values can't be shown as binding chips without
          // data loss — edit them as raw JSON instead.
          <JsonObjectEditor
            label="What to save (raw)"
            value={params.content}
            onChange={(next) => setParam('content', next)}
            testId={`step-${step.id}-content`}
          />
        )}
      </div>

      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-xs text-slate-600 hover:text-slate-900"
        >
          {showAdvanced ? 'Hide advanced' : 'Advanced (technical settings)'}
        </button>
        {showAdvanced && (
          <div className="mt-2 border-t border-slate-200 pt-3">
            <JsonObjectEditor
              label="All audit params (raw)"
              value={step.params}
              onChange={(next) =>
                onChange({
                  params: next === undefined ? undefined : (next as Record<string, unknown>),
                })
              }
              testId={`step-${step.id}-params`}
            />
          </div>
        )}
      </div>
    </div>
  );
}
