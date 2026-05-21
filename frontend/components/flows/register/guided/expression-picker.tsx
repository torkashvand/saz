'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Braces } from 'lucide-react';
import type { FlowDraft, WorkflowStepDraft } from '@/lib/flows/types';

interface ExpressionPickerProps {
  /** Insert the chosen token at the current cursor in `inputRef`. */
  inputRef: React.RefObject<HTMLInputElement | HTMLTextAreaElement>;
  /** Current value of the text input (state, not DOM). */
  value: string;
  /** Called when the picker rewrites the value. */
  onChange: (next: string) => void;
  /** The whole draft — drives the form-field / step-id / credential lists. */
  draft: FlowDraft;
  /** Step IDs that come BEFORE this one (so users can only ref prior steps). */
  priorStepIds?: string[];
  /** Accessibility label for the trigger button. */
  triggerLabel?: string;
}

/**
 * Variable explorer for template expressions.
 *
 * Lists the form fields, prior step outputs, credential names, and env
 * helpers. Clicking an item inserts a syntactically valid token into the
 * bound text input at the cursor position (or at the end if the input is
 * not focused). Users don't have to remember `{{ $form.x }}` syntax.
 */
export function ExpressionPicker({
  inputRef,
  value,
  onChange,
  draft,
  priorStepIds,
  triggerLabel,
}: ExpressionPickerProps) {
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const id = useId();

  const formFields = draft.form?.fields ?? [];
  const credentials = draft.credentials?.uses ?? [];
  const stepIds = priorStepIds ?? draft.workflow.steps.map((s) => s.id);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (!popoverRef.current) return;
      if (!popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [open]);

  const insert = (token: string) => {
    const el = inputRef.current;
    if (!el) {
      onChange(value + token);
      setOpen(false);
      return;
    }
    const start = typeof el.selectionStart === 'number' ? el.selectionStart : value.length;
    const end = typeof el.selectionEnd === 'number' ? el.selectionEnd : value.length;
    const next = value.slice(0, start) + token + value.slice(end);
    onChange(next);
    // Restore cursor position after the inserted token on the next tick.
    requestAnimationFrame(() => {
      const target = inputRef.current;
      if (!target) return;
      const pos = start + token.length;
      try {
        target.focus();
        target.setSelectionRange(pos, pos);
      } catch {
        // Some inputs don't support setSelectionRange; ignore.
      }
    });
    setOpen(false);
  };

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={triggerLabel || 'Insert expression'}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        className="p-1.5 text-xs text-slate-600 hover:bg-slate-100 rounded inline-flex items-center gap-1"
      >
        <Braces className="h-3.5 w-3.5" />
        <span>Insert</span>
      </button>
      {open && (
        <div
          ref={popoverRef}
          id={id}
          role="dialog"
          aria-label="Expression picker"
          className="absolute right-0 mt-1 w-72 max-h-80 overflow-y-auto bg-white border border-slate-200 rounded-md shadow-lg z-50"
        >
          <PickerGroup title="Form fields" empty="No form fields defined yet.">
            {formFields.map((field) => (
              <PickerItem
                key={field.name}
                label={field.name}
                hint={field.description}
                token={`{{ $form.${field.name} }}`}
                onPick={insert}
              />
            ))}
          </PickerGroup>

          <PickerGroup title="Prior step outputs" empty="No prior steps yet.">
            {stepIds.map((sid) => (
              <PickerItem key={sid} label={sid} token={`{{ $step('${sid}') }}`} onPick={insert} />
            ))}
          </PickerGroup>

          <PickerGroup title="Credentials" empty="No credentials declared.">
            {credentials.map((name) => (
              <PickerItem
                key={name}
                label={name}
                token={`{{ $secret('${name}') }}`}
                onPick={insert}
              />
            ))}
          </PickerGroup>

          <PickerGroup title="Environment">
            <PickerItem label="$env(VAR)" token={`{{ $env('VAR') }}`} onPick={insert} />
          </PickerGroup>
        </div>
      )}
    </div>
  );
}

function PickerGroup({
  title,
  children,
  empty,
}: {
  title: string;
  children: React.ReactNode;
  empty?: string;
}) {
  const items = Array.isArray(children) ? children.filter(Boolean) : [children];
  const hasItems = items.length > 0 && items.some(Boolean);
  return (
    <div className="border-b border-slate-100 last:border-b-0">
      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500 bg-slate-50">
        {title}
      </div>
      {hasItems ? (
        <ul className="py-1">{items}</ul>
      ) : (
        <p className="px-3 py-2 text-xs text-slate-400">{empty}</p>
      )}
    </div>
  );
}

function PickerItem({
  label,
  hint,
  token,
  onPick,
}: {
  label: string;
  hint?: string;
  token: string;
  onPick: (token: string) => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onPick(token)}
        className="w-full text-left px-3 py-1.5 text-xs hover:bg-blue-50 focus:bg-blue-50 focus:outline-none"
      >
        <div className="font-mono text-slate-900">{label}</div>
        {hint && <div className="text-[11px] text-slate-500">{hint}</div>}
        <div className="text-[11px] text-blue-700 font-mono mt-0.5">{token}</div>
      </button>
    </li>
  );
}

// Helper hook: pair a ref + value handler with the picker.
export function useExpressionField(
  step: WorkflowStepDraft,
  onChange: (updates: Partial<WorkflowStepDraft>) => void,
  fieldKey: 'instruction' | 'if',
) {
  const inputRef = useRef<HTMLTextAreaElement | HTMLInputElement | null>(null);
  const value = (step[fieldKey] as string | undefined) ?? '';
  return {
    inputRef,
    value,
    onChange: (next: string) => onChange({ [fieldKey]: next } as Partial<WorkflowStepDraft>),
  };
}
