'use client';

import { useState } from 'react';
import type { StepEditorProps } from '../step-editors/step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';

function asParams(step: StepEditorProps['step']): Record<string, unknown> {
  return (step.params as Record<string, unknown>) ?? {};
}

/**
 * Friendly editor for "Wait for a response" steps (webhook.wait).
 *
 * Exposes what response the run is waiting for and how long to wait. The raw
 * event name and other webhook internals live in the advanced section.
 */
export function WaitForFeedbackEditor({ step, onChange }: StepEditorProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const params = asParams(step);

  const setParam = (key: string, value: unknown) => {
    const next = { ...params };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange({ params: next });
  };

  const timeout = typeof params.timeout_minutes === 'number' ? params.timeout_minutes : undefined;

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">
          What response are you waiting for?
        </label>
        <input
          type="text"
          aria-label="Expected response name"
          value={typeof params.event_name === 'string' ? params.event_name : ''}
          onChange={(e) => setParam('event_name', e.target.value || undefined)}
          className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="e.g. supplier feedback"
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">
          How long to wait (minutes)
        </label>
        <input
          type="number"
          min={1}
          aria-label="Wait timeout in minutes"
          value={timeout ?? ''}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === '') return setParam('timeout_minutes', undefined);
            const parsed = parseInt(raw, 10);
            setParam('timeout_minutes', Number.isNaN(parsed) ? undefined : parsed);
          }}
          className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="e.g. 4320"
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
              label="All wait params (raw)"
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
