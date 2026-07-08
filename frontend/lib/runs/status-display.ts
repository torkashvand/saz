// Single source of truth for run-status presentation. The backend RunStatus is
// queued | running | suspended | failed | completed (saz.domain.literals) — no
// 'pending'/'success'/'waiting_approval'. Every run-status badge must key off
// this map so labels and colors can't drift per component.

import type { RunStatus } from '@/lib/types';

export interface RunStatusStyle {
  label: string;
  /** Tailwind classes for a bordered pill (bg + text + border). */
  pill: string;
  /** Tailwind text color for an icon/dot. */
  accent: string;
}

export const RUN_STATUS_DISPLAY: Record<RunStatus, RunStatusStyle> = {
  queued: {
    label: 'Queued',
    pill: 'bg-slate-100 text-slate-700 border-slate-300',
    accent: 'text-slate-500',
  },
  running: {
    label: 'Running',
    pill: 'bg-blue-50 text-blue-700 border-blue-200',
    accent: 'text-blue-600',
  },
  suspended: {
    label: 'Suspended',
    pill: 'bg-amber-50 text-amber-700 border-amber-200',
    accent: 'text-amber-600',
  },
  failed: {
    label: 'Failed',
    pill: 'bg-red-50 text-red-700 border-red-200',
    accent: 'text-red-600',
  },
  completed: {
    label: 'Completed',
    pill: 'bg-green-50 text-green-700 border-green-200',
    accent: 'text-green-600',
  },
};

export function runStatusStyle(status: string): RunStatusStyle {
  return (
    (RUN_STATUS_DISPLAY as Record<string, RunStatusStyle>)[status] ?? RUN_STATUS_DISPLAY.queued
  );
}

// Statuses offered as run-list filters, in display order.
export const RUN_STATUS_FILTERS: RunStatus[] = [
  'queued',
  'running',
  'suspended',
  'completed',
  'failed',
];
