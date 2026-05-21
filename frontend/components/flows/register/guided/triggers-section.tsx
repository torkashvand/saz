'use client';

import type { FlowDraft, FlowTriggers } from '@/lib/flows/types';

interface TriggersSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

export function TriggersSection({ draft, onChange }: TriggersSectionProps) {
  const triggers: FlowTriggers = draft.triggers ?? { manual: true };

  const update = (next: Partial<FlowTriggers>) => onChange({ triggers: { ...triggers, ...next } });

  return (
    <div id="triggers" className="bg-white border border-slate-200 rounded-lg p-6">
      <h2 className="text-lg font-semibold text-slate-900 mb-4">Triggers</h2>

      <div className="space-y-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={triggers.manual !== false}
            onChange={(e) => update({ manual: e.target.checked })}
            className="rounded"
          />
          <span className="text-sm font-medium text-slate-700">Manual Trigger</span>
        </label>

        <div>
          <label className="flex items-center gap-2 cursor-pointer mb-2">
            <input
              type="checkbox"
              checked={triggers.webhook?.enabled || false}
              onChange={(e) =>
                update({
                  webhook: { ...triggers.webhook, enabled: e.target.checked },
                })
              }
              className="rounded"
            />
            <span className="text-sm font-medium text-slate-700">Webhook Trigger</span>
          </label>
          {triggers.webhook?.enabled && (
            <div className="ml-6 space-y-2">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Path</label>
                <input
                  type="text"
                  value={triggers.webhook.path || ''}
                  onChange={(e) =>
                    update({
                      webhook: { ...triggers.webhook!, path: e.target.value || undefined },
                    })
                  }
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="/my-webhook"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Event</label>
                <input
                  type="text"
                  value={triggers.webhook.event || ''}
                  onChange={(e) =>
                    update({
                      webhook: { ...triggers.webhook!, event: e.target.value || undefined },
                    })
                  }
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g., support.ticket.created"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Signature header
                </label>
                <input
                  type="text"
                  value={triggers.webhook.signature_header || ''}
                  onChange={(e) =>
                    update({
                      webhook: {
                        ...triggers.webhook!,
                        signature_header: e.target.value || undefined,
                      },
                    })
                  }
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="X-Signature"
                />
                <p className="text-xs text-slate-500 mt-1">
                  Incoming HTTP header that carries the signature for verification.
                </p>
              </div>
            </div>
          )}
        </div>

        <div>
          <label className="flex items-center gap-2 cursor-pointer mb-2">
            <input
              type="checkbox"
              checked={triggers.schedule?.enabled || false}
              onChange={(e) =>
                update({
                  schedule: { ...triggers.schedule, enabled: e.target.checked },
                })
              }
              className="rounded"
            />
            <span className="text-sm font-medium text-slate-700">Schedule Trigger</span>
          </label>
          {triggers.schedule?.enabled && (
            <div className="ml-6 space-y-2">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Cron Expression
                </label>
                <input
                  type="text"
                  value={triggers.schedule.cron || ''}
                  onChange={(e) =>
                    update({
                      schedule: {
                        ...triggers.schedule!,
                        cron: e.target.value || undefined,
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
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Timezone</label>
                <input
                  type="text"
                  value={triggers.schedule.timezone || ''}
                  onChange={(e) =>
                    update({
                      schedule: {
                        ...triggers.schedule!,
                        timezone: e.target.value || undefined,
                      },
                    })
                  }
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="America/New_York"
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
