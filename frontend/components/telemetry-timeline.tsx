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
import type { TelemetryEvent } from '@/lib/types';
import { Card, CardContent } from '@/components/ui/card';

interface TelemetryTimelineProps {
  events: TelemetryEvent[];
  onStepClick?: (stepId: string) => void;
}

interface TelemetryEventItemProps {
  event: TelemetryEvent;
  relativeTime: string;
  onStepClick?: (stepId: string) => void;
}

// Helper: Calculate relative time from start
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

// Helper: Get display info for each event type
function getEventDisplay(event: TelemetryEvent): {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  label: string;
  details?: string;
} {
  const eventType = event.type;

  switch (eventType) {
    case 'trace.plan': {
      const e = event as Extract<TelemetryEvent, { type: 'trace.plan' }>;
      const stepList = e.steps.map(s => `  ${s.id}: ${s.intent}`).join('\n');
      return {
        icon: GitBranch,
        color: 'border-purple-500',
        label: '🎯 Execution Plan Generated',
        details: `${e.total_steps} steps planned:\n${stepList}`,
      };
    }

    case 'trace.step.grounded': {
      const e = event as Extract<TelemetryEvent, { type: 'trace.step.grounded' }>;
      return {
        icon: Activity,
        color: 'border-blue-500',
        label: `📋 ${e.step_id}`,
        details: `${e.intent}\n💭 Input: ${e.input_summary}`,
      };
    }

    case 'trace.policy.check': {
      const e = event as Extract<TelemetryEvent, { type: 'trace.policy.check' }>;
      let piiDetails = '';
      if (e.pii_stats) {
        const parts = [];
        if (e.pii_stats.tokenized_count > 0) {
          parts.push(`🔒 ${e.pii_stats.tokenized_count} PII values tokenized`);
        }
        if (e.pii_stats.detokenized_paths.length > 0) {
          parts.push(`🔓 Detokenized: ${e.pii_stats.detokenized_paths.join(', ')}`);
        }
        if (e.pii_stats.blocked_paths.length > 0) {
          parts.push(`🚫 Blocked: ${e.pii_stats.blocked_paths.join(', ')}`);
        }
        piiDetails = parts.length > 0 ? '\n' + parts.join('\n') : '';
      }

      return {
        icon: Shield,
        color: e.allowed ? 'border-green-500' : 'border-red-500',
        label: e.allowed ? '✅ Policy Check: Allowed' : '❌ Policy Check: Blocked',
        details: `Tool: ${e.tool}${e.reason ? `\n⚠️  Reason: ${e.reason}` : ''}${piiDetails}`,
      };
    }

    case 'trace.tool.start': {
      const e = event as Extract<TelemetryEvent, { type: 'trace.tool.start' }>;
      return {
        icon: PlayCircle,
        color: 'border-cyan-500',
        label: `▶️  Executing: ${e.tool}`,
        details: `Attempt #${e.attempt}`,
      };
    }

    case 'trace.tool.end': {
      const e = event as Extract<TelemetryEvent, { type: 'trace.tool.end' }>;
      const statusEmoji = e.status === 'success' ? '✅' : '❌';
      return {
        icon: e.status === 'success' ? StopCircle : XCircle,
        color: e.status === 'success' ? 'border-cyan-500' : 'border-red-500',
        label: `${statusEmoji} ${e.tool} ${e.status === 'success' ? 'Completed' : 'Failed'}`,
        details: `⏱️  Duration: ${e.duration_ms.toFixed(0)}ms${e.error_type ? `\n❌ Error: ${e.error_type}` : ''}`,
      };
    }

    case 'trace.route.chosen': {
      const e = event as Extract<TelemetryEvent, { type: 'trace.route.chosen' }>;
      return {
        icon: GitBranch,
        color: 'border-amber-500',
        label: `Route: ${e.route}`,
        details: e.signal_summary,
      };
    }

    case 'trace.critique': {
      const e = event as Extract<TelemetryEvent, { type: 'trace.critique' }>;
      const verdictIcon = {
        PASS: CheckCircle2,
        FAIL: XCircle,
        ESCALATE: AlertCircle,
        REPLAN: Activity,
      }[e.verdict] || Activity;
      const verdictColor = {
        PASS: 'border-green-500',
        FAIL: 'border-red-500',
        ESCALATE: 'border-yellow-500',
        REPLAN: 'border-orange-500',
      }[e.verdict] || 'border-gray-500';

      const verdictEmoji = {
        PASS: '✅',
        FAIL: '❌',
        ESCALATE: '⚠️',
        REPLAN: '🔄',
      }[e.verdict] || '❓';

      let issuesDetail = '';
      if (e.issues.length > 0) {
        issuesDetail = '\n❗ Issues:\n' + e.issues.map((i) => `  • ${i}`).join('\n');
      }

      return {
        icon: verdictIcon,
        color: verdictColor,
        label: `${verdictEmoji} Critique: ${e.verdict}`,
        details: `📊 Confidence: ${(e.confidence * 100).toFixed(0)}%\n${e.summary}${issuesDetail}`,
      };
    }

    case 'trace.usage': {
      const e = event as Extract<TelemetryEvent, { type: 'trace.usage' }>;
      return {
        icon: TrendingUp,
        color: 'border-indigo-500',
        label: '📈 Resource Usage',
        details: `🔢 ${e.tokens.toLocaleString()} tokens\n💰 $${e.cost_usd.toFixed(4)}\n⏱️  ${e.duration_ms.toFixed(0)}ms`,
      };
    }

    case 'trace.progress': {
      const e = event as Extract<TelemetryEvent, { type: 'trace.progress' }>;
      const progressBar = '▓'.repeat(Math.floor(e.percent / 5)) + '░'.repeat(20 - Math.floor(e.percent / 5));
      return {
        icon: Activity,
        color: 'border-slate-500',
        label: `📊 Progress: ${e.percent.toFixed(1)}%`,
        details: `${progressBar}\n${e.completed}/${e.total} steps completed`,
      };
    }

    default:
      return {
        icon: Activity,
        color: 'border-gray-500',
        label: eventType,
        details: undefined,
      };
  }
}

// Event item component
function TelemetryEventItem({ event, relativeTime, onStepClick }: TelemetryEventItemProps) {
  const { icon: Icon, color, label, details } = getEventDisplay(event);

  return (
    <div
      className={`border-l-4 ${color} bg-muted/30 p-3 rounded hover:bg-muted/50 transition-colors cursor-pointer`}
      onClick={() => {
        if ('step_id' in event && onStepClick) {
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

// Main timeline component
export function TelemetryTimeline({ events, onStepClick }: TelemetryTimelineProps) {
  const [autoScroll, setAutoScroll] = useState(true);
  const timelineRef = useRef<HTMLDivElement>(null);
  const lastEventCountRef = useRef(0);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (autoScroll && events.length > lastEventCountRef.current && timelineRef.current) {
      timelineRef.current.scrollTop = timelineRef.current.scrollHeight;
    }
    lastEventCountRef.current = events.length;
  }, [events, autoScroll]);

  // Detect manual scroll up
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
          <p>No telemetry events yet</p>
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
                key={`${event.type}-${idx}`}
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
