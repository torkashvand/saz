'use client';

import {
  renderBindingLabel,
  validateBinding,
  type BindingContext,
  type BindingSourceType,
  type FriendlyBinding,
} from '@/lib/flows/bindings';

interface BindingPickerProps {
  label: string;
  binding: FriendlyBinding | null;
  context: BindingContext;
  onChange: (binding: FriendlyBinding) => void;
  required?: boolean;
}

const SOURCE_OPTIONS: Array<{ value: BindingSourceType; label: string }> = [
  { value: 'form', label: 'Intake form field' },
  { value: 'previous_step', label: 'Output from an earlier step' },
  { value: 'constant', label: 'Fixed value' },
  { value: 'system', label: 'System value' },
];

/**
 * Lets a business user pick where a value comes from — a form field, an
 * earlier step's output, or a fixed value — without ever typing a template
 * expression. The selection is shown as a readable chip; the compiled
 * `{{ ... }}` syntax stays hidden behind the friendly model.
 */
export function BindingPicker({ label, binding, context, onChange, required }: BindingPickerProps) {
  const current: FriendlyBinding = binding ?? { sourceType: 'form', sourceField: '' };
  const validation = validateBinding({ ...current, required }, context);

  const setSourceType = (sourceType: BindingSourceType) => {
    onChange({ sourceType, sourceField: '' });
  };

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
            validation.valid ? 'bg-blue-50 text-blue-700' : 'bg-amber-50 text-amber-700'
          }`}
        >
          {binding ? renderBindingLabel(current, context) : 'Not set'}
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        <select
          aria-label={`Source for ${label}`}
          value={current.sourceType}
          onChange={(e) => setSourceType(e.target.value as BindingSourceType)}
          className="px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {SOURCE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        {current.sourceType === 'form' && (
          <select
            aria-label={`Form field for ${label}`}
            value={current.sourceField}
            onChange={(e) => onChange({ sourceType: 'form', sourceField: e.target.value })}
            className="flex-1 min-w-[10rem] px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Choose a field…</option>
            {(context.formFields ?? []).map((f) => (
              <option key={f.name} value={f.name}>
                {f.title || f.name}
              </option>
            ))}
          </select>
        )}

        {current.sourceType === 'previous_step' && (
          <>
            <select
              aria-label={`Step for ${label}`}
              value={current.sourceStepId ?? ''}
              onChange={(e) =>
                onChange({
                  sourceType: 'previous_step',
                  sourceStepId: e.target.value,
                  sourceField: current.sourceField,
                })
              }
              className="px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Choose a step…</option>
              {(context.steps ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name || s.id}
                </option>
              ))}
            </select>
            <input
              type="text"
              aria-label={`Output field for ${label}`}
              value={current.sourceField}
              onChange={(e) =>
                onChange({
                  sourceType: 'previous_step',
                  sourceStepId: current.sourceStepId,
                  sourceField: e.target.value,
                })
              }
              placeholder="output field (optional)"
              className="flex-1 min-w-[8rem] px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </>
        )}

        {current.sourceType === 'constant' && (
          <input
            type="text"
            aria-label={`Fixed value for ${label}`}
            value={current.sourceField}
            onChange={(e) => onChange({ sourceType: 'constant', sourceField: e.target.value })}
            placeholder="Type a fixed value"
            className="flex-1 min-w-[10rem] px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        )}

        {current.sourceType === 'system' && (
          <>
            <input
              type="text"
              aria-label={`System value for ${label}`}
              value={current.sourceField}
              onChange={(e) =>
                onChange({
                  sourceType: 'system',
                  sourceField: e.target.value,
                  fallback: current.fallback,
                })
              }
              placeholder="environment variable name"
              className="flex-1 min-w-[10rem] px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <input
              type="text"
              aria-label={`Fallback for ${label}`}
              value={current.fallback ?? ''}
              onChange={(e) =>
                onChange({
                  sourceType: 'system',
                  sourceField: current.sourceField,
                  fallback: e.target.value || undefined,
                })
              }
              placeholder="fallback (optional)"
              className="min-w-[8rem] px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </>
        )}
      </div>

      {current.sourceType === 'system' && (
        <p className="text-xs text-slate-400">
          Uses an environment value. Current date, run ID and current user aren&apos;t available
          yet.
        </p>
      )}

      {!validation.valid && validation.message && (
        <p className="text-xs text-amber-700">{validation.message}</p>
      )}
    </div>
  );
}
