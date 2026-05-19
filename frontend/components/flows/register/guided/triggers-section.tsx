'use client';

import type { FlowDraft } from '@/lib/flows/types';

interface TriggersSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

export function TriggersSection({ draft, onChange }: TriggersSectionProps) {
  return (
    <div id="triggers" className="bg-white border border-slate-200 rounded-lg p-6">
      <h2 className="text-lg font-semibold text-slate-900 mb-4">Triggers</h2>

      <div className="space-y-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={draft.triggers.manual}
            onChange={(e) =>
              onChange({ triggers: { ...draft.triggers, manual: e.target.checked } })
            }
            className="rounded"
          />
          <span className="text-sm font-medium text-slate-700">Manual Trigger</span>
        </label>

        <div>
          <label className="flex items-center gap-2 cursor-pointer mb-2">
            <input
              type="checkbox"
              checked={draft.triggers.webhook?.enabled || false}
              onChange={(e) =>
                onChange({
                  triggers: {
                    ...draft.triggers,
                    webhook: { ...draft.triggers.webhook, enabled: e.target.checked },
                  },
                })
              }
              className="rounded"
            />
            <span className="text-sm font-medium text-slate-700">Webhook Trigger</span>
          </label>
          {draft.triggers.webhook?.enabled && (
            <div className="ml-6 space-y-2">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Path</label>
                <input
                  type="text"
                  value={draft.triggers.webhook.path || ''}
                  onChange={(e) =>
                    onChange({
                      triggers: {
                        ...draft.triggers,
                        webhook: { ...draft.triggers.webhook!, path: e.target.value },
                      },
                    })
                  }
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="/my-webhook"
                />
              </div>
            </div>
          )}
        </div>

        <div>
          <label className="flex items-center gap-2 cursor-pointer mb-2">
            <input
              type="checkbox"
              checked={draft.triggers.schedule?.enabled || false}
              onChange={(e) =>
                onChange({
                  triggers: {
                    ...draft.triggers,
                    schedule: { ...draft.triggers.schedule, enabled: e.target.checked },
                  },
                })
              }
              className="rounded"
            />
            <span className="text-sm font-medium text-slate-700">Schedule Trigger</span>
          </label>
          {draft.triggers.schedule?.enabled && (
            <div className="ml-6 space-y-2">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Cron Expression
                </label>
                <input
                  type="text"
                  value={draft.triggers.schedule.cron || ''}
                  onChange={(e) =>
                    onChange({
                      triggers: {
                        ...draft.triggers,
                        schedule: { ...draft.triggers.schedule!, cron: e.target.value },
                      },
                    })
                  }
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="0 9 * * *"
                />
                <p className="text-xs text-slate-500 mt-1">
                  E.g., &quot;0 9 * * *&quot; = daily at 9 AM
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
