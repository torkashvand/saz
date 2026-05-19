'use client';

import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, Search, Sparkles, Star, Tag, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useTemplates } from '@/lib/hooks';
import type { TemplateSummary } from '@/lib/types';

interface TemplatePickerProps {
  /** Controlled open state. Parent decides when the picker is visible. */
  open: boolean;
  /** Called when the picker should close (X button, ESC, backdrop click). */
  onClose: () => void;
  /**
   * Called when a template is selected. The parent is responsible for
   * loading the YAML — the picker only signals which id to load.
   */
  onSelect: (templateId: string) => void;
}

/**
 * Modal template picker.
 *
 * Lists the built-in flow templates returned by ``/api/templates/`` with
 * the recommended ones (wedge demos) surfaced at the top. Supports a
 * text filter and a "recommended only" toggle. Designed to be the
 * primary entry point for operators trying the demos for the first time.
 *
 * The component is intentionally self-contained (no external Dialog
 * dependency) so it can ship alongside the rest of the wedge-demo
 * polish without pulling in a new UI library.
 */
export function TemplatePicker({ open, onClose, onSelect }: TemplatePickerProps) {
  const [recommendedOnly, setRecommendedOnly] = useState(true);
  const [search, setSearch] = useState('');
  const [mounted, setMounted] = useState(false);

  // Portals need a DOM target — defer mount to client.
  useEffect(() => {
    setMounted(true);
  }, []);

  // ESC closes the picker so keyboard users aren't stuck in the modal.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const templatesQuery = useTemplates({ recommendedOnly });

  const filtered = useMemo(() => {
    const list = templatesQuery.data ?? [];
    const needle = search.trim().toLowerCase();
    if (!needle) return list;
    return list.filter((t) => {
      const haystack = [
        t.title,
        t.description,
        ...(t.tags ?? []),
        t.id,
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [templatesQuery.data, search]);

  // Sort so wedge demos come first (most relevant for the conference
  // narrative), then by title alphabetically for stable ordering.
  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const aWedge = (a.tags || []).includes('wedge-demo') ? 0 : 1;
      const bWedge = (b.tags || []).includes('wedge-demo') ? 0 : 1;
      if (aWedge !== bWedge) return aWedge - bWedge;
      return a.title.localeCompare(b.title);
    });
  }, [filtered]);

  if (!mounted || !open) return null;

  const modal = (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Choose a flow template"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={(e) => {
        // Clicking the backdrop (but not the panel) closes the modal.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        data-testid="template-picker"
        className="flex w-full max-w-4xl max-h-[85vh] flex-col rounded-lg bg-white shadow-xl"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-200 p-5">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              Start from a template
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Pick a pre-built workflow to populate the editor. Wedge demos are
              highlighted — they're the recommended starting point.
            </p>
          </div>
          <button
            type="button"
            aria-label="Close template picker"
            onClick={onClose}
            className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        {/* Filters */}
        <div className="flex flex-col gap-3 border-b border-slate-200 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative flex-1">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
              aria-hidden="true"
            />
            <input
              type="search"
              placeholder="Search by title, description, or tag…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              data-testid="template-picker-search"
              className="w-full rounded border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={recommendedOnly}
              onChange={(e) => setRecommendedOnly(e.target.checked)}
              data-testid="template-picker-recommended-only"
              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            Recommended only
          </label>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {templatesQuery.isLoading && (
            <div className="flex items-center justify-center py-12 text-sm text-slate-500">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              Loading templates…
            </div>
          )}

          {templatesQuery.error && (
            <div
              role="alert"
              data-testid="template-picker-error"
              className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800"
            >
              Failed to load templates. Make sure the backend is reachable at the
              configured API base URL.
            </div>
          )}

          {!templatesQuery.isLoading &&
            !templatesQuery.error &&
            sorted.length === 0 && (
              <div className="rounded border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-600">
                No templates match the current filters.
              </div>
            )}

          {sorted.length > 0 && (
            <ul className="space-y-3" data-testid="template-picker-list">
              {sorted.map((tpl) => (
                <TemplateRow
                  key={tpl.id}
                  template={tpl}
                  onSelect={() => onSelect(tpl.id)}
                />
              ))}
            </ul>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 p-4">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}

function TemplateRow({
  template,
  onSelect,
}: {
  template: TemplateSummary;
  onSelect: () => void;
}) {
  const isWedge = (template.tags || []).includes('wedge-demo');
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        data-testid={`template-picker-row-${template.id}`}
        className={`group flex w-full flex-col gap-2 rounded-lg border p-4 text-left transition-colors hover:border-blue-400 hover:bg-blue-50/40 focus:outline-none focus:ring-2 focus:ring-blue-500 ${
          isWedge
            ? 'border-amber-300 bg-amber-50/40'
            : 'border-slate-200 bg-white'
        }`}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              {template.title}
            </h3>
            <p className="mt-1 text-xs text-slate-500 font-mono">{template.id}</p>
          </div>
          <div className="flex flex-shrink-0 items-center gap-2">
            {isWedge && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
                <Sparkles className="h-3 w-3" aria-hidden="true" />
                Wedge demo
              </span>
            )}
            {template.recommended && (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-800">
                <Star className="h-3 w-3" aria-hidden="true" />
                Recommended
              </span>
            )}
          </div>
        </div>
        {template.description && (
          <p className="text-sm text-slate-700">{template.description}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <span className="rounded bg-slate-100 px-2 py-0.5 font-medium">
            {template.steps_count} step{template.steps_count === 1 ? '' : 's'}
          </span>
          {template.ai_steps > 0 && (
            <span className="rounded bg-slate-100 px-2 py-0.5 font-medium">
              {template.ai_steps} AI op{template.ai_steps === 1 ? '' : 's'}
            </span>
          )}
          {template.credentials.length > 0 && (
            <span className="rounded bg-slate-100 px-2 py-0.5 font-medium">
              {template.credentials.length} credential
              {template.credentials.length === 1 ? '' : 's'}
            </span>
          )}
          <span className="rounded bg-slate-100 px-2 py-0.5 font-medium capitalize">
            {template.complexity}
          </span>
          {(template.tags || []).slice(0, 5).map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded bg-slate-50 px-2 py-0.5 text-slate-600"
            >
              <Tag className="h-3 w-3" aria-hidden="true" />
              {tag}
            </span>
          ))}
        </div>
      </button>
    </li>
  );
}