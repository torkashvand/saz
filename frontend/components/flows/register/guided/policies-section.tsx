'use client';

import type { FlowDraft } from '@/lib/flows/types';
import { PII_POLICIES } from '@/lib/flows/types';
import { X } from 'lucide-react';

interface PoliciesSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

export function PoliciesSection({ draft, onChange }: PoliciesSectionProps) {
  const addCredential = () => {
    const cred = prompt('Enter credential ID:');
    if (cred && !draft.credentials.includes(cred)) {
      onChange({ credentials: [...draft.credentials, cred] });
    }
  };

  const removeCredential = (cred: string) => {
    onChange({ credentials: draft.credentials.filter((c) => c !== cred) });
  };

  return (
    <div id="policies" className="bg-white border border-slate-200 rounded-lg p-6">
      <h2 className="text-lg font-semibold text-slate-900 mb-4">Policies & Credentials</h2>

      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Budget (USD)
            </label>
            <input
              type="number"
              step="0.01"
              value={draft.policies.budget_usd || ''}
              onChange={(e) =>
                onChange({
                  policies: { ...draft.policies, budget_usd: parseFloat(e.target.value) || 0 },
                })
              }
              className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="1.00"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">PII Policy</label>
            <select
              value={draft.policies.pii_policy || 'disallow'}
              onChange={(e) =>
                onChange({ policies: { ...draft.policies, pii_policy: e.target.value as any } })
              }
              className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {PII_POLICIES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Credentials</label>
          <div className="flex flex-wrap gap-2 mb-2">
            {draft.credentials.map((cred) => (
              <span
                key={cred}
                className="inline-flex items-center gap-1 px-2 py-1 bg-orange-100 text-orange-700 text-xs rounded"
              >
                {cred}
                <button
                  onClick={() => removeCredential(cred)}
                  className="text-orange-600 hover:text-orange-800"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
          <button
            onClick={addCredential}
            className="text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            + Add Credential
          </button>
        </div>
      </div>
    </div>
  );
}
