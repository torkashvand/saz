'use client';

import type { WorkflowStepDraft } from '@/lib/flows/types';

function params(step: WorkflowStepDraft): Record<string, unknown> {
  return (step.params as Record<string, unknown>) ?? {};
}

function values(step: WorkflowStepDraft): Record<string, string> {
  const raw = params(step).values;
  if (!raw || typeof raw !== 'object') return {};
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    out[k] = typeof v === 'string' ? v : '';
  }
  return out;
}

/** Human-readable output-name without exposing template expressions. */
function readableFilename(step: WorkflowStepDraft): string {
  const name = params(step).output_name;
  if (typeof name !== 'string' || !name) return 'Not set';
  const idx = name.indexOf('{{');
  if (idx === -1) return name;
  const prefix = name.slice(0, idx).trim();
  return prefix ? `${prefix}… (+ reference)` : '(reference)';
}

/**
 * Frontend-only "configuration preview" for a document-generation step. It
 * summarises what the step is configured to produce and which mappings still
 * need a value. It does NOT render a real document — there is no backend
 * preview endpoint — so it is explicitly a configuration preview.
 */
export function DocumentConfigPreview({
  step,
  templateLabel,
}: {
  step: WorkflowStepDraft;
  templateLabel: string;
}) {
  const p = params(step);
  const v = values(step);
  const entries = Object.entries(v);
  const missing = entries.filter(([, expr]) => !expr || expr === '').map(([k]) => k);
  const purpose = p.require_all === true ? 'Final' : 'Draft';
  const hasTemplate = typeof p.template === 'string' && p.template.length > 0;
  const titleKey = Object.keys(v).find((k) => /title/i.test(k));

  return (
    <section
      aria-label="Configuration preview"
      className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700"
    >
      <h4 className="mb-2 text-sm font-medium text-slate-800">Configuration preview</h4>
      <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1">
        <dt className="text-slate-500">Purpose</dt>
        <dd>{purpose}</dd>
        <dt className="text-slate-500">Template</dt>
        <dd>{hasTemplate ? templateLabel : 'Not selected'}</dd>
        <dt className="text-slate-500">Output file</dt>
        <dd>{readableFilename(step)}</dd>
        <dt className="text-slate-500">Fields mapped</dt>
        <dd>{entries.length}</dd>
        <dt className="text-slate-500">Sample title</dt>
        <dd>{titleKey ? `From “${titleKey}”` : 'Not set'}</dd>
      </dl>
      <p className="mt-2">
        {missing.length === 0 ? (
          entries.length === 0 ? (
            <span className="text-amber-700">No fields mapped yet.</span>
          ) : (
            <span className="text-green-700">All mapped fields have a value.</span>
          )
        ) : (
          <span className="text-amber-700">
            {missing.length} {missing.length === 1 ? 'mapping needs' : 'mappings need'} a value:{' '}
            {missing.join(', ')}
          </span>
        )}
      </p>
    </section>
  );
}
