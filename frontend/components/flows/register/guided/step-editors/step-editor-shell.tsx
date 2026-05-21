'use client';

import { useRef } from 'react';
import type { FlowDraft, WorkflowStepDraft } from '@/lib/flows/types';
import { ExpressionPicker } from '../expression-picker';

export interface StepEditorProps {
  step: WorkflowStepDraft;
  draft: FlowDraft;
  priorStepIds: string[];
  onChange: (updates: Partial<WorkflowStepDraft>) => void;
}

/**
 * Inline text input that pairs with an ExpressionPicker so users can
 * insert `{{ $form.x }}` style tokens without remembering syntax.
 */
export function ExpressionInput({
  step,
  draft,
  priorStepIds,
  value,
  onChange,
  placeholder,
  label,
  textarea = false,
  rows = 3,
  fieldKey,
}: {
  step: WorkflowStepDraft;
  draft: FlowDraft;
  priorStepIds: string[];
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  label: string;
  textarea?: boolean;
  rows?: number;
  fieldKey: string;
}) {
  const inputRef = useRef<HTMLTextAreaElement | HTMLInputElement | null>(null);

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="block text-xs font-medium text-slate-600">{label}</label>
        <ExpressionPicker
          inputRef={inputRef as React.RefObject<HTMLInputElement | HTMLTextAreaElement>}
          value={value}
          onChange={onChange}
          draft={draft}
          priorStepIds={priorStepIds}
          triggerLabel={`Insert expression into ${step.id} ${fieldKey}`}
        />
      </div>
      {textarea ? (
        <textarea
          ref={(el) => {
            inputRef.current = el;
          }}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={rows}
          className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder={placeholder}
        />
      ) : (
        <input
          ref={(el) => {
            inputRef.current = el;
          }}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-2 py-1.5 text-sm font-mono border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder={placeholder}
        />
      )}
    </div>
  );
}

export function StaticField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
        placeholder={placeholder}
      />
    </div>
  );
}
