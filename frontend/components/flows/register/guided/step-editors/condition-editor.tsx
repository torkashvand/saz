'use client';

import type { StepEditorProps } from './step-editor-shell';
import { ExpressionInput } from './step-editor-shell';

export function ConditionEditor({ step, draft, priorStepIds, onChange }: StepEditorProps) {
  return (
    <div className="space-y-3">
      <ExpressionInput
        step={step}
        draft={draft}
        priorStepIds={priorStepIds}
        value={step.if || ''}
        onChange={(next) => onChange({ if: next })}
        label="If expression"
        fieldKey="if"
        placeholder="{{ $step('classify').escalation_required }}"
      />
      <p className="text-xs text-slate-500">
        Boolean template expression. The step runs only when this evaluates truthy.
      </p>
    </div>
  );
}
