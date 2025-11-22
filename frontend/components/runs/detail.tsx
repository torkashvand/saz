"use client";

import { useRunEvents } from '@/lib/use-run-events';
import { RunTimeline } from './timeline';
import { formatDuration, formatCost, formatTokens } from '@/lib/format-utils';
import { CheckCircle2, XCircle, Clock, Wifi, WifiOff, AlertCircle } from 'lucide-react';
import { EventType, Severity } from '@/lib/types';
import { useState } from 'react';
import { ErrorBanner } from '@/components/ui/error-banner';

interface RunDetailProps {
  runId: string;
}

export function RunDetail({ runId }: RunDetailProps) {
  const { run, events, isConnected, isLoading, error, connectionError, retry } = useRunEvents(runId);
  const [eventTypeFilter, setEventTypeFilter] = useState<EventType | 'all'>('all');
  const [severityFilter, setSeverityFilter] = useState<Severity | 'all'>('all');

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <Clock className="w-12 h-12 mx-auto mb-3 text-gray-400 animate-spin" />
          <p className="text-gray-600">Loading run details...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <AlertCircle className="w-12 h-12 mx-auto mb-3 text-red-500" />
          <p className="text-red-600 font-medium">Error: {error?.message || 'Failed to load run'}</p>
        </div>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-gray-600">Run not found</p>
      </div>
    );
  }

  // Filter events
  const filteredEvents = events.filter((event) => {
    if (eventTypeFilter !== 'all' && event.event_type !== eventTypeFilter) {
      return false;
    }
    if (severityFilter !== 'all' && event.severity !== severityFilter) {
      return false;
    }
    return true;
  });

  // Status icon
  const statusConfig = {
    running: {
      icon: <Clock className="w-6 h-6 text-blue-500 animate-spin" />,
      color: 'text-blue-700',
      bg: 'bg-blue-50',
    },
    completed: {
      icon: <CheckCircle2 className="w-6 h-6 text-green-500" />,
      color: 'text-green-700',
      bg: 'bg-green-50',
    },
    failed: {
      icon: <XCircle className="w-6 h-6 text-red-500" />,
      color: 'text-red-700',
      bg: 'bg-red-50',
    },
    suspended: {
      icon: <Clock className="w-6 h-6 text-yellow-500" />,
      color: 'text-yellow-700',
      bg: 'bg-yellow-50',
    },
  };

  const config = statusConfig[run.status as keyof typeof statusConfig] || statusConfig.running;

  return (
    <div className="flex flex-col h-full">
      {/* Header with status, duration, cost */}
      <div className="border-b bg-white sticky top-0 z-10 shadow-sm">
        <div className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              {config.icon}
              <div>
                <h1 className="text-2xl font-bold text-gray-900">{run.flow_id}</h1>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`px-3 py-1 rounded-full text-sm font-medium ${config.bg} ${config.color}`}>
                    {run.status}
                  </span>
                  <span className="px-3 py-1 rounded-full text-sm font-medium bg-purple-50 text-purple-700">
                    {run.planner_mode}
                  </span>
                </div>
              </div>
            </div>
            <div className="text-sm">
              {isConnected ? (
                <span className="flex items-center gap-2 text-green-600">
                  <Wifi className="w-4 h-4" />
                  <span>Live</span>
                </span>
              ) : (
                <span className="flex items-center gap-2 text-gray-400">
                  <WifiOff className="w-4 h-4" />
                  <span>Offline</span>
                </span>
              )}
            </div>
          </div>

          {/* Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <div className="text-xs text-gray-500 uppercase font-medium">Duration</div>
              <div className="text-lg font-semibold font-mono">{formatDuration(run.duration_ms)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500 uppercase font-medium">Tokens</div>
              <div className="text-lg font-semibold font-mono">{formatTokens(run.total_tokens)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500 uppercase font-medium">Cost</div>
              <div className="text-lg font-semibold font-mono">{formatCost(run.total_cost_usd)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500 uppercase font-medium">Events</div>
              <div className="text-lg font-semibold font-mono">{run.total_events || events.length}</div>
            </div>
            {run.error_count && run.error_count > 0 && (
              <div>
                <div className="text-xs text-red-500 uppercase font-medium">Errors</div>
                <div className="text-lg font-semibold font-mono text-red-600">{run.error_count}</div>
              </div>
            )}
          </div>

          {/* Filters */}
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => {
                setEventTypeFilter('all');
                setSeverityFilter('all');
              }}
              className={`px-3 py-1 rounded text-sm ${
                eventTypeFilter === 'all' && severityFilter === 'all'
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              All Events
            </button>
            <button
              onClick={() => setSeverityFilter('error')}
              className={`px-3 py-1 rounded text-sm ${
                severityFilter === 'error'
                  ? 'bg-red-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              Errors Only
            </button>
            <button
              onClick={() => setEventTypeFilter('policy.pii.redacted' as EventType)}
              className={`px-3 py-1 rounded text-sm ${
                eventTypeFilter === 'policy.pii.redacted'
                  ? 'bg-yellow-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              Policy Events
            </button>
            <button
              onClick={() => setEventTypeFilter('plan.generated' as EventType)}
              className={`px-3 py-1 rounded text-sm ${
                eventTypeFilter === 'plan.generated'
                  ? 'bg-purple-500 text-white'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              Agentic Decisions
            </button>
          </div>
        </div>
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-auto p-6 bg-gray-50">
        {connectionError && (
          <div className="mb-4">
            <ErrorBanner
              error={connectionError}
              title="WebSocket Connection Failed"
              onRetry={retry}
              onDismiss={() => {}}
            />
          </div>
        )}
        <RunTimeline events={filteredEvents} />
      </div>
    </div>
  );
}
