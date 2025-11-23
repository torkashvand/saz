'use client';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { ValidationResult, FlowDraft } from '@/lib/flows/types';
import { CheckCircle2, XCircle, AlertCircle } from 'lucide-react';

interface FlowPreviewPanelProps {
  validationResult: ValidationResult | null;
  draft: FlowDraft;
}

export function FlowPreviewPanel({ validationResult, draft }: FlowPreviewPanelProps) {
  if (!validationResult) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        No preview available. Build your flow or validate YAML.
      </div>
    );
  }

  return (
    <Tabs defaultValue="summary" className="h-full flex flex-col">
      <TabsList className="grid w-full grid-cols-2">
        <TabsTrigger value="summary">Summary</TabsTrigger>
        <TabsTrigger value="form">Form Schema</TabsTrigger>
      </TabsList>

      <TabsContent value="summary" className="flex-1 space-y-4 overflow-y-auto">
        {/* Validation Status Card */}
        <div className="border border-slate-200 rounded-lg p-4 bg-white">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Validation Status</h3>
          <div className="flex items-start gap-3">
            {validationResult.valid ? (
              <>
                <CheckCircle2 className="h-5 w-5 text-green-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <div className="text-sm font-medium text-green-700">Valid</div>
                  <div className="text-xs text-slate-600 mt-0.5">
                    Flow is ready to register
                  </div>
                </div>
              </>
            ) : (
              <>
                <XCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <div className="text-sm font-medium text-red-700">
                    {validationResult.errors.length} errors
                  </div>
                  <div className="mt-2 space-y-1">
                    {validationResult.errors.slice(0, 3).map((err, idx) => (
                      <div key={idx} className="text-xs text-red-600">
                        • {err.message}
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Flow Overview */}
        <div className="border border-slate-200 rounded-lg p-4 bg-white">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Flow Overview</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-600">Name:</span>
              <span className="font-mono text-slate-900">{draft.name || '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-600">Version:</span>
              <span className="font-mono text-slate-900">{draft.version || '—'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-600">Mode:</span>
              <span className="font-mono text-slate-900">{draft.planner_mode || 'deterministic'}</span>
            </div>
          </div>
        </div>

        {/* Workflow Steps Summary */}
        <div className="border border-slate-200 rounded-lg p-4 bg-white">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Workflow Steps</h3>
          {draft.workflow_steps.length === 0 ? (
            <p className="text-xs text-slate-500">No steps defined</p>
          ) : (
            <div className="space-y-2">
              {draft.workflow_steps.map((step, idx) => (
                <div key={idx} className="flex items-start gap-2 text-xs">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center font-medium">
                    {idx + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-slate-900 truncate">{step.name}</div>
                    <div className="text-slate-500">{step.type}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Policies & Credentials */}
        <div className="border border-slate-200 rounded-lg p-4 bg-white">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Policies & Credentials</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-600">Budget:</span>
              <span className="font-mono text-slate-900">
                ${draft.policies.budget_usd?.toFixed(2) || '0.00'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-600">PII Policy:</span>
              <span className="text-slate-900">{draft.policies.pii_policy || 'disallow'}</span>
            </div>
            {draft.credentials.length > 0 && (
              <div>
                <div className="text-slate-600 mb-1">Credentials:</div>
                <div className="flex flex-wrap gap-1">
                  {draft.credentials.map((cred) => (
                    <span
                      key={cred}
                      className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded"
                    >
                      {cred}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </TabsContent>

      <TabsContent value="form" className="flex-1 overflow-y-auto">
        <div className="border border-slate-200 rounded-lg p-4 bg-white">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Form Fields</h3>
          {draft.form_fields.length === 0 ? (
            <p className="text-xs text-slate-500">No form fields defined</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="text-left py-2 px-2 font-semibold text-slate-700">Name</th>
                    <th className="text-left py-2 px-2 font-semibold text-slate-700">Type</th>
                    <th className="text-left py-2 px-2 font-semibold text-slate-700">Required</th>
                    <th className="text-left py-2 px-2 font-semibold text-slate-700">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.form_fields.map((field, idx) => (
                    <tr key={idx} className="border-b border-slate-100">
                      <td className="py-2 px-2 font-mono text-slate-900">{field.name}</td>
                      <td className="py-2 px-2 text-slate-600">{field.type}</td>
                      <td className="py-2 px-2">
                        {field.required ? (
                          <span className="text-red-600">✓</span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="py-2 px-2 text-slate-600">{field.description || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </TabsContent>
    </Tabs>
  );
}
