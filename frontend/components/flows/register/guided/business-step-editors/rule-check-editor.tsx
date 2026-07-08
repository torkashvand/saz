'use client';

import { useState } from 'react';
import type { StepEditorProps } from '../step-editors/step-editor-shell';
import { StaticField } from '../step-editors/step-editor-shell';
import { BindingPicker } from '../binding-picker';
import { bindingContextFor } from '@/lib/flows/business-step-metadata';
import {
  bindingToExpression,
  expressionToBinding,
  type FriendlyBinding,
} from '@/lib/flows/bindings';

const OPERATORS: Array<{ value: string; label: string }> = [
  { value: '==', label: 'is equal to' },
  { value: '!=', label: 'is not equal to' },
  { value: '>', label: 'is greater than' },
  { value: '<', label: 'is less than' },
  { value: '>=', label: 'is at least' },
  { value: '<=', label: 'is at most' },
];

const IF_RE = /^\{\{\s*(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*\}\}$/;

interface ParsedRule {
  subject: FriendlyBinding | null;
  operator: string;
  value: string;
}

function parseRule(ifStr: string | undefined): ParsedRule | null {
  if (!ifStr) return { subject: null, operator: '==', value: '' };
  const m = ifStr.match(IF_RE);
  if (!m) return null; // advanced / unsupported condition
  return {
    subject: expressionToBinding(`{{ ${m[1]} }}`),
    operator: m[2],
    value: m[3],
  };
}

function innerExpression(binding: FriendlyBinding): string {
  return bindingToExpression(binding)
    .replace(/^\{\{\s*/, '')
    .replace(/\s*\}\}$/, '');
}

/**
 * Friendly editor for "Rule check" steps (condition).
 *
 * Builds a simple "subject / comparison / value" rule and compiles it to the
 * `if` boolean expression — no raw boolean syntax in the default UI. Complex
 * hand-written conditions fall back to an advanced raw editor.
 */
export function RuleCheckEditor({ step, draft, priorStepIds, onChange }: StepEditorProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const parsed = parseRule(step.if);

  const context = bindingContextFor(draft.form?.fields, priorStepIds, draft.workflow.steps);

  const compile = (rule: ParsedRule) => {
    if (!rule.subject || !rule.subject.sourceField) {
      onChange({ if: undefined });
      return;
    }
    onChange({ if: `{{ ${innerExpression(rule.subject)} ${rule.operator} ${rule.value} }}` });
  };

  return (
    <div className="space-y-4">
      <StaticField
        label="Check name"
        value={step.description ?? ''}
        onChange={(next) => onChange({ description: next || undefined })}
        placeholder="e.g. Market consultation requested"
      />

      {parsed ? (
        <div className="space-y-2">
          <label className="block text-xs font-medium text-slate-600">Run this step when…</label>
          <BindingPicker
            label="rule subject"
            binding={parsed.subject}
            context={context}
            onChange={(b) => compile({ ...parsed, subject: b })}
          />
          <div className="flex flex-wrap gap-2">
            <select
              aria-label="Comparison"
              value={parsed.operator}
              onChange={(e) => compile({ ...parsed, operator: e.target.value })}
              className="px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {OPERATORS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <input
              type="text"
              aria-label="Comparison value"
              value={parsed.value}
              onChange={(e) => compile({ ...parsed, value: e.target.value })}
              placeholder="e.g. true"
              className="flex-1 min-w-[8rem] px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
      ) : (
        <p className="px-3 py-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-700">
          This check uses an advanced condition. Edit it below in advanced mode.
        </p>
      )}

      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-xs text-slate-600 hover:text-slate-900"
        >
          {showAdvanced ? 'Hide advanced' : 'Advanced (technical settings)'}
        </button>
        {showAdvanced && (
          <div className="mt-2 border-t border-slate-200 pt-3">
            <StaticField
              label="Condition (raw)"
              value={step.if ?? ''}
              onChange={(next) => onChange({ if: next || undefined })}
              placeholder="{{ $form.field == true }}"
            />
          </div>
        )}
      </div>
    </div>
  );
}
