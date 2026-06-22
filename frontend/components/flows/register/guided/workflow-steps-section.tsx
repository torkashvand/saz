'use client';

import { useEffect, useRef, useState } from 'react';
import type { FlowDraft, StepType, WorkflowStepDraft } from '@/lib/flows/types';
import { AI_STEP_TYPES, STEP_TYPES } from '@/lib/flows/types';
import { Plus, Trash2, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { pickStepEditor } from './step-editors';
import { pickFriendlyEditor } from './business-step-editors';
import { ExpertModeToggle } from './expert-mode-toggle';
import {
  addStepMenu,
  bindingContextFor,
  createBusinessStep,
  createTechnicalStep,
  resolvePresentation,
} from '@/lib/flows/business-step-metadata';
import { getActiveDomainPack } from '@/lib/flows/domain-packs/registry';
import type { BusinessStepPattern, StepStatus } from '@/lib/flows/domain-packs/types';

interface WorkflowStepsSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
  /** Validation errors keyed by step_id so the UI can flag the right card. */
  stepErrors?: Record<string, string[]>;
}

export function WorkflowStepsSection({ draft, onChange, stepErrors }: WorkflowStepsSectionProps) {
  const steps = draft.workflow.steps;
  const [expertMode, setExpertMode] = useState(false);
  const sectionRef = useRef<HTMLDivElement>(null);
  const [scrollToId, setScrollToId] = useState<string | null>(null);

  // Bring a newly added/duplicated step into view and focus its first control.
  useEffect(() => {
    if (!scrollToId) return;
    const card = sectionRef.current?.querySelector(`[data-step-id="${scrollToId}"]`);
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      (card.querySelector('input, select, textarea') as HTMLElement | null)?.focus({
        preventScroll: true,
      });
    }
    setScrollToId(null);
  }, [scrollToId]);

  const setSteps = (next: WorkflowStepDraft[]) =>
    onChange({ workflow: { ...draft.workflow, steps: next } });

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
    setScrollToId(newStep.id);
  };

  const pack = getActiveDomainPack();

  const appendStep = (step: WorkflowStepDraft) => {
    setSteps([...steps, step]);
    setScrollToId(step.id);
  };

  const addBusinessStep = (pattern: BusinessStepPattern) =>
    appendStep(
      createBusinessStep(
        pattern,
        steps.map((s) => s.id),
        pack,
      ),
    );

  const addTechnicalStep = (type: StepType) =>
    appendStep(
      createTechnicalStep(
        type,
        steps.map((s) => s.id),
      ),
    );

  return (
    <div id="steps" ref={sectionRef} className="bg-white border border-slate-200 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-900">Workflow Steps</h2>
        <div className="flex items-center gap-3">
          <ExpertModeToggle expert={expertMode} onChange={setExpertMode} />
          <AddStepPicker onAddPattern={addBusinessStep} onAddType={addTechnicalStep} />
        </div>
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
              expertMode={expertMode}
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
  expertMode: boolean;
}

function StepCard({
  step,
  draft,
  priorStepIds,
  onChange,
  onRemove,
  onDuplicate,
  errors,
  expertMode,
}: StepCardProps) {
  const isAi = AI_STEP_TYPES.has(step.type);
  const friendlyEditor = pickFriendlyEditor(step);
  const FriendlyEditor = !expertMode ? friendlyEditor : null;
  const GenericEditor = pickStepEditor(step.type);
  const credentials = draft.credentials?.uses ?? [];

  const context = bindingContextFor(draft.form?.fields, priorStepIds, draft.workflow.steps);
  const presentation = resolvePresentation(step, getActiveDomainPack(), context);

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
          {expertMode ? (
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
          ) : (
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span aria-hidden="true">{presentation.icon}</span>
                <h3 className="text-sm font-semibold text-slate-900">{presentation.label}</h3>
                <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 capitalize">
                  {presentation.category}
                </span>
                <StatusChip status={presentation.status} />
              </div>
              <p className="mt-1 text-xs text-slate-500">{presentation.summary}</p>
              {presentation.reviewer && (
                <p className="mt-0.5 text-xs text-slate-500">Reviewer: {presentation.reviewer}</p>
              )}
              {presentation.conditionSummary && (
                <p className="mt-0.5 text-xs text-slate-500">{presentation.conditionSummary}</p>
              )}
            </div>
          )}

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

          {FriendlyEditor ? (
            <FriendlyEditor
              step={step}
              draft={draft}
              priorStepIds={priorStepIds}
              onChange={onChange}
            />
          ) : (
            <>
              {!expertMode && !isAi && (
                <div className="px-3 py-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-700">
                  Expert step — this step is configured with technical settings.
                </div>
              )}
              <GenericEditor
                step={step}
                draft={draft}
                priorStepIds={priorStepIds}
                onChange={onChange}
              />
            </>
          )}

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

const STATUS_STYLES: Record<StepStatus['kind'], string> = {
  ready: 'bg-green-50 text-green-700',
  needs_setup: 'bg-amber-50 text-amber-700',
  missing_mappings: 'bg-amber-50 text-amber-700',
  reviewer_missing: 'bg-amber-50 text-amber-700',
  advanced: 'bg-slate-100 text-slate-600',
};

function StatusChip({ status }: { status: StepStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status.kind]}`}
    >
      {status.label}
    </span>
  );
}

function AddStepPicker({
  onAddPattern,
  onAddType,
}: {
  onAddPattern: (pattern: BusinessStepPattern) => void;
  onAddType: (type: StepType) => void;
}) {
  const [open, setOpen] = useState(false);
  const groups = addStepMenu(getActiveDomainPack());
  return (
    <div className="relative">
      <Button
        size="sm"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Plus className="h-4 w-4 mr-1" />
        Add step
      </Button>
      {open && (
        <>
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            className="fixed inset-0 z-10 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div
            role="menu"
            className="absolute right-0 z-20 mt-1 max-h-80 w-72 overflow-auto rounded-md border border-slate-200 bg-white py-1 shadow-lg"
          >
            {groups.map((group) => (
              <div key={group.label} className="py-1">
                <p className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  {group.label}
                </p>
                {group.options.map((opt) => (
                  <button
                    key={opt.key}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      if (opt.pattern) onAddPattern(opt.pattern);
                      else if (opt.stepType) onAddType(opt.stepType);
                      setOpen(false);
                    }}
                    className="block w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
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
