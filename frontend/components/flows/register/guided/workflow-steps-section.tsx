'use client';

import type { FlowDraft, WorkflowStepDraft } from '@/lib/flows/types';
import { Plus, Trash2, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { STEP_TYPES } from '@/lib/flows/types';

interface WorkflowStepsSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

export function WorkflowStepsSection({ draft, onChange }: WorkflowStepsSectionProps) {
  const addStep = () => {
    const newStep: WorkflowStepDraft = {
      id: `step_${draft.workflow_steps.length + 1}`,
      name: `Step ${draft.workflow_steps.length + 1}`,
      type: 'ai.extract',
    };
    onChange({ workflow_steps: [...draft.workflow_steps, newStep] });
  };

  const updateStep = (index: number, updates: Partial<WorkflowStepDraft>) => {
    const updated = [...draft.workflow_steps];
    updated[index] = { ...updated[index], ...updates };
    onChange({ workflow_steps: updated });
  };

  const removeStep = (index: number) => {
    onChange({ workflow_steps: draft.workflow_steps.filter((_, i) => i !== index) });
  };

  const duplicateStep = (index: number) => {
    const step = draft.workflow_steps[index];
    const newStep = { ...step, id: `${step.id}_copy_${Date.now()}` };
    const updated = [...draft.workflow_steps];
    updated.splice(index + 1, 0, newStep);
    onChange({ workflow_steps: updated });
  };

  return (
    <div id="steps" className="bg-white border border-slate-200 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-900">Workflow Steps</h2>
        <Button size="sm" onClick={addStep}>
          <Plus className="h-4 w-4 mr-1" />
          Add Step
        </Button>
      </div>

      {draft.workflow_steps.length === 0 ? (
        <p className="text-sm text-slate-500 text-center py-8">
          No steps defined. Click &quot;Add Step&quot; to create one.
        </p>
      ) : (
        <div className="space-y-4">
          {draft.workflow_steps.map((step, idx) => (
            <div key={idx} className="relative border-l-2 border-blue-400 pl-4">
              <div className="absolute -left-2 top-2 w-4 h-4 rounded-full bg-blue-400 border-2 border-white"></div>

              <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1 grid grid-cols-3 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Step ID
                      </label>
                      <input
                        type="text"
                        value={step.id}
                        onChange={(e) => updateStep(idx, { id: e.target.value })}
                        className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">Name</label>
                      <input
                        type="text"
                        value={step.name}
                        onChange={(e) => updateStep(idx, { name: e.target.value })}
                        className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">Type</label>
                      <select
                        value={step.type}
                        onChange={(e) => updateStep(idx, { type: e.target.value as any })}
                        className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        {STEP_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="flex gap-1 ml-3">
                    <button
                      onClick={() => duplicateStep(idx)}
                      className="p-1.5 text-slate-600 hover:bg-slate-200 rounded"
                      title="Duplicate"
                    >
                      <Copy className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => removeStep(idx)}
                      className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                      title="Delete"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                <div className="space-y-2">
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                      Description
                    </label>
                    <input
                      type="text"
                      value={step.description || ''}
                      onChange={(e) => updateStep(idx, { description: e.target.value })}
                      className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="What does this step do?"
                    />
                  </div>

                  {(step.type.startsWith('ai.') || step.type === 'webhook.wait') && (
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        Instruction
                      </label>
                      <textarea
                        value={step.instruction || ''}
                        onChange={(e) => updateStep(idx, { instruction: e.target.value })}
                        rows={2}
                        className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="AI instruction or prompt..."
                      />
                    </div>
                  )}

                  {step.type === 'tool.call' && (
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">Tool</label>
                      <input
                        type="text"
                        value={step.tool || ''}
                        onChange={(e) => updateStep(idx, { tool: e.target.value })}
                        className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="e.g., http_request"
                      />
                    </div>
                  )}
                </div>

                <details className="mt-2">
                  <summary className="text-xs text-slate-600 cursor-pointer hover:text-slate-900">
                    Advanced Config
                  </summary>
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    {step.type.startsWith('ai.') && (
                      <>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 mb-1">
                            Temperature
                          </label>
                          <input
                            type="number"
                            step="0.1"
                            min="0"
                            max="2"
                            value={step.temperature ?? ''}
                            onChange={(e) =>
                              updateStep(idx, { temperature: parseFloat(e.target.value) || undefined })
                            }
                            className="w-full px-2 py-1 text-sm border border-slate-300 rounded"
                            placeholder="0.1"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 mb-1">
                            Max Tokens
                          </label>
                          <input
                            type="number"
                            value={step.max_tokens ?? ''}
                            onChange={(e) =>
                              updateStep(idx, { max_tokens: parseInt(e.target.value) || undefined })
                            }
                            className="w-full px-2 py-1 text-sm border border-slate-300 rounded"
                            placeholder="512"
                          />
                        </div>
                      </>
                    )}
                  </div>
                </details>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
