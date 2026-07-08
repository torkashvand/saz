'use client';

import { useEffect, useRef, useState } from 'react';

interface CommaListInputProps {
  /** Current parsed list. */
  value: string[];
  /** Called with the parsed (trimmed, empties dropped) list on every edit. */
  onChange: (next: string[]) => void;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
}

function sameList(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/**
 * Text input for a comma-separated list. Keeps the raw typed string as its own
 * draft so intermediate states like a trailing comma ("low, ") survive — the
 * old pattern derived the input value from parsed `array.join(', ')` while
 * stripping empty segments on change, which deleted the comma mid-typing and
 * made lists impossible to extend. The parsed list is emitted on every edit;
 * the draft is only re-synced when `value` changes from outside.
 */
export function CommaListInput({
  value,
  onChange,
  placeholder,
  className,
  ariaLabel,
}: CommaListInputProps) {
  const [draft, setDraft] = useState(() => value.join(', '));
  const lastEmitted = useRef<string[]>(value);

  useEffect(() => {
    if (sameList(value, lastEmitted.current)) return;
    lastEmitted.current = value;
    setDraft(value.join(', '));
  }, [value]);

  const handleChange = (raw: string) => {
    setDraft(raw);
    const parsed = raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    lastEmitted.current = parsed;
    onChange(parsed);
  };

  return (
    <input
      type="text"
      aria-label={ariaLabel}
      value={draft}
      onChange={(e) => handleChange(e.target.value)}
      placeholder={placeholder}
      className={className ?? 'w-full px-2 py-1.5 text-sm border border-slate-300 rounded'}
    />
  );
}
