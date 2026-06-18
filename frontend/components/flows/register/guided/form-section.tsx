'use client';

import { useEffect, useRef, useState } from 'react';
import type { FlowDraft, FlowFormField, FormFieldType } from '@/lib/flows/types';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { FIELD_TYPES } from '@/lib/flows/types';
import {
  FRIENDLY_FIELD_TYPES,
  applyFriendlyFieldType,
  deriveFieldKey,
  keyTracksLabel,
  toFriendlyFieldType,
  type FriendlyFieldType,
} from '@/lib/flows/intake-fields';
import { resolveStepMetadata } from '@/lib/flows/business-step-metadata';
import { GENERIC_PACK, getActiveDomainPack } from '@/lib/flows/domain-packs/registry';
import { ExpertModeToggle } from './expert-mode-toggle';

interface FormSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

const FORMAT_OPTIONS: ReadonlyArray<{ value: '' | 'email' | 'uri'; label: string }> = [
  { value: '', label: 'None' },
  { value: 'email', label: 'Email' },
  { value: 'uri', label: 'URI' },
];

export function FormSection({ draft, onChange }: FormSectionProps) {
  const fields = draft.form?.fields ?? [];
  const [expertMode, setExpertMode] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const [scrollToNewField, setScrollToNewField] = useState(false);

  // Bring a newly added field into view and focus its first control.
  useEffect(() => {
    if (!scrollToNewField) return;
    const row = listRef.current?.lastElementChild;
    if (row) {
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      (row.querySelector('input, select, textarea') as HTMLElement | null)?.focus({
        preventScroll: true,
      });
    }
    setScrollToNewField(false);
  }, [scrollToNewField]);

  // Generic flows keep the neutral "Form Fields" title. Only an opted-in domain
  // pack relabels the section (e.g. procurement → "Collect RFQ/RFP request…").
  const pack = getActiveDomainPack();
  const isDomainPack = pack.id !== GENERIC_PACK.id;
  const intakeMeta = resolveStepMetadata('intake_form', pack);

  const setFields = (next: FlowFormField[]) =>
    onChange({ form: next.length > 0 ? { fields: next } : undefined });

  const addField = () => {
    const newField: FlowFormField = {
      name: `field_${fields.length + 1}`,
      type: 'string',
      required: false,
    };
    setFields([...fields, newField]);
    setScrollToNewField(true);
  };

  const updateField = (index: number, updates: Partial<FlowFormField>) => {
    const updated = [...fields];
    updated[index] = { ...updated[index], ...updates };
    setFields(updated);
  };

  const replaceField = (index: number, next: FlowFormField) => {
    const updated = [...fields];
    updated[index] = next;
    setFields(updated);
  };

  const removeField = (index: number) => setFields(fields.filter((_, i) => i !== index));

  return (
    <div id="form" className="bg-white border border-slate-200 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            {!expertMode && isDomainPack ? intakeMeta.friendlyLabel : 'Form Fields'}
          </h2>
          {!expertMode && isDomainPack && (
            <p className="mt-0.5 text-xs text-slate-500">{intakeMeta.description}</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <ExpertModeToggle expert={expertMode} onChange={setExpertMode} />
          <Button size="sm" onClick={addField}>
            <Plus className="h-4 w-4 mr-1" />
            Add Field
          </Button>
        </div>
      </div>

      {fields.length === 0 ? (
        <p className="text-sm text-slate-500 text-center py-8">
          No form fields defined. Click &quot;Add Field&quot; to create one.
        </p>
      ) : (
        <div ref={listRef} className="space-y-3">
          {fields.map((field, idx) =>
            expertMode ? (
              <FormFieldRow
                key={idx}
                field={field}
                onChange={(updates) => updateField(idx, updates)}
                onRemove={() => removeField(idx)}
              />
            ) : (
              <BusinessFieldRow
                key={idx}
                field={field}
                onChange={(next) => replaceField(idx, next)}
                onRemove={() => removeField(idx)}
              />
            ),
          )}
        </div>
      )}
    </div>
  );
}

interface BusinessFieldRowProps {
  field: FlowFormField;
  onChange: (next: FlowFormField) => void;
  onRemove: () => void;
}

/**
 * Friendly intake-field editor. Presents a plain-language label, an
 * auto-generated key, a friendly type, required toggle and help text — never
 * raw JSON schema. Edits map onto FlowFormField via the intake-fields helpers
 * so the generated YAML stays valid.
 */
function BusinessFieldRow({ field, onChange, onRemove }: BusinessFieldRowProps) {
  const label = field.title ?? '';
  const friendlyType = toFriendlyFieldType(field);
  const choices = (field.enum ?? []).map((v) => String(v)).join(', ');

  const onLabelChange = (nextLabel: string) => {
    const next: FlowFormField = { ...field, title: nextLabel };
    // Keep the key in sync with the label until the user customises the key.
    if (keyTracksLabel(field)) {
      next.name = deriveFieldKey(nextLabel) || field.name;
    }
    onChange(next);
  };

  return (
    <div className="border border-slate-200 rounded-md p-4 space-y-3">
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-4">
          <label className="block text-xs font-medium text-slate-600 mb-1">Label</label>
          <input
            type="text"
            aria-label="Field label"
            value={label}
            onChange={(e) => onLabelChange(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="What are you asking for?"
          />
        </div>

        <div className="col-span-3">
          <label className="block text-xs font-medium text-slate-600 mb-1">Field key</label>
          <input
            type="text"
            aria-label="Field key"
            value={field.name}
            onChange={(e) => onChange({ ...field, name: e.target.value })}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="col-span-3">
          <label className="block text-xs font-medium text-slate-600 mb-1">Type</label>
          <select
            aria-label="Field type"
            value={friendlyType}
            onChange={(e) =>
              onChange(applyFriendlyFieldType(field, e.target.value as FriendlyFieldType))
            }
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {FRIENDLY_FIELD_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>

        <div className="col-span-1 flex items-end pb-1.5">
          <label className="flex items-center gap-1.5 cursor-pointer whitespace-nowrap">
            <input
              type="checkbox"
              checked={field.required === true}
              onChange={(e) => onChange({ ...field, required: e.target.checked })}
              className="rounded"
            />
            <span className="text-xs text-slate-600">Required</span>
          </label>
        </div>

        <div className="col-span-1 flex items-end justify-end">
          <button
            onClick={onRemove}
            aria-label={`Remove field ${field.title || field.name}`}
            className="p-1.5 text-red-600 hover:bg-red-50 rounded"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-3">
        <div className={friendlyType === 'choice' ? 'col-span-6' : 'col-span-12'}>
          <label className="block text-xs font-medium text-slate-600 mb-1">Help text</label>
          <input
            type="text"
            aria-label="Help text"
            value={field.description || ''}
            onChange={(e) => onChange({ ...field, description: e.target.value || undefined })}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Shown to the requester (optional)"
          />
        </div>

        {friendlyType === 'choice' && (
          <div className="col-span-6">
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Choices (comma-separated)
            </label>
            <input
              type="text"
              aria-label="Choices"
              value={choices}
              onChange={(e) => {
                const items = e.target.value
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean);
                onChange({ ...field, enum: items });
              }}
              className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="low, medium, high"
            />
          </div>
        )}
      </div>
    </div>
  );
}

interface FormFieldRowProps {
  field: FlowFormField;
  onChange: (updates: Partial<FlowFormField>) => void;
  onRemove: () => void;
}

function FormFieldRow({ field, onChange, onRemove }: FormFieldRowProps) {
  const isNumeric = field.type === 'number' || field.type === 'integer';
  const isTextual = field.type === 'string' || field.type === 'text';
  const enumDraft = (field.enum || []).join(', ');

  return (
    <div className="border border-slate-200 rounded-md p-4 space-y-3">
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-3">
          <label className="block text-xs font-medium text-slate-600 mb-1">Name</label>
          <input
            type="text"
            value={field.name}
            onChange={(e) => onChange({ name: e.target.value })}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="col-span-2">
          <label className="block text-xs font-medium text-slate-600 mb-1">Type</label>
          <select
            value={field.type}
            onChange={(e) => onChange({ type: e.target.value as FormFieldType })}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {FIELD_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>

        <div className="col-span-2 flex items-end pb-1.5">
          <label className="flex items-center gap-1.5 cursor-pointer whitespace-nowrap">
            <input
              type="checkbox"
              checked={field.required === true}
              onChange={(e) => onChange({ required: e.target.checked })}
              className="rounded"
            />
            <span className="text-xs text-slate-600">Required</span>
          </label>
        </div>

        <div className="col-span-4">
          <label className="block text-xs font-medium text-slate-600 mb-1">Description</label>
          <input
            type="text"
            value={field.description || ''}
            onChange={(e) => onChange({ description: e.target.value })}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Field description..."
          />
        </div>

        <div className="col-span-1 flex items-end justify-end">
          <button
            onClick={onRemove}
            aria-label={`Remove field ${field.name}`}
            className="p-1.5 text-red-600 hover:bg-red-50 rounded"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <details className="text-xs">
        <summary className="cursor-pointer text-slate-600 hover:text-slate-900">
          Constraints
        </summary>
        <div className="mt-2 grid grid-cols-12 gap-3">
          <div className="col-span-4">
            <label className="block text-xs font-medium text-slate-600 mb-1">Default</label>
            <input
              type="text"
              value={field.default === undefined ? '' : String(field.default)}
              onChange={(e) =>
                onChange({ default: e.target.value === '' ? undefined : e.target.value })
              }
              className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
              placeholder="(none)"
            />
          </div>

          {isTextual && (
            <div className="col-span-4">
              <label className="block text-xs font-medium text-slate-600 mb-1">Format</label>
              <select
                value={field.format || ''}
                onChange={(e) =>
                  onChange({ format: (e.target.value || undefined) as FlowFormField['format'] })
                }
                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
              >
                {FORMAT_OPTIONS.map((opt) => (
                  <option key={opt.value || 'none'} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {isTextual && (
            <div className="col-span-12 grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Min length</label>
                <input
                  type="number"
                  min={0}
                  value={field.minLength ?? ''}
                  onChange={(e) =>
                    onChange({
                      minLength: e.target.value === '' ? undefined : parseInt(e.target.value, 10),
                    })
                  }
                  className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Max length</label>
                <input
                  type="number"
                  min={0}
                  value={field.maxLength ?? ''}
                  onChange={(e) =>
                    onChange({
                      maxLength: e.target.value === '' ? undefined : parseInt(e.target.value, 10),
                    })
                  }
                  className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                />
              </div>
            </div>
          )}

          {isTextual && (
            <div className="col-span-12">
              <label className="block text-xs font-medium text-slate-600 mb-1">Pattern</label>
              <input
                type="text"
                value={field.pattern || ''}
                onChange={(e) =>
                  onChange({ pattern: e.target.value === '' ? undefined : e.target.value })
                }
                className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded font-mono"
                placeholder="^[A-Z]+$"
              />
            </div>
          )}

          {isNumeric && (
            <div className="col-span-12 grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Minimum</label>
                <input
                  type="number"
                  value={field.minimum ?? ''}
                  onChange={(e) =>
                    onChange({
                      minimum: e.target.value === '' ? undefined : Number(e.target.value),
                    })
                  }
                  className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Maximum</label>
                <input
                  type="number"
                  value={field.maximum ?? ''}
                  onChange={(e) =>
                    onChange({
                      maximum: e.target.value === '' ? undefined : Number(e.target.value),
                    })
                  }
                  className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
                />
              </div>
            </div>
          )}

          <div className="col-span-12">
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Allowed values (comma-separated)
            </label>
            <input
              type="text"
              value={enumDraft}
              onChange={(e) => {
                const trimmed = e.target.value.trim();
                if (!trimmed) {
                  onChange({ enum: undefined });
                  return;
                }
                const items = e.target.value
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean);
                onChange({ enum: items.length > 0 ? items : undefined });
              }}
              className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded"
              placeholder="low, medium, high"
            />
          </div>
        </div>
      </details>
    </div>
  );
}
