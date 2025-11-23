'use client';

import type { FlowDraft, FlowFormField } from '@/lib/flows/types';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { FIELD_TYPES } from '@/lib/flows/types';

interface FormSectionProps {
  draft: FlowDraft;
  onChange: (updates: Partial<FlowDraft>) => void;
}

export function FormSection({ draft, onChange }: FormSectionProps) {
  const addField = () => {
    const newField: FlowFormField = {
      name: `field_${draft.form_fields.length + 1}`,
      type: 'string',
      required: false,
    };
    onChange({ form_fields: [...draft.form_fields, newField] });
  };

  const updateField = (index: number, updates: Partial<FlowFormField>) => {
    const updated = [...draft.form_fields];
    updated[index] = { ...updated[index], ...updates };
    onChange({ form_fields: updated });
  };

  const removeField = (index: number) => {
    onChange({ form_fields: draft.form_fields.filter((_, i) => i !== index) });
  };

  return (
    <div id="form" className="bg-white border border-slate-200 rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-slate-900">Form Fields</h2>
        <Button size="sm" onClick={addField}>
          <Plus className="h-4 w-4 mr-1" />
          Add Field
        </Button>
      </div>

      {draft.form_fields.length === 0 ? (
        <p className="text-sm text-slate-500 text-center py-8">
          No form fields defined. Click &quot;Add Field&quot; to create one.
        </p>
      ) : (
        <div className="space-y-3">
          {draft.form_fields.map((field, idx) => (
            <div key={idx} className="border border-slate-200 rounded-md p-4">
              <div className="grid grid-cols-12 gap-3">
                <div className="col-span-3">
                  <label className="block text-xs font-medium text-slate-600 mb-1">Name</label>
                  <input
                    type="text"
                    value={field.name}
                    onChange={(e) => updateField(idx, { name: e.target.value })}
                    className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>

                <div className="col-span-2">
                  <label className="block text-xs font-medium text-slate-600 mb-1">Type</label>
                  <select
                    value={field.type}
                    onChange={(e) => updateField(idx, { type: e.target.value as any })}
                    className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {FIELD_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="col-span-1 flex items-end">
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={field.required}
                      onChange={(e) => updateField(idx, { required: e.target.checked })}
                      className="rounded"
                    />
                    <span className="text-xs text-slate-600">Required</span>
                  </label>
                </div>

                <div className="col-span-5">
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    Description
                  </label>
                  <input
                    type="text"
                    value={field.description || ''}
                    onChange={(e) => updateField(idx, { description: e.target.value })}
                    className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="Field description..."
                  />
                </div>

                <div className="col-span-1 flex items-end justify-end">
                  <button
                    onClick={() => removeField(idx)}
                    className="p-1.5 text-red-600 hover:bg-red-50 rounded"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
