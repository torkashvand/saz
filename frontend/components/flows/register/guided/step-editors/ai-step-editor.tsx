'use client';

import type { StepEditorProps } from './step-editor-shell';
import { ExpressionInput } from './step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';

const LOCALE_FRIENDLY_TYPES = new Set([
  'ai.extract',
  'ai.generate',
  'ai.route',
  'ai.score',
  'ai.assess',
  'ai.normalize',
  'ai.match',
  'ai.evaluate',
  'ai.compare',
  'ai.translate',
  'ai.summarize',
  'ai.plan',
]);

/**
 * Shared editor for every `ai.*` step. AI ops all use the same fields
 * (instruction + params.data + expect + temperature + max_tokens) plus a
 * handful of type-specific extras (branches_enum, word_cap, target_locale,
 * top_k, tools_allowlist).
 */
export function AiStepEditor({ step, draft, priorStepIds, onChange }: StepEditorProps) {
  if (!LOCALE_FRIENDLY_TYPES.has(step.type)) return null;

  const extras = step.extras ?? {};

  const setExtra = (key: string, value: unknown) => {
    const next = { ...extras };
    if (value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) {
      delete next[key];
    } else {
      next[key] = value;
    }
    onChange({ extras: Object.keys(next).length > 0 ? next : undefined });
  };

  return (
    <div className="space-y-3">
      <ExpressionInput
        step={step}
        draft={draft}
        priorStepIds={priorStepIds}
        value={step.instruction || ''}
        onChange={(next) => onChange({ instruction: next })}
        label="Instruction"
        textarea
        rows={4}
        fieldKey="instruction"
        placeholder="What the model should do."
      />

      <JsonObjectEditor
        label="Input data (params.data)"
        value={step.params}
        onChange={(next) =>
          onChange({
            params: next === undefined ? undefined : (next as Record<string, unknown>),
          })
        }
        placeholder='{ "data": { "x": "{{ $form.x }}" } }'
        testId={`step-${step.id}-params`}
      />

      <JsonObjectEditor
        label="Expected output schema"
        value={step.expect}
        onChange={(next) => onChange({ expect: next })}
        placeholder='{ "type": "object", "properties": { "ok": { "type": "boolean" } }, "required": ["ok"] }'
        testId={`step-${step.id}-expect`}
      />

      {step.type === 'ai.route' && (
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">
            Branches (comma-separated)
          </label>
          <input
            type="text"
            value={(step.branches_enum || []).join(', ')}
            onChange={(e) => {
              const items = e.target.value
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean);
              onChange({ branches_enum: items.length > 0 ? items : undefined });
            }}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
            placeholder="approve, reject, escalate"
          />
        </div>
      )}

      {step.type === 'ai.translate' && (
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Target locale</label>
          <input
            type="text"
            value={typeof extras.target_locale === 'string' ? extras.target_locale : ''}
            onChange={(e) => setExtra('target_locale', e.target.value)}
            className="w-full px-2 py-1.5 text-sm font-mono border border-slate-300 rounded"
            placeholder="fr-FR"
          />
        </div>
      )}

      {step.type === 'ai.match' && (
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Top-k matches</label>
          <input
            type="number"
            min={1}
            value={typeof extras.top_k === 'number' ? extras.top_k : ''}
            onChange={(e) =>
              setExtra('top_k', e.target.value === '' ? undefined : parseInt(e.target.value, 10))
            }
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
            placeholder="3"
          />
        </div>
      )}

      {step.type === 'ai.plan' && (
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">
            Tools allowlist (comma-separated)
          </label>
          <input
            type="text"
            value={Array.isArray(extras.tools_allowlist) ? extras.tools_allowlist.join(', ') : ''}
            onChange={(e) => {
              const items = e.target.value
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean);
              setExtra('tools_allowlist', items.length > 0 ? items : undefined);
            }}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
            placeholder="http_request, artifact.store"
          />
        </div>
      )}

      {(step.type === 'ai.summarize' || step.type === 'ai.generate') && (
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Word cap</label>
          <input
            type="number"
            min={1}
            value={step.word_cap ?? ''}
            onChange={(e) =>
              onChange({
                word_cap: e.target.value === '' ? undefined : parseInt(e.target.value, 10),
              })
            }
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
            placeholder="120"
          />
        </div>
      )}
    </div>
  );
}
