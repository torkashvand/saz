'use client';

import type { StepEditorProps } from './step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';

export function WebhookWaitEditor({ step, onChange }: StepEditorProps) {
  const params = step.params ?? {};
  const eventName = typeof params.event_name === 'string' ? params.event_name : '';

  const setEventName = (value: string) => {
    const next = { ...params };
    if (value === '') {
      delete next.event_name;
    } else {
      next.event_name = value;
    }
    onChange({ params: Object.keys(next).length > 0 ? next : undefined });
  };

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">
          Event name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={eventName}
          onChange={(e) => setEventName(e.target.value)}
          className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="approval_received"
        />
      </div>

      <JsonObjectEditor
        label="Additional params"
        value={otherParams(params)}
        onChange={(next) => {
          const merged: Record<string, unknown> = {
            ...(eventName ? { event_name: eventName } : {}),
            ...(next as Record<string, unknown> | undefined),
          };
          onChange({ params: Object.keys(merged).length > 0 ? merged : undefined });
        }}
        // The engine reads timeout_minutes/timeout_seconds for webhook.wait;
        // a timeout_ms example would be silently ignored at runtime.
        placeholder='{ "timeout_minutes": 1440 }'
        testId={`step-${step.id}-params-extra`}
      />
    </div>
  );
}

function otherParams(params: Record<string, unknown>): Record<string, unknown> | undefined {
  const rest = { ...params };
  delete rest.event_name;
  return Object.keys(rest).length > 0 ? rest : undefined;
}
