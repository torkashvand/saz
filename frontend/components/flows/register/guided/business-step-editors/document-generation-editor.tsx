'use client';

import { useState } from 'react';
import type { StepEditorProps } from '../step-editors/step-editor-shell';
import { StaticField } from '../step-editors/step-editor-shell';
import { JsonObjectEditor } from '../json-object-editor';
import { BindingPicker } from '../binding-picker';
import { MappingRows, readStringMap } from './mapping-rows';
import { DocumentConfigPreview } from './document-config-preview';
import { getActiveDomainPack } from '@/lib/flows/domain-packs/registry';
import { getFieldLabel, getFieldOptions } from '@/lib/flows/business-step-metadata';
import {
  bindingToExpression,
  expressionToBinding,
  type BindingContext,
  type FriendlyBinding,
} from '@/lib/flows/bindings';

function asParams(step: StepEditorProps['step']): Record<string, unknown> {
  return (step.params as Record<string, unknown>) ?? {};
}

/**
 * Friendly editor for document-generation steps (tool.call → docx_render).
 *
 * It exposes document purpose, template, output name, and the template field
 * mappings as binding chips — never raw params JSON or template expressions.
 * Labels and the purpose options are pulled from the generic business-step
 * metadata (overridable per DomainPack), so the component itself stays generic.
 * Everything compiles down into the existing docx_render params object, so the
 * generated YAML is unchanged. A collapsed advanced section keeps the raw
 * params editable for experts.
 */
export function DocumentGenerationEditor({ step, draft, priorStepIds, onChange }: StepEditorProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const params = asParams(step);
  const { supported: valuesSupported, values } = readStringMap(params.values);

  const context: BindingContext = {
    formFields: draft.form?.fields ?? [],
    steps: priorStepIds.map((id) => ({
      id,
      name: draft.workflow.steps.find((s) => s.id === id)?.name,
    })),
  };

  const setParam = (key: string, value: unknown) => {
    const next = { ...params };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange({ params: next });
  };

  const setValues = (next: Record<string, string>) => setParam('values', next);

  // Domain pack supplies template presets and field labels; the editor itself
  // stays generic (works with any pack, including GENERIC_PACK).
  const pack = getActiveDomainPack();
  const presets = pack.templatePresets ?? [];
  const purposeLabel = getFieldLabel('document_generation', 'params.require_all', pack);
  const purposeOptions = getFieldOptions('document_generation', 'params.require_all');
  const templateLabel = getFieldLabel('document_generation', 'params.template', pack);
  const outputLabel = getFieldLabel('document_generation', 'params.output_name', pack);

  const purpose: 'draft' | 'final' = params.require_all === true ? 'final' : 'draft';
  const template = typeof params.template === 'string' ? params.template : '';
  const templateIsPreset = presets.some((p) => p.value === template);

  const mappingCount = Object.keys(values).length;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">{purposeLabel}</label>
          <select
            aria-label={purposeLabel}
            value={purpose}
            onChange={(e) => setParam('require_all', e.target.value === 'final')}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {purposeOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">{templateLabel}</label>
          <select
            aria-label={templateLabel}
            value={templateIsPreset ? template : 'custom'}
            onChange={(e) => {
              if (e.target.value === 'custom') return;
              setParam('template', e.target.value);
            }}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {presets.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
            <option value="custom">Custom (set in advanced)</option>
          </select>
        </div>
      </div>

      <OutputNameField
        label={outputLabel}
        value={typeof params.output_name === 'string' ? params.output_name : ''}
        context={context}
        onChange={(next) => setParam('output_name', next || undefined)}
      />

      <DocumentConfigPreview
        step={step}
        templateDisplay={presets.find((p) => p.value === template)?.label ?? template}
      />

      <div>
        <h4 className="text-sm font-medium text-slate-800 mb-2">
          Field mappings{mappingCount > 0 ? ` (${mappingCount})` : ''}
        </h4>
        {valuesSupported ? (
          <MappingRows values={values} context={context} onChange={setValues} />
        ) : (
          <JsonObjectEditor
            label="Field mappings (raw)"
            value={params.values}
            onChange={(next) => setParam('values', next)}
            testId={`step-${step.id}-values`}
          />
        )}
      </div>

      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-xs text-slate-600 hover:text-slate-900"
        >
          {showAdvanced ? 'Hide advanced' : 'Advanced (technical settings)'}
        </button>
        {showAdvanced && (
          <div className="mt-2 space-y-3 border-t border-slate-200 pt-3">
            <StaticField
              label="Template (raw)"
              value={template}
              onChange={(next) => setParam('template', next || undefined)}
              placeholder="path or {{ $env('...') }}"
            />
            <JsonObjectEditor
              label="All document params (raw)"
              value={step.params}
              onChange={(next) =>
                onChange({
                  params: next === undefined ? undefined : (next as Record<string, unknown>),
                })
              }
              testId={`step-${step.id}-params`}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function OutputNameField({
  label,
  value,
  context,
  onChange,
}: {
  label: string;
  value: string;
  context: BindingContext;
  onChange: (next: string) => void;
}) {
  const idx = value.indexOf('{{');
  const prefix = idx === -1 ? value : value.slice(0, idx);
  const ref = idx === -1 ? null : expressionToBinding(value.slice(idx));

  const compile = (nextPrefix: string, nextRef: FriendlyBinding | null) => {
    onChange(`${nextPrefix}${nextRef ? bindingToExpression(nextRef) : ''}`);
  };

  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-slate-600">{label}</label>
      <input
        type="text"
        aria-label={label}
        value={prefix}
        onChange={(e) => compile(e.target.value, ref)}
        placeholder="e.g. rfq_draft_"
        className="w-full px-2 py-1.5 text-sm border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <div>
        <span className="block text-xs text-slate-500 mb-1">Append a reference (optional)</span>
        <BindingPicker
          label="file name reference"
          binding={ref}
          context={context}
          onChange={(b) => compile(prefix, b)}
        />
      </div>
    </div>
  );
}
