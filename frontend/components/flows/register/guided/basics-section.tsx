'use client';

import { useState } from 'react';
import type { FlowDraft, FlowSection, PlannerMode } from '@/lib/flows/types';
import { Plus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface BasicsSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

export function BasicsSection({ draft, onChange }: BasicsSectionProps) {
  const [labelKey, setLabelKey] = useState('');
  const [labelValue, setLabelValue] = useState('');

  const flow = draft.flow;
  const labels = flow.labels ?? {};
  const labelEntries = Object.entries(labels);

  const patchFlow = (next: Partial<FlowSection>) => onChange({ flow: { ...flow, ...next } });

  const setPlannerMode = (mode: PlannerMode) =>
    onChange({ workflow: { ...draft.workflow, planner_mode: mode } });

  const addLabel = () => {
    const key = labelKey.trim();
    const value = labelValue.trim();
    if (!key || !value) return;
    patchFlow({ labels: { ...labels, [key]: value } });
    setLabelKey('');
    setLabelValue('');
  };

  const removeLabel = (key: string) => {
    const next = { ...labels };
    delete next[key];
    patchFlow({ labels: Object.keys(next).length > 0 ? next : undefined });
  };

  return (
    <div id="basics" className="bg-white border border-slate-200 rounded-lg p-6">
      <h2 className="text-lg font-semibold text-slate-900 mb-4">Basics</h2>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Flow Name <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            value={flow.name}
            onChange={(e) => patchFlow({ name: e.target.value })}
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g., support_ticket_triage"
          />
          <p className="text-xs text-slate-500 mt-1">Use snake_case, no spaces</p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Version <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={flow.version || ''}
              onChange={(e) => patchFlow({ version: e.target.value || undefined })}
              className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="1.0"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Planner Mode</label>
            <select
              value={draft.workflow.planner_mode}
              onChange={(e) => setPlannerMode(e.target.value as PlannerMode)}
              className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="deterministic">Deterministic</option>
              <option value="agentic">Agentic</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Description</label>
          <textarea
            value={flow.description}
            onChange={(e) => patchFlow({ description: e.target.value })}
            rows={3}
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="What does this workflow do?"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Labels</label>
          {labelEntries.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {labelEntries.map(([key, value]) => (
                <span
                  key={key}
                  className="inline-flex items-center gap-1 px-2 py-1 bg-slate-100 text-slate-700 text-xs rounded"
                >
                  <span className="font-mono">{key}</span>
                  <span className="text-slate-500">=</span>
                  <span className="font-mono">{value}</span>
                  <button
                    onClick={() => removeLabel(key)}
                    aria-label={`Remove label ${key}`}
                    className="text-slate-500 hover:text-slate-700"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={labelKey}
              onChange={(e) => setLabelKey(e.target.value)}
              placeholder="key"
              className="w-32 px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <input
              type="text"
              value={labelValue}
              onChange={(e) => setLabelValue(e.target.value)}
              placeholder="value"
              className="flex-1 px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <Button
              size="sm"
              variant="ghost"
              onClick={addLabel}
              disabled={!labelKey.trim() || !labelValue.trim()}
            >
              <Plus className="h-4 w-4 mr-1" />
              Add
            </Button>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Labels are stored as a key/value map (e.g. <span className="font-mono">team=ops</span>).
          </p>
        </div>
      </div>
    </div>
  );
}
