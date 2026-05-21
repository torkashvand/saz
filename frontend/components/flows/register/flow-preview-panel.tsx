'use client';

import { useState, useCallback } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { ValidationResult, FlowDraft } from '@/lib/flows/types';
import { piiPolicyFromBackend } from '@/lib/flows/types';
import { CheckCircle2, XCircle, Zap } from 'lucide-react';
import { AIOpsReferencePanel } from './ai-ops-reference';

interface FlowPreviewPanelProps {
  validationResult: ValidationResult | null;
  draft: FlowDraft;
}

function extractAIOpFromError(message: string): string | null {
  const match = message.match(/\(type:\s*(ai\.\w+)\)/);
  return match ? match[1] : null;
}

export function FlowPreviewPanel({ validationResult, draft }: FlowPreviewPanelProps) {
  const [activeTab, setActiveTab] = useState('summary');
  const [focusOp, setFocusOp] = useState<string | null>(null);

  const handleOpenOpReference = useCallback((opName: string) => {
    setFocusOp(opName);
    setActiveTab('ai-ops');
  }, []);

  const credentials = draft.credentials?.uses ?? [];
  const formFields = draft.form?.fields ?? [];
  const steps = draft.workflow.steps;

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full flex flex-col">
      <TabsList className="grid w-full grid-cols-3">
        <TabsTrigger value="summary">Summary</TabsTrigger>
        <TabsTrigger value="form">Form</TabsTrigger>
        <TabsTrigger value="ai-ops" className="gap-1">
          <Zap className="h-3 w-3" />
          AI Ops
        </TabsTrigger>
      </TabsList>

      <TabsContent value="summary" className="flex-1 space-y-4 overflow-y-auto">
        {!validationResult ? (
          <div className="flex items-center justify-center py-12 text-slate-500 text-sm">
            No preview available. Build your flow or validate YAML.
          </div>
        ) : (
          <>
            <div className="border border-slate-200 rounded-lg p-4 bg-white">
              <h3 className="text-sm font-semibold text-slate-900 mb-3">Validation Status</h3>
              <div className="flex items-start gap-3">
                {validationResult.valid ? (
                  <>
                    <CheckCircle2 className="h-5 w-5 text-green-600 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <div className="text-sm font-medium text-green-700">Valid</div>
                      <div className="text-xs text-slate-600 mt-0.5">Flow is ready to register</div>
                    </div>
                  </>
                ) : (
                  <>
                    <XCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <div className="text-sm font-medium text-red-700">
                        {validationResult.errors.length} errors
                      </div>
                      <div className="mt-2 space-y-1.5">
                        {validationResult.errors.slice(0, 5).map((err, idx) => {
                          const aiOp = extractAIOpFromError(err.message);
                          return (
                            <div key={idx}>
                              <div className="text-xs text-red-600">
                                {err.section ? (
                                  <span className="font-mono mr-1">[{err.section}]</span>
                                ) : null}
                                {err.step_id ? (
                                  <span className="font-mono mr-1">{err.step_id}:</span>
                                ) : null}
                                {err.message}
                              </div>
                              {aiOp && err.message.includes('expect') && (
                                <button
                                  onClick={() => handleOpenOpReference(aiOp)}
                                  className="ml-3 mt-0.5 text-[11px] text-blue-600 hover:text-blue-800 hover:underline flex items-center gap-1"
                                >
                                  <Zap className="h-3 w-3" />
                                  Open {aiOp} reference
                                </button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="border border-slate-200 rounded-lg p-4 bg-white">
              <h3 className="text-sm font-semibold text-slate-900 mb-3">Flow Overview</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-600">Name:</span>
                  <span className="font-mono text-slate-900">{draft.flow.name || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">Version:</span>
                  <span className="font-mono text-slate-900">{draft.flow.version || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">Mode:</span>
                  <span className="font-mono text-slate-900">{draft.workflow.planner_mode}</span>
                </div>
              </div>
            </div>

            <div className="border border-slate-200 rounded-lg p-4 bg-white">
              <h3 className="text-sm font-semibold text-slate-900 mb-3">Workflow Steps</h3>
              {steps.length === 0 ? (
                <p className="text-xs text-slate-500">No steps defined</p>
              ) : (
                <div className="space-y-2">
                  {steps.map((step, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-xs">
                      <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center font-medium">
                        {idx + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-slate-900 truncate">
                          {step.name || step.id}
                        </div>
                        <div className="text-slate-500">{step.type}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="border border-slate-200 rounded-lg p-4 bg-white">
              <h3 className="text-sm font-semibold text-slate-900 mb-3">Policies & Credentials</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-600">Budget:</span>
                  <span className="font-mono text-slate-900">
                    ${draft.policies?.budget_usd?.toFixed(2) || '0.00'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">PII Policy:</span>
                  <span className="text-slate-900">
                    {piiPolicyFromBackend(draft.policies?.pii)}
                  </span>
                </div>
                {credentials.length > 0 && (
                  <div>
                    <div className="text-slate-600 mb-1">Credentials:</div>
                    <div className="flex flex-wrap gap-1">
                      {credentials.map((cred) => (
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
          </>
        )}
      </TabsContent>

      <TabsContent value="form" className="flex-1 overflow-y-auto">
        <div className="border border-slate-200 rounded-lg p-4 bg-white">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">Form Fields</h3>
          {formFields.length === 0 ? (
            <p className="text-xs text-slate-500">No form fields defined</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="text-left py-2 px-2 font-semibold text-slate-700">Name</th>
                    <th className="text-left py-2 px-2 font-semibold text-slate-700">Type</th>
                    <th className="text-left py-2 px-2 font-semibold text-slate-700">Required</th>
                    <th className="text-left py-2 px-2 font-semibold text-slate-700">
                      Description
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {formFields.map((field, idx) => (
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

      <TabsContent value="ai-ops" className="flex-1 overflow-y-auto">
        <AIOpsReferencePanel focusOp={focusOp} onFocusHandled={() => setFocusOp(null)} />
      </TabsContent>
    </Tabs>
  );
}
