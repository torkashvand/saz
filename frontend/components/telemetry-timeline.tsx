'use client';

import React, { useEffect, useRef, useState } from 'react';
import {
  CheckCircle2,
  XCircle,
  AlertCircle,
  PlayCircle,
  StopCircle,
  GitBranch,
  Shield,
  Activity,
  TrendingUp,
} from 'lucide-react';
import type { Event } from '@/lib/types';
import { Card, CardContent } from '@/components/ui/card';

interface TelemetryTimelineProps {
  events: Event[];
  onStepClick?: (stepId: string) => void;
}

interface TelemetryEventItemProps {
  event: Event;
  relativeTime: string;
  onStepClick?: (stepId: string) => void;
}

function calculateRelativeTime(startMs: number, eventMs: number): string {
  const diffMs = eventMs - startMs;

  if (diffMs < 1000) {
    return `+${diffMs.toFixed(0)}ms`;
  } else if (diffMs < 60000) {
    return `+${(diffMs / 1000).toFixed(1)}s`;
  } else {
    const minutes = Math.floor(diffMs / 60000);
    const seconds = ((diffMs % 60000) / 1000).toFixed(0);
    return `+${minutes}m ${seconds}s`;
  }
}

function getEventDisplay(event: Event): {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  label: string;
  details?: string;
} {
  const eventType = event.event_type;

  switch (eventType) {
    case 'plan.generated': {
      const steps = event.payload?.steps || [];
      const stepList = steps.map((s: any) => `  ${s.id}: ${s.intent}`).join('\n');
      return {
        icon: GitBranch,
        color: 'border-purple-500',
        label: 'Plan Generated',
        details: `${steps.length} steps planned:\n${stepList}`,
      };
    }

    case 'step.started': {
      return {
        icon: Activity,
        color: 'border-blue-500',
        label: `Step: ${event.payload?.step_id || event.step_id}`,
        details: `${event.summary}`,
      };
    }

    case 'policy.pii.redacted':
    case 'policy.blocked':
    case 'policy.rate_limited': {
      const isAllowed = eventType !== 'policy.blocked';
      return {
        icon: Shield,
        color: isAllowed ? 'border-green-500' : 'border-red-500',
        label: isAllowed ? 'Policy: Allowed' : 'Policy: Blocked',
        details: `${event.summary}`,
      };
    }

    case 'tool.started': {
      return {
        icon: PlayCircle,
        color: 'border-cyan-500',
        label: `Tool: ${event.payload?.tool || 'Unknown'}`,
        details: `Attempt #${event.payload?.attempt || 1}`,
      };
    }

    case 'tool.succeeded':
    case 'tool.failed': {
      const isSuccess = eventType === 'tool.succeeded';
      return {
        icon: isSuccess ? StopCircle : XCircle,
        color: isSuccess ? 'border-cyan-500' : 'border-red-500',
        label: `Tool ${isSuccess ? 'Completed' : 'Failed'}: ${event.payload?.tool || 'Unknown'}`,
        details: `Duration: ${event.payload?.duration_ms?.toFixed(0) || 0}ms${event.payload?.error ? `\nError: ${event.payload.error}` : ''}`,
      };
    }

    case 'branch.chosen': {
      return {
        icon: GitBranch,
        color: 'border-amber-500',
        label: `Route: ${event.payload?.route || 'Unknown'}`,
        details: event.payload?.signal_summary || event.summary,
      };
    }

    case 'system.error':
    case 'system.warning': {
      const isError = eventType === 'system.error';
      const verdictIcon = isError ? XCircle : AlertCircle;
      return {
        icon: verdictIcon,
        color: isError ? 'border-red-500' : 'border-yellow-500',
        label: `${isError ? 'Error' : 'Warning'}: ${event.summary}`,
        details: event.payload?.details || '',
      };
    }

    case 'usage.recorded': {
      return {
        icon: TrendingUp,
        color: 'border-indigo-500',
        label: 'Resource Usage',
        details: `Tokens: ${event.payload?.tokens?.toLocaleString() || 0}\nCost: $${event.payload?.cost_usd?.toFixed(4) || '0.0000'}\nDuration: ${event.payload?.duration_ms?.toFixed(0) || 0}ms`,
      };
    }

    case 'progress.updated': {
      const percent = event.payload?.percent || 0;
      const progressBar = '▓'.repeat(Math.floor(percent / 5)) + '░'.repeat(20 - Math.floor(percent / 5));
      return {
        icon: Activity,
        color: 'border-slate-500',
        label: `Progress: ${percent.toFixed(1)}%`,
        details: `${progressBar}\n${event.payload?.completed || 0}/${event.payload?.total || 0} steps`,
      };
    }

    default:
      return {
        icon: Activity,
        color: 'border-gray-500',
        label: eventType,
        details: event.summary,
      };
  }
}

function TelemetryEventItem({ event, relativeTime, onStepClick }: TelemetryEventItemProps) {
  const { icon: Icon, color, label, details } = getEventDisplay(event);

  return (
    <div
      className={`border-l-4 ${color} bg-muted/30 p-3 rounded hover:bg-muted/50 transition-colors cursor-pointer`}
      onClick={() => {
        if (event.step_id && onStepClick) {
          onStepClick(event.step_id);
        }
      }}
    >
      <div className="flex items-start gap-3">
        <Icon className="w-4 h-4 mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">{label}</span>
            <span className="text-xs text-muted-foreground font-mono flex-shrink-0">
              {relativeTime}
            </span>
          </div>
          {details && (
            <div className="text-xs text-muted-foreground mt-1 whitespace-pre-wrap">{details}</div>
          )}
        </div>
      </div>
    </div>
  );
}

export function TelemetryTimeline({ events, onStepClick }: TelemetryTimelineProps) {
  const [autoScroll, setAutoScroll] = useState(true);
  const timelineRef = useRef<HTMLDivElement>(null);
  const lastEventCountRef = useRef(0);

  useEffect(() => {
    if (autoScroll && events.length > lastEventCountRef.current && timelineRef.current) {
      timelineRef.current.scrollTop = timelineRef.current.scrollHeight;
    }
    lastEventCountRef.current = events.length;
  }, [events, autoScroll]);

  const handleScroll = () => {
    if (!timelineRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = timelineRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    setAutoScroll(isAtBottom);
  };

  if (events.length === 0) {
    return (
      <Card>
        <CardContent className="p-8 text-center text-muted-foreground">
          <Activity className="w-12 h-12 mx-auto mb-4 opacity-50" />
          <p>No events yet</p>
          <p className="text-sm mt-2">Events will appear here as the workflow executes</p>
        </CardContent>
      </Card>
    );
  }

  const firstTimestamp = new Date(events[0].timestamp).getTime();

  return (
    <div className="relative">
      {!autoScroll && (
        <div className="absolute top-2 right-2 z-10">
          <button
            onClick={() => setAutoScroll(true)}
            className="px-3 py-1 text-xs bg-blue-500 text-white rounded-full shadow-lg hover:bg-blue-600 transition-colors"
          >
            Jump to latest
          </button>
        </div>
      )}

      <Card>
        <CardContent className="p-4">
          <div
            ref={timelineRef}
            onScroll={handleScroll}
            className="space-y-2 overflow-auto max-h-[600px] pr-2"
          >
            {events.map((event, idx) => (
              <TelemetryEventItem
                key={`${event.id}-${idx}`}
                event={event}
                relativeTime={calculateRelativeTime(
                  firstTimestamp,
                  new Date(event.timestamp).getTime(),
                )}
                onStepClick={onStepClick}
              />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
