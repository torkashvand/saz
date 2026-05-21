'use client';

import type { FlowDraft, FlowTelemetry } from '@/lib/flows/types';

interface TelemetrySectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

const TRACE_LEVELS: ReadonlyArray<{
  value: NonNullable<FlowTelemetry['trace_level']>;
  label: string;
}> = [
  { value: 'off', label: 'Off (no telemetry)' },
  { value: 'meta', label: 'Meta (run/step boundaries only)' },
  { value: 'brief', label: 'Brief (+ tool calls, policy decisions)' },
  { value: 'verbose', label: 'Verbose (+ input summaries)' },
];

export function TelemetrySection({ draft, onChange }: TelemetrySectionProps) {
  const telemetry: FlowTelemetry = draft.telemetry || {};

  const update = (next: Partial<FlowTelemetry>) => {
    const merged = { ...telemetry, ...next };
    const cleaned: FlowTelemetry = {};
    if (merged.trace_level) cleaned.trace_level = merged.trace_level;
    if (typeof merged.sample_rate === 'number') cleaned.sample_rate = merged.sample_rate;
    onChange({ telemetry: Object.keys(cleaned).length > 0 ? cleaned : undefined });
  };

  return (
    <div id="telemetry" className="bg-white border border-slate-200 rounded-lg p-6">
      <h2 className="text-lg font-semibold text-slate-900 mb-4">Telemetry</h2>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Trace level</label>
          <select
            value={telemetry.trace_level || ''}
            onChange={(e) =>
              update({
                trace_level: (e.target.value || undefined) as FlowTelemetry['trace_level'],
              })
            }
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Default</option>
            {TRACE_LEVELS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Sample rate</label>
          <input
            type="number"
            min={0}
            max={1}
            step={0.1}
            value={telemetry.sample_rate ?? ''}
            onChange={(e) =>
              update({
                sample_rate: e.target.value === '' ? undefined : Number(e.target.value),
              })
            }
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="1.0"
          />
          <p className="text-xs text-slate-500 mt-1">0.0 (none) to 1.0 (every run).</p>
        </div>
      </div>
    </div>
  );
}
