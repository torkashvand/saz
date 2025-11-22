"use client";

import { Event, EventType } from '@/lib/types';
import { formatRelativeTime, formatTimestamp } from '@/lib/format-utils';
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
  Zap,
  Shield,
  DollarSign,
  User,
  Play,
  Clock,
  GitBranch,
  FileText,
} from 'lucide-react';

const EVENT_ICONS: Record<string, React.ReactNode> = {
  'run.started': <Zap className="w-4 h-4 text-blue-500" />,
  'run.completed': <CheckCircle2 className="w-4 h-4 text-green-500" />,
  'run.failed': <XCircle className="w-4 h-4 text-red-500" />,
  'step.started': <Play className="w-4 h-4 text-blue-500" />,
  'step.completed': <CheckCircle2 className="w-4 h-4 text-green-500" />,
  'step.failed': <XCircle className="w-4 h-4 text-red-500" />,
  'tool.started': <Clock className="w-4 h-4 text-gray-500" />,
  'tool.succeeded': <CheckCircle2 className="w-4 h-4 text-green-500" />,
  'tool.failed': <XCircle className="w-4 h-4 text-red-500" />,
  'plan.generated': <GitBranch className="w-4 h-4 text-purple-500" />,
  'policy.pii.redacted': <Shield className="w-4 h-4 text-yellow-500" />,
  'policy.budget.exhausted': <DollarSign className="w-4 h-4 text-red-500" />,
  'approval.requested': <User className="w-4 h-4 text-blue-500" />,
  'artifact.created': <FileText className="w-4 h-4 text-green-500" />,
  'system.error': <XCircle className="w-4 h-4 text-red-500" />,
  'system.warning': <AlertTriangle className="w-4 h-4 text-yellow-500" />,
};

interface EventCardProps {
  event: Event;
  baseTimestamp?: string;
  showDetails?: boolean;
}

export function EventCard({ event, baseTimestamp, showDetails = false }: EventCardProps) {
  const icon = EVENT_ICONS[event.event_type] || <Info className="w-4 h-4" />;

  const severityStyles = {
    info: 'bg-blue-50 border-blue-200',
    warn: 'bg-yellow-50 border-yellow-200',
    error: 'bg-red-50 border-red-200',
  };

  const severityBadgeStyles = {
    info: 'bg-blue-100 text-blue-800',
    warn: 'bg-yellow-100 text-yellow-800',
    error: 'bg-red-100 text-red-800',
  };

  return (
    <div className={`border rounded-lg p-3 ${severityStyles[event.severity]}`}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5">{icon}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className="text-xs font-mono bg-white/50 px-2 py-0.5 rounded border border-gray-300">
              {event.event_type}
            </span>
            <span className="text-xs text-gray-500">
              {baseTimestamp
                ? formatRelativeTime(event.timestamp, baseTimestamp)
                : formatTimestamp(event.timestamp)}
            </span>
            {event.actor !== 'system' && (
              <span className="text-xs px-2 py-0.5 rounded bg-purple-100 text-purple-800">
                {event.actor}
              </span>
            )}
            {event.severity !== 'info' && (
              <span className={`text-xs px-2 py-0.5 rounded ${severityBadgeStyles[event.severity]}`}>
                {event.severity}
              </span>
            )}
          </div>

          <p className="text-sm font-medium text-gray-900">{event.summary}</p>

          {/* Expandable payload details */}
          {Object.keys(event.payload).length > 0 && (
            <details className="mt-2" open={showDetails}>
              <summary className="text-xs text-gray-600 cursor-pointer hover:underline select-none">
                View details
              </summary>
              <pre className="mt-2 p-2 bg-white rounded text-xs overflow-auto max-h-64 border border-gray-200">
                {JSON.stringify(event.payload, null, 2)}
              </pre>
            </details>
          )}

          {/* Tags */}
          {Object.keys(event.tags).length > 0 && (
            <div className="mt-2 flex gap-1 flex-wrap">
              {Object.entries(event.tags).map(([key, value]) => (
                <span
                  key={key}
                  className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700 font-mono"
                >
                  {key}: {value}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
