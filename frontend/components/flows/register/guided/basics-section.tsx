'use client';

import type { FlowDraft } from '@/lib/flows/types';
import { X } from 'lucide-react';

interface BasicsSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

export function BasicsSection({ draft, onChange }: BasicsSectionProps) {
  const addLabel = () => {
    const label = prompt('Enter label name:');
    if (label && !draft.labels?.includes(label)) {
      onChange({ labels: [...(draft.labels || []), label] });
    }
  };

  const removeLabel = (label: string) => {
    onChange({ labels: draft.labels?.filter(l => l !== label) });
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
            value={draft.name}
            onChange={(e) => onChange({ name: e.target.value })}
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
              value={draft.version}
              onChange={(e) => onChange({ version: e.target.value })}
              className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="1.0"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Planner Mode</label>
            <select
              value={draft.planner_mode || 'deterministic'}
              onChange={(e) => onChange({ planner_mode: e.target.value as any })}
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
            value={draft.description}
            onChange={(e) => onChange({ description: e.target.value })}
            rows={3}
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="What does this workflow do?"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Labels</label>
          <div className="flex flex-wrap gap-2 mb-2">
            {draft.labels?.map((label) => (
              <span
                key={label}
                className="inline-flex items-center gap-1 px-2 py-1 bg-slate-100 text-slate-700 text-xs rounded"
              >
                {label}
                <button
                  onClick={() => removeLabel(label)}
                  className="text-slate-500 hover:text-slate-700"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
          <button
            onClick={addLabel}
            className="text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            + Add Label
          </button>
        </div>
      </div>
    </div>
  );
}
