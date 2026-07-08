'use client';

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { BindingPicker } from '../binding-picker';
import {
  bindingToExpression,
  expressionToBinding,
  type BindingContext,
  type FriendlyBinding,
} from '@/lib/flows/bindings';

/**
 * Read a params sub-object as a friendly string→expression map. `supported`
 * is false when any value is a non-string (nested object/array/number), which
 * MappingRows can't represent — callers fall back to the raw JSON editor so
 * that data is preserved rather than coerced to '' and destroyed on edit.
 */
export function readStringMap(value: unknown): {
  supported: boolean;
  values: Record<string, string>;
} {
  if (value === undefined || value === null) return { supported: true, values: {} };
  if (typeof value !== 'object' || Array.isArray(value)) return { supported: false, values: {} };
  const values: Record<string, string> = {};
  let supported = true;
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    if (typeof v === 'string') values[k] = v;
    else supported = false;
  }
  return { supported, values };
}

interface MappingRowsProps {
  /** Map of document/record field name -> compiled expression. */
  values: Record<string, string>;
  context: BindingContext;
  onChange: (next: Record<string, string>) => void;
  addLabel?: string;
  namePlaceholder?: string;
}

/**
 * Reusable "field name → where the value comes from" list. Each value is held
 * as a compiled expression but edited through a BindingPicker, so a business
 * user never sees `{{ ... }}`. Used by the document, audit, and approval
 * editors for their params.values / content / payload maps.
 */
export function MappingRows({
  values,
  context,
  onChange,
  addLabel = 'Add field mapping',
  namePlaceholder = 'Document field name',
}: MappingRowsProps) {
  const entries = Object.entries(values);

  // Key renames are edited in a local draft and committed on blur. Renaming
  // live on every keystroke would, while typing THROUGH an existing key (e.g.
  // "vendor" en route to "vendor_name"), momentarily collide and drop the
  // other mapping via Object.fromEntries dedupe.
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({});

  const commitKey = (oldKey: string) => {
    const draft = keyDrafts[oldKey];
    setKeyDrafts((d) => {
      const next = { ...d };
      delete next[oldKey];
      return next;
    });
    if (draft === undefined) return;
    const newKey = draft.trim();
    // Reject empty or colliding names — revert to the original silently.
    if (!newKey || newKey === oldKey || newKey in values) return;
    onChange(
      Object.fromEntries(
        Object.entries(values).map(([k, v]) => (k === oldKey ? [newKey, v] : [k, v])),
      ),
    );
  };

  const setBinding = (key: string, binding: FriendlyBinding) => {
    onChange({ ...values, [key]: bindingToExpression(binding) });
  };

  const remove = (key: string) => {
    const next = { ...values };
    delete next[key];
    onChange(next);
  };

  const add = () => {
    let n = entries.length + 1;
    let key = `field_${n}`;
    while (key in values) key = `field_${++n}`;
    onChange({ ...values, [key]: '' });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {entries.length === 0
            ? 'No fields mapped yet.'
            : `${entries.length} ${entries.length === 1 ? 'field' : 'fields'} mapped.`}
        </p>
        <button
          type="button"
          onClick={add}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 rounded"
        >
          <Plus className="h-3.5 w-3.5" />
          {addLabel}
        </button>
      </div>

      {entries.map(([key, expr], i) => (
        <div key={key} className="border border-slate-200 rounded p-3 space-y-2 bg-white">
          <div className="flex items-center gap-2">
            <input
              type="text"
              aria-label={`Field name for mapping ${i + 1}`}
              value={keyDrafts[key] ?? key}
              onChange={(e) => setKeyDrafts((d) => ({ ...d, [key]: e.target.value }))}
              onBlur={() => commitKey(key)}
              placeholder={namePlaceholder}
              className="flex-1 px-2 py-1 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="button"
              onClick={() => remove(key)}
              className="p-1.5 text-red-600 hover:bg-red-50 rounded"
              aria-label={`Remove mapping ${i + 1}`}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
          <BindingPicker
            label={`mapping ${i + 1}`}
            binding={expr ? expressionToBinding(expr) : null}
            context={context}
            onChange={(b) => setBinding(key, b)}
          />
        </div>
      ))}
    </div>
  );
}
