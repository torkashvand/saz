import { CheckCircle2, XCircle, Loader2, Clock, AlertCircle } from 'lucide-react';
import type { StepStatus } from '@/lib/types';

interface StatusBadgeProps {
  status: StepStatus;
  className?: string;
}

const STATUS_CONFIG = {
  completed: {
    icon: CheckCircle2,
    color: 'text-green-600',
    bg: 'bg-green-50',
    label: 'Completed',
  },
  failed: {
    icon: XCircle,
    color: 'text-red-600',
    bg: 'bg-red-50',
    label: 'Failed',
  },
  running: {
    icon: Loader2,
    color: 'text-blue-600',
    bg: 'bg-blue-50',
    label: 'Running',
  },
  queued: {
    icon: Clock,
    color: 'text-slate-400',
    bg: 'bg-slate-50',
    label: 'Queued',
  },
  suspended: {
    icon: AlertCircle,
    color: 'text-amber-600',
    bg: 'bg-amber-50',
    label: 'Suspended',
  },
} as const;

export function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.queued;
  const Icon = config.icon;

  return (
    <div className={`inline-flex items-center gap-1.5 ${className}`}>
      <Icon
        className={`h-4 w-4 ${config.color} ${status === 'running' ? 'animate-spin' : ''}`}
        aria-label={config.label}
      />
    </div>
  );
}

export function StatusPill({
  status,
  showLabel = false,
}: StatusBadgeProps & { showLabel?: boolean }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.queued;
  const Icon = config.icon;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium ${config.bg} ${config.color}`}
    >
      <Icon className={`h-3 w-3 ${status === 'running' ? 'animate-spin' : ''}`} />
      {showLabel && config.label}
    </span>
  );
}
