'use client';

import type { FlowDraft, StepType, WorkflowStepDraft } from '@/lib/flows/types';
import { AI_STEP_TYPES, STEP_TYPES } from '@/lib/flows/types';
import { Plus, Trash2, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { pickStepEditor } from './step-editors';

interface WorkflowStepsSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
  /** Validation errors keyed by step_id so the UI can flag the right card. */
  stepErrors?: Record<string, string[]>;
}

export function WorkflowStepsSection({ draft, onChange, stepErrors }: WorkflowStepsSectionProps) {
  const steps = draft.workflow.steps;

  const setSteps = (next: WorkflowStepDraft[]) =>
    onChange({ workflow: { ...draft.workflow, steps: next } });

  const addStep = () => {
    const newStep: WorkflowStepDraft = {
      id: `step_${steps.length + 1}`,
      name: `Step ${steps.length + 1}`,
      type: 'ai.extract',
    };
    setSteps([...steps, newStep]);
  };

  const updateStep = (index: number, updates: Partial<WorkflowStepDraft>) => {
    const updated = [...steps];
    updated[index] = { ...updated[index], ...updates };
    setSteps(updated);
  };

  const removeStep = (index: number) => setSteps(steps.filter((_, i) => i !== index));

  const duplicateStep = (index: number) => {
    const step = steps[index];
    const newStep: WorkflowStepDraft = { ...step, id: `${step.id}_copy_${Date.now()}` };
    const updated = [...steps];
    updated.splice(index + 1, 0, newStep);
    setSteps(updated);
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

      {steps.length === 0 ? (
        <p className="text-sm text-slate-500 text-center py-8">
          No steps defined. Click &quot;Add Step&quot; to create one.
        </p>
      ) : (
        <div className="space-y-4">
          {steps.map((step, idx) => (
            <StepCard
              key={idx}
              step={step}
              draft={draft}
              priorStepIds={steps.slice(0, idx).map((s) => s.id)}
              onChange={(updates) => updateStep(idx, updates)}
              onRemove={() => removeStep(idx)}
              onDuplicate={() => duplicateStep(idx)}
              errors={stepErrors?.[step.id]}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface StepCardProps {
  step: WorkflowStepDraft;
  draft: FlowDraft;
  priorStepIds: string[];
  onChange: (updates: Partial<WorkflowStepDraft>) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  errors?: string[];
}

function StepCard({
  step,
  draft,
  priorStepIds,
  onChange,
  onRemove,
  onDuplicate,
  errors,
}: StepCardProps) {
  const isAi = AI_STEP_TYPES.has(step.type);
  const StepEditor = pickStepEditor(step.type);
  const credentials = draft.credentials?.uses ?? [];

  return (
    <div
      className="relative border-l-2 pl-4"
      data-step-id={step.id}
      style={{ borderColor: errors && errors.length ? '#ef4444' : '#60a5fa' }}
    >
      <div
        className="absolute -left-2 top-2 w-4 h-4 rounded-full border-2 border-white"
        style={{ backgroundColor: errors && errors.length ? '#ef4444' : '#60a5fa' }}
      />

      <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1 grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Step ID</label>
              <input
                type="text"
                value={step.id}
                onChange={(e) => onChange({ id: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Name</label>
              <input
                type="text"
                value={step.name || ''}
                onChange={(e) => onChange({ name: e.target.value })}
                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Type</label>
              <select
                value={step.type}
                onChange={(e) => onChange({ type: e.target.value as StepType })}
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
              onClick={onDuplicate}
              className="p-1.5 text-slate-600 hover:bg-slate-200 rounded"
              title="Duplicate"
              aria-label={`Duplicate step ${step.id}`}
            >
              <Copy className="h-4 w-4" />
            </button>
            <button
              onClick={onRemove}
              className="p-1.5 text-red-600 hover:bg-red-50 rounded"
              title="Delete"
              aria-label={`Delete step ${step.id}`}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        {errors && errors.length > 0 && (
          <div className="mb-3 px-3 py-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
            <ul className="list-disc list-inside space-y-0.5">
              {errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Description</label>
            <input
              type="text"
              value={step.description || ''}
              onChange={(e) => onChange({ description: e.target.value })}
              className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="What does this step do?"
            />
          </div>

          <StepEditor step={step} draft={draft} priorStepIds={priorStepIds} onChange={onChange} />

          <CredentialsField
            available={credentials}
            value={step.uses_credentials || []}
            onChange={(creds) =>
              onChange({ uses_credentials: creds.length > 0 ? creds : undefined })
            }
          />
        </div>

        <details className="mt-3">
          <summary className="text-xs text-slate-600 cursor-pointer hover:text-slate-900">
            Advanced
          </summary>
          <div className="mt-2 space-y-2">
            {isAi && (
              <div className="grid grid-cols-2 gap-2">
                <NumericField
                  label="Temperature"
                  value={step.temperature}
                  step="0.1"
                  min={0}
                  max={2}
                  placeholder="0.1"
                  onChange={(v) => onChange({ temperature: v })}
                />
                <NumericField
                  label="Max tokens"
                  value={step.max_tokens}
                  min={1}
                  placeholder="512"
                  onChange={(v) => onChange({ max_tokens: v })}
                />
              </div>
            )}
            <RetryField value={step.retry} onChange={(retry) => onChange({ retry })} />
          </div>
        </details>
      </div>
    </div>
  );
}

function NumericField({
  label,
  value,
  onChange,
  step,
  min,
  max,
  placeholder,
}: {
  label: string;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  step?: string;
  min?: number;
  max?: number;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      <input
        type="number"
        step={step}
        min={min}
        max={max}
        value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === '') {
            onChange(undefined);
            return;
          }
          const parsed = step ? parseFloat(raw) : parseInt(raw, 10);
          onChange(Number.isNaN(parsed) ? undefined : parsed);
        }}
        placeholder={placeholder}
        className="w-full px-2 py-1 text-sm border border-slate-300 rounded"
      />
    </div>
  );
}

function RetryField({
  value,
  onChange,
}: {
  value: WorkflowStepDraft['retry'];
  onChange: (retry: WorkflowStepDraft['retry']) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-2">
      <NumericField
        label="Retry attempts"
        value={value?.attempts}
        min={0}
        placeholder="0"
        onChange={(v) => {
          if (v === undefined && !value?.backoff) {
            onChange(undefined);
            return;
          }
          onChange({ ...(value || {}), attempts: v });
        }}
      />
    </div>
  );
}

function CredentialsField({
  available,
  value,
  onChange,
}: {
  available: string[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  if (available.length === 0 && value.length === 0) return null;
  const toggle = (cred: string, checked: boolean) => {
    onChange(checked ? [...value, cred] : value.filter((c) => c !== cred));
  };
  const merged = Array.from(new Set([...available, ...value]));
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 mb-1">Uses credentials</label>
      <div className="flex flex-wrap gap-2">
        {merged.map((cred) => (
          <label
            key={cred}
            className="flex items-center gap-1.5 px-2 py-1 bg-slate-100 rounded cursor-pointer"
          >
            <input
              type="checkbox"
              checked={value.includes(cred)}
              onChange={(e) => toggle(cred, e.target.checked)}
              className="rounded"
            />
            <span className="text-xs">{cred}</span>
          </label>
        ))}
      </div>
    </div>
  );
}
