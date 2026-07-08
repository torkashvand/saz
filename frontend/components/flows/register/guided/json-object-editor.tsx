'use client';

import { useEffect, useRef, useState } from 'react';

interface JsonObjectEditorProps {
  label: string;
  value: unknown;
  onChange: (next: unknown) => void;
  placeholder?: string;
  rows?: number;
  // Identifier used in the textarea's aria-label so tests can target it.
  testId?: string;
}

/**
 * Structured editor for nested DSL fields (params, expect, content, etc.).
 *
 * Renders as a textarea backed by pretty-printed JSON. The textarea keeps
 * its own draft string so a user can type partial JSON without the parent
 * flipping state on every keystroke; the parent is only updated when the
 * draft parses cleanly. Invalid drafts are flagged inline.
 *
 * JSON (rather than YAML) is the right tradeoff here: js-yaml's quoting is
 * fiddly to reverse, JSON has unambiguous round-trip semantics, and the
 * generator re-serializes to YAML on its own.
 */
export function JsonObjectEditor({
  label,
  value,
  onChange,
  placeholder,
  rows = 6,
  testId,
}: JsonObjectEditorProps) {
  const [draft, setDraft] = useState<string>(() => stringify(value));
  const [error, setError] = useState<string | null>(null);
  // The last value THIS editor emitted, so we can distinguish an external
  // change (adopt it) from an echo of our own onChange (ignore it).
  const lastEmitted = useRef<unknown>(value);

  // Adopt external value changes (e.g. YAML mode rewrote the draft). Crucially
  // this does NOT run on blur, so typing invalid JSON and clicking away keeps
  // the invalid text and its error visible instead of silently reverting.
  useEffect(() => {
    if (value === lastEmitted.current) return;
    lastEmitted.current = value;
    setDraft(stringify(value));
    setError(null);
  }, [value]);

  const handleChange = (next: string) => {
    setDraft(next);
    if (next.trim() === '') {
      setError(null);
      lastEmitted.current = undefined;
      onChange(undefined);
      return;
    }
    try {
      const parsed = JSON.parse(next);
      setError(null);
      lastEmitted.current = parsed;
      onChange(parsed);
    } catch (e: any) {
      setError(e?.message || 'Invalid JSON');
    }
  };

  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      <textarea
        value={draft}
        onChange={(e) => handleChange(e.target.value)}
        rows={rows}
        aria-label={testId || label}
        spellCheck={false}
        className="w-full px-2 py-1.5 text-xs font-mono border border-slate-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
        placeholder={placeholder || '{ }'}
      />
      {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
    </div>
  );
}

function stringify(value: unknown): string {
  if (value === undefined || value === null) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return '';
  }
}
