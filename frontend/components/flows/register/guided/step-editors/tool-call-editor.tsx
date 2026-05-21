'use client';

import { useDslMetadata } from '@/lib/hooks';
import type { StepEditorProps } from './step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';

export function ToolCallEditor({ step, onChange }: StepEditorProps) {
  const { data: metadata } = useDslMetadata();
  const tools = metadata?.tools ?? [];

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">Tool</label>
        <input
          list={`tools-${step.id}`}
          type="text"
          value={step.tool || ''}
          onChange={(e) => onChange({ tool: e.target.value || undefined })}
          className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="e.g., http_request"
        />
        <datalist id={`tools-${step.id}`}>
          {tools.map((t) => (
            <option key={t.name} value={t.name}>
              {t.description}
            </option>
          ))}
        </datalist>
      </div>

      <JsonObjectEditor
        label="Params"
        value={step.params}
        onChange={(next) =>
          onChange({
            params: next === undefined ? undefined : (next as Record<string, unknown>),
          })
        }
        placeholder='{ "url": "https://...", "method": "GET" }'
        testId={`step-${step.id}-params`}
      />

      <JsonObjectEditor
        label="Expected output schema (optional)"
        value={step.expect}
        onChange={(next) => onChange({ expect: next })}
        placeholder='{ "type": "object" }'
        testId={`step-${step.id}-expect`}
      />
    </div>
  );
}
