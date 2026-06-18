'use client';

import { useState } from 'react';
import type { StepEditorProps } from '../step-editors/step-editor-shell';
import { StaticField } from '../step-editors/step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';
import { MappingRows } from './mapping-rows';
import type { BindingContext } from '@/lib/flows/bindings';

function asParams(step: StepEditorProps['step']): Record<string, unknown> {
  return (step.params as Record<string, unknown>) ?? {};
}

function asValues(value: unknown): Record<string, string> {
  if (!value || typeof value !== 'object') return {};
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    out[k] = typeof v === 'string' ? v : '';
  }
  return out;
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
  const content = asValues(params.content);

  const context: BindingContext = {
    formFields: draft.form?.fields ?? [],
    steps: priorStepIds.map((id) => ({
      id,
      name: draft.workflow.steps.find((s) => s.id === id)?.name,
    })),
  };

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
        <MappingRows
          values={content}
          context={context}
          onChange={(next) => setParam('content', Object.keys(next).length ? next : undefined)}
          addLabel="Add item to save"
          namePlaceholder="Record field name"
        />
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
