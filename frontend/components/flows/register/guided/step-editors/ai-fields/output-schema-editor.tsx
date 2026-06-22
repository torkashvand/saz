'use client';

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { JsonObjectEditor } from '../../json-object-editor';
import {
  friendlyToSchema,
  schemaToFriendly,
  type FriendlyOutputField,
  type FriendlyOutputSchema,
  type OutputFieldType,
  type OutputScalarType,
} from '@/lib/flows/output-schema';

const FIELD_TYPE_OPTIONS: Array<{ value: OutputFieldType; label: string }> = [
  { value: 'string', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'integer', label: 'Whole number' },
  { value: 'boolean', label: 'Yes / no' },
  { value: 'array', label: 'List of values' },
];
const ITEM_TYPE_OPTIONS: Array<{ value: OutputScalarType; label: string }> = [
  { value: 'string', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'integer', label: 'Whole number' },
  { value: 'boolean', label: 'Yes / no' },
];

/**
 * Field-list editor for an AI step's `expect` JSON Schema. A supported schema
 * is edited as visual rows (name / type / required / enum / bounds /
 * description) and recompiled with `friendlyToSchema`; a raw `JsonObjectEditor`
 * stays behind an Advanced toggle. Anything outside the supported subset shows
 * a warning and the raw editor only, leaving the original schema untouched.
 */
export function OutputSchemaEditor({
  value,
  stepId,
  onChange,
}: {
  value: unknown;
  stepId: string;
  onChange: (next: unknown) => void;
}) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const parsed = schemaToFriendly(value);

  if (!parsed.supported) {
    return (
      <div className="space-y-2">
        <label className="block text-xs font-medium text-slate-600">Expected output</label>
        <div className="px-3 py-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-700">
          This output schema can&apos;t be shown in the visual editor (it uses advanced features).
          Edit the raw schema below — it is kept exactly as-is.
        </div>
        <JsonObjectEditor
          label="Expected output schema (raw)"
          value={value}
          onChange={onChange}
          testId={`step-${stepId}-expect`}
        />
      </div>
    );
  }

  const schema = parsed.schema;
  const emit = (next: FriendlyOutputSchema) => onChange(friendlyToSchema(next));

  const setField = (i: number, patch: Partial<FriendlyOutputField>) => {
    emit({ ...schema, fields: schema.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  };
  const addField = () => {
    const n = schema.fields.length + 1;
    emit({
      ...schema,
      fields: [...schema.fields, { name: `field_${n}`, type: 'string', required: false }],
    });
  };
  const removeField = (i: number) => {
    emit({ ...schema, fields: schema.fields.filter((_, j) => j !== i) });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-xs font-medium text-slate-600">Expected output fields</label>
        <button
          type="button"
          onClick={addField}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 rounded"
        >
          <Plus className="h-3.5 w-3.5" />
          Add field
        </button>
      </div>

      {schema.fields.length === 0 && (
        <p className="text-xs text-slate-500">No output fields yet.</p>
      )}

      {schema.fields.map((f, i) => {
        const isNumeric = f.type === 'number' || f.type === 'integer';
        const enumApplies = f.type !== 'boolean' && f.type !== 'array';
        return (
          <div key={i} className="border border-slate-200 rounded p-3 space-y-2 bg-white">
            <div className="flex items-center gap-2">
              <input
                type="text"
                aria-label={`Field name ${i + 1}`}
                value={f.name}
                onChange={(e) => setField(i, { name: e.target.value })}
                placeholder="field name"
                className="flex-1 px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <select
                aria-label={`Field type ${i + 1}`}
                value={f.type}
                onChange={(e) => setField(i, { type: e.target.value as OutputFieldType })}
                className="px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {FIELD_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              {f.type === 'array' && (
                <select
                  aria-label={`Item type ${i + 1}`}
                  value={f.itemType ?? 'string'}
                  onChange={(e) => setField(i, { itemType: e.target.value as OutputScalarType })}
                  className="px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {ITEM_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              )}
              <label className="flex items-center gap-1 text-xs text-slate-600">
                <input
                  type="checkbox"
                  aria-label={`Required ${i + 1}`}
                  checked={f.required}
                  onChange={(e) => setField(i, { required: e.target.checked })}
                />
                Required
              </label>
              <button
                type="button"
                onClick={() => removeField(i)}
                className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                aria-label={`Remove field ${i + 1}`}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>

            {enumApplies && (
              <input
                type="text"
                aria-label={`Allowed values ${i + 1}`}
                value={(f.enumValues ?? []).join(', ')}
                onChange={(e) => {
                  const items = e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean);
                  setField(i, { enumValues: items.length > 0 ? items : undefined });
                }}
                placeholder="Allowed values (comma-separated, optional)"
                className="w-full px-2 py-1 text-xs border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            )}

            {isNumeric && (
              <div className="flex gap-2">
                <input
                  type="number"
                  aria-label={`Minimum ${i + 1}`}
                  value={f.minimum ?? ''}
                  onChange={(e) =>
                    setField(i, {
                      minimum: e.target.value === '' ? undefined : Number(e.target.value),
                    })
                  }
                  placeholder="min"
                  className="w-24 px-2 py-1 text-xs border border-slate-300 rounded"
                />
                <input
                  type="number"
                  aria-label={`Maximum ${i + 1}`}
                  value={f.maximum ?? ''}
                  onChange={(e) =>
                    setField(i, {
                      maximum: e.target.value === '' ? undefined : Number(e.target.value),
                    })
                  }
                  placeholder="max"
                  className="w-24 px-2 py-1 text-xs border border-slate-300 rounded"
                />
              </div>
            )}

            {f.type === 'array' && (
              <div className="flex gap-2">
                <input
                  type="number"
                  aria-label={`Minimum items ${i + 1}`}
                  value={f.minItems ?? ''}
                  onChange={(e) =>
                    setField(i, {
                      minItems: e.target.value === '' ? undefined : Number(e.target.value),
                    })
                  }
                  placeholder="min items"
                  className="w-28 px-2 py-1 text-xs border border-slate-300 rounded"
                />
                <input
                  type="number"
                  aria-label={`Maximum items ${i + 1}`}
                  value={f.maxItems ?? ''}
                  onChange={(e) =>
                    setField(i, {
                      maxItems: e.target.value === '' ? undefined : Number(e.target.value),
                    })
                  }
                  placeholder="max items"
                  className="w-28 px-2 py-1 text-xs border border-slate-300 rounded"
                />
              </div>
            )}

            <input
              type="text"
              aria-label={`Description ${i + 1}`}
              value={f.description ?? ''}
              onChange={(e) => setField(i, { description: e.target.value || undefined })}
              placeholder="Description (optional)"
              className="w-full px-2 py-1 text-xs border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        );
      })}

      <label className="flex items-center gap-2 text-xs text-slate-600">
        <input
          type="checkbox"
          aria-label="Allow additional properties"
          checked={schema.additionalProperties}
          onChange={(e) => emit({ ...schema, additionalProperties: e.target.checked })}
        />
        Allow fields beyond those listed above
      </label>

      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-xs text-slate-600 hover:text-slate-900"
        >
          {showAdvanced ? 'Hide advanced' : 'Advanced (raw schema)'}
        </button>
        {showAdvanced && (
          <div className="mt-2 border-t border-slate-200 pt-3">
            <JsonObjectEditor
              label="Expected output schema (raw)"
              value={value}
              onChange={onChange}
              testId={`step-${stepId}-expect`}
            />
          </div>
        )}
      </div>
    </div>
  );
}
