'use client';

import type { FlowDraft, FlowPolicies, PiiPolicyValue } from '@/lib/flows/types';
import { PII_POLICIES, piiPolicyFromBackend, piiPolicyToBackend } from '@/lib/flows/types';
import { X } from 'lucide-react';

interface PoliciesSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

export function PoliciesSection({ draft, onChange }: PoliciesSectionProps) {
  const policies: FlowPolicies = draft.policies ?? {};
  const credentials = draft.credentials?.uses ?? [];
  const piiValue: PiiPolicyValue = piiPolicyFromBackend(policies.pii);

  const setPolicies = (next: FlowPolicies) => {
    const hasContent = Object.values(next).some((v) => v !== undefined);
    onChange({ policies: hasContent ? next : undefined });
  };

  const updatePolicies = (next: Partial<FlowPolicies>) => setPolicies({ ...policies, ...next });

  const updateDefaults = (next: Partial<NonNullable<FlowPolicies['defaults']>>) => {
    const current = policies.defaults || {};
    const merged: NonNullable<FlowPolicies['defaults']> = { ...current, ...next };
    const cleaned = Object.fromEntries(
      Object.entries(merged).filter(([, v]) => v !== undefined),
    ) as NonNullable<FlowPolicies['defaults']>;
    updatePolicies({
      defaults: Object.keys(cleaned).length > 0 ? cleaned : undefined,
    });
  };

  const updateConcurrency = (next: Partial<NonNullable<FlowPolicies['concurrency']>>) => {
    const current = policies.concurrency || {};
    const merged = { ...current, ...next };
    const cleaned = Object.fromEntries(
      Object.entries(merged).filter(([, v]) => v !== undefined),
    ) as NonNullable<FlowPolicies['concurrency']>;
    updatePolicies({
      concurrency: Object.keys(cleaned).length > 0 ? cleaned : undefined,
    });
  };

  const setPii = (value: PiiPolicyValue) => {
    const mapped = piiPolicyToBackend(value);
    updatePolicies({
      pii: {
        ...policies.pii,
        allow: mapped.allow,
        tokenize_model_inputs: mapped.tokenize_model_inputs,
      },
    });
  };

  const setCredentials = (next: string[]) =>
    onChange({ credentials: next.length > 0 ? { uses: next } : undefined });

  const addCredential = () => {
    const cred = prompt('Enter credential ID:');
    if (cred && !credentials.includes(cred)) {
      setCredentials([...credentials, cred]);
    }
  };

  const removeCredential = (cred: string) => setCredentials(credentials.filter((c) => c !== cred));

  return (
    <div id="policies" className="bg-white border border-slate-200 rounded-lg p-6">
      <h2 className="text-lg font-semibold text-slate-900 mb-4">Policies & Credentials</h2>

      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Budget (USD)</label>
            <input
              type="number"
              step="0.01"
              value={policies.budget_usd ?? ''}
              onChange={(e) =>
                updatePolicies({
                  budget_usd: e.target.value === '' ? undefined : parseFloat(e.target.value),
                })
              }
              className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="1.00"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">PII Policy</label>
            <select
              value={piiValue}
              onChange={(e) => setPii(e.target.value as PiiPolicyValue)}
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

        <fieldset className="border border-slate-200 rounded-md p-3">
          <legend className="text-xs font-medium text-slate-700 px-1">Defaults</legend>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Timeout (ms)</label>
              <input
                type="number"
                min={1}
                value={policies.defaults?.timeout_ms ?? ''}
                onChange={(e) =>
                  updateDefaults({
                    timeout_ms: e.target.value === '' ? undefined : parseInt(e.target.value, 10),
                  })
                }
                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                placeholder="60000"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Retry attempts
              </label>
              <input
                type="number"
                min={0}
                value={policies.defaults?.retry?.attempts ?? ''}
                onChange={(e) => {
                  const value = e.target.value;
                  const attempts = value === '' ? undefined : parseInt(value, 10);
                  const current = policies.defaults?.retry || {};
                  const nextRetry = { ...current, attempts };
                  const cleaned =
                    attempts === undefined && !current.backoff ? undefined : nextRetry;
                  updateDefaults({ retry: cleaned });
                }}
                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                placeholder="3"
              />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={policies.defaults?.continue_on_fail === true}
                  onChange={(e) =>
                    updateDefaults({
                      continue_on_fail: e.target.checked ? true : undefined,
                    })
                  }
                  className="rounded"
                />
                <span className="text-xs text-slate-600">Continue on fail</span>
              </label>
            </div>
          </div>
        </fieldset>

        <fieldset className="border border-slate-200 rounded-md p-3">
          <legend className="text-xs font-medium text-slate-700 px-1">Concurrency</legend>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Per flow</label>
              <input
                type="number"
                min={1}
                value={policies.concurrency?.per_flow ?? ''}
                onChange={(e) =>
                  updateConcurrency({
                    per_flow: e.target.value === '' ? undefined : parseInt(e.target.value, 10),
                  })
                }
                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                placeholder="1"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Per user</label>
              <input
                type="number"
                min={1}
                value={policies.concurrency?.per_user ?? ''}
                onChange={(e) =>
                  updateConcurrency({
                    per_user: e.target.value === '' ? undefined : parseInt(e.target.value, 10),
                  })
                }
                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                placeholder="1"
              />
            </div>
          </div>
        </fieldset>

        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Credentials</label>
          <div className="flex flex-wrap gap-2 mb-2">
            {credentials.map((cred) => (
              <span
                key={cred}
                className="inline-flex items-center gap-1 px-2 py-1 bg-orange-100 text-orange-700 text-xs rounded"
              >
                {cred}
                <button
                  onClick={() => removeCredential(cred)}
                  aria-label={`Remove credential ${cred}`}
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
