'use client';

import { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Sparkles,
  FileInput,
  FileOutput,
  MessageSquare,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Type guards
// ---------------------------------------------------------------------------

/** A plain JSON object (not null, not an array). */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The execution envelope produced for AI steps: `{ tool: "ai.*", arguments: {...} }`. */
export interface AiStepEnvelope {
  tool: string;
  arguments: Record<string, unknown>;
}

export function isAiStepEnvelope(value: unknown): value is AiStepEnvelope {
  return (
    isRecord(value) &&
    typeof value.tool === 'string' &&
    value.tool.startsWith('ai.') &&
    isRecord(value.arguments)
  );
}

/** True when a value carries no information worth showing the operator. */
export function isEmptyValue(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  if (isRecord(value)) return Object.keys(value).length === 0;
  return false;
}

// ---------------------------------------------------------------------------
// Readable value rendering
// ---------------------------------------------------------------------------

/**
 * Render an arbitrary value as readable, human-scannable content rather than a
 * raw JSON blob. Strings keep their real line breaks, objects become labelled
 * rows, arrays become lists. Defensive against null/undefined/unknown shapes.
 */
export function ReadableValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="italic text-slate-400">none</span>;
  }

  if (typeof value === 'string') {
    if (value.trim().length === 0) {
      return <span className="italic text-slate-400">empty</span>;
    }
    return <span className="whitespace-pre-wrap break-words text-slate-800">{value}</span>;
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return <span className="font-mono text-slate-800">{String(value)}</span>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="italic text-slate-400">empty list</span>;
    }
    return (
      <ul className="space-y-1.5">
        {value.map((item, i) => (
          <li key={i} className="flex gap-2">
            <span className="select-none font-mono text-xs text-slate-400">{i + 1}.</span>
            <div className="min-w-0 flex-1">
              <ReadableValue value={item} />
            </div>
          </li>
        ))}
      </ul>
    );
  }

  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) {
      return <span className="italic text-slate-400">empty</span>;
    }
    return (
      <dl className="space-y-2">
        {entries.map(([key, val]) => (
          <div key={key} className="grid grid-cols-[minmax(0,9rem)_1fr] gap-x-3 gap-y-0.5">
            <dt className="break-words text-xs font-medium text-slate-500">{key}</dt>
            <dd className="min-w-0 text-sm">
              <ReadableValue value={val} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  return <span className="font-mono text-slate-800">{String(value)}</span>;
}

// ---------------------------------------------------------------------------
// Collapsible section
// ---------------------------------------------------------------------------

interface CollapsibleSectionProps {
  title: string;
  hint?: string;
  defaultOpen?: boolean;
  icon?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * A bordered, collapsible section used to group a single concern (prompt,
 * input data, output). Click handling stops propagation so toggling a section
 * never collapses the enclosing step card.
 */
export function CollapsibleSection({
  title,
  hint,
  defaultOpen = false,
  icon,
  children,
}: CollapsibleSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const toggle = (e: React.MouseEvent | React.KeyboardEvent) => {
    e.stopPropagation();
    setIsOpen((prev) => !prev);
  };

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <button
        type="button"
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggle(e);
          }
        }}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4 flex-shrink-0 text-slate-400" />
        ) : (
          <ChevronRight className="h-4 w-4 flex-shrink-0 text-slate-400" />
        )}
        {icon}
        <span className="flex-1">{title}</span>
        {hint && <span className="text-xs font-normal text-slate-400">{hint}</span>}
      </button>
      {isOpen && (
        <div className="max-h-96 overflow-auto border-t border-slate-100 px-3 py-3 text-sm">
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step inspection panel
// ---------------------------------------------------------------------------

function fieldCount(value: unknown): string {
  if (isRecord(value)) {
    const n = Object.keys(value).length;
    return `${n} field${n === 1 ? '' : 's'}`;
  }
  if (Array.isArray(value)) {
    const n = value.length;
    return `${n} item${n === 1 ? '' : 's'}`;
  }
  return '1 value';
}

interface StepInspectionPanelProps {
  input?: unknown;
  output?: unknown;
}

/**
 * Operator-facing inspection of a step's input and output.
 *
 * AI steps carry an execution envelope (`{ tool: "ai.*", arguments: {...} }`)
 * that mixes prompt, runtime data, and static config. We separate the prompt
 * from the runtime data and hide static workflow config from the default view.
 * Non-AI steps render their input and output as readable values.
 *
 * Renders nothing when there is nothing meaningful to show.
 */
export function StepInspectionPanel({ input, output }: StepInspectionPanelProps) {
  const hasOutput = !isEmptyValue(output);

  if (isAiStepEnvelope(input)) {
    const instruction = input.arguments.instruction;
    const data = input.arguments.data;

    const hasPrompt = typeof instruction === 'string' && instruction.trim().length > 0;
    const hasData = !isEmptyValue(data);

    if (!hasPrompt && !hasData && !hasOutput) return null;

    const summary = ['AI step'];
    if (hasPrompt) summary.push('prompt separated');
    if (hasData) summary.push(`input data: ${fieldCount(data)}`);
    if (hasOutput) summary.push(`output: ${fieldCount(output)}`);

    return (
      <div className="space-y-2">
        <SummaryLine text={summary.join(' · ')} />

        {hasPrompt && (
          <CollapsibleSection
            title="Prompt"
            icon={<MessageSquare className="h-4 w-4 flex-shrink-0 text-purple-500" />}
          >
            <div className="whitespace-pre-wrap break-words leading-relaxed text-slate-800">
              {instruction as string}
            </div>
          </CollapsibleSection>
        )}

        {hasData && (
          <CollapsibleSection
            title="Input data"
            hint={fieldCount(data)}
            defaultOpen
            icon={<FileInput className="h-4 w-4 flex-shrink-0 text-blue-500" />}
          >
            <ReadableValue value={data} />
          </CollapsibleSection>
        )}

        {hasOutput && (
          <CollapsibleSection
            title="Output"
            defaultOpen
            icon={<FileOutput className="h-4 w-4 flex-shrink-0 text-green-600" />}
          >
            <ReadableValue value={output} />
          </CollapsibleSection>
        )}
      </div>
    );
  }

  // Non-AI step: render clean input/output sections without envelope assumptions.
  const hasInput = !isEmptyValue(input);
  if (!hasInput && !hasOutput) return null;

  const summary = ['Step data'];
  if (hasInput) summary.push(`input: ${fieldCount(input)}`);
  if (hasOutput) summary.push(`output: ${fieldCount(output)}`);

  return (
    <div className="space-y-2">
      <SummaryLine text={summary.join(' · ')} />

      {hasInput && (
        <CollapsibleSection
          title="Input"
          hint={fieldCount(input)}
          defaultOpen
          icon={<FileInput className="h-4 w-4 flex-shrink-0 text-blue-500" />}
        >
          <ReadableValue value={input} />
        </CollapsibleSection>
      )}

      {hasOutput && (
        <CollapsibleSection
          title="Output"
          defaultOpen
          icon={<FileOutput className="h-4 w-4 flex-shrink-0 text-green-600" />}
        >
          <ReadableValue value={output} />
        </CollapsibleSection>
      )}
    </div>
  );
}

function SummaryLine({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-slate-500">
      <Sparkles className="h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
      <span>{text}</span>
    </div>
  );
}
