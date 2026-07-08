'use client';

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type { StepEditorProps } from '../step-editors/step-editor-shell';
import { StaticField } from '../step-editors/step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';
import { BindingPicker } from '../binding-picker';
import { MappingRows, readStringMap } from './mapping-rows';
import {
  bindingToExpression,
  expressionToBinding,
  type BindingContext,
  type FriendlyBinding,
} from '@/lib/flows/bindings';

function asParams(step: StepEditorProps['step']): Record<string, unknown> {
  return (step.params as Record<string, unknown>) ?? {};
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

/**
 * Friendly editor for "Review & approval" steps (human.approval).
 *
 * Exposes who reviews, the title and message they see, and what data they
 * review — all without raw approval payload JSON, which stays in the collapsed
 * advanced section. Compiles down to the existing human.approval params.
 */
export function ApprovalEditor({ step, draft, priorStepIds, onChange }: StepEditorProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const params = asParams(step);
  const approvers = asStringArray(params.approvers);
  const { supported: payloadSupported, values: payload } = readStringMap(params.payload);

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

  const setApprover = (index: number, binding: FriendlyBinding) => {
    const next = [...approvers];
    next[index] = bindingToExpression(binding);
    setParam('approvers', next);
  };
  const addApprover = () => setParam('approvers', [...approvers, '']);
  const removeApprover = (index: number) =>
    setParam(
      'approvers',
      approvers.filter((_, i) => i !== index),
    );

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-xs font-medium text-slate-600">Reviewers</label>
          <button
            type="button"
            onClick={addApprover}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 rounded"
          >
            <Plus className="h-3.5 w-3.5" />
            Add reviewer
          </button>
        </div>
        {approvers.length === 0 && (
          <p className="text-xs text-slate-500">No reviewers chosen yet.</p>
        )}
        <div className="space-y-2">
          {approvers.map((expr, i) => (
            <div key={i} className="flex items-start gap-2">
              <div className="flex-1">
                <BindingPicker
                  label={`reviewer ${i + 1}`}
                  binding={expr ? expressionToBinding(expr) : null}
                  context={context}
                  onChange={(b) => setApprover(i, b)}
                />
              </div>
              <button
                type="button"
                onClick={() => removeApprover(i)}
                className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                aria-label={`Remove reviewer ${i + 1}`}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      <StaticField
        label="Approval title"
        value={typeof params.title === 'string' ? params.title : ''}
        onChange={(next) => setParam('title', next || undefined)}
        placeholder="e.g. Review RFQ narrative"
      />

      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">
          Message to the reviewer
        </label>
        <textarea
          value={typeof params.message === 'string' ? params.message : ''}
          onChange={(e) => setParam('message', e.target.value || undefined)}
          rows={3}
          className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="What should the reviewer check?"
        />
      </div>

      <div>
        <h4 className="text-sm font-medium text-slate-800 mb-2">What the reviewer sees</h4>
        {payloadSupported ? (
          <MappingRows
            values={payload}
            context={context}
            onChange={(next) => setParam('payload', Object.keys(next).length ? next : undefined)}
            addLabel="Add item"
            namePlaceholder="Item name"
          />
        ) : (
          <JsonObjectEditor
            label="What the reviewer sees (raw)"
            value={params.payload}
            onChange={(next) => setParam('payload', next)}
            testId={`step-${step.id}-payload`}
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
              label="All approval params (raw)"
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
