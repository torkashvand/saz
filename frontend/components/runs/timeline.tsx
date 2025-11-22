"use client";

import { Event } from '@/lib/types';
import { groupEventsByStep } from '@/lib/timeline-utils';
import { EventCard } from './event-card';
import { formatDuration } from '@/lib/format-utils';
import { CheckCircle2, XCircle, Clock, ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';

interface RunTimelineProps {
  events: Event[];
}

export function RunTimeline({ events }: RunTimelineProps) {
  const { steps, orphanEvents } = groupEventsByStep(events);
  const baseTimestamp = events[0]?.timestamp;

  return (
    <div className="space-y-4">
      {/* Orphan events (run-level, before any steps) */}
      {orphanEvents.length > 0 && (
        <div className="space-y-2">
          {orphanEvents.map((event) => (
            <EventCard key={event.id} event={event} baseTimestamp={baseTimestamp} />
          ))}
        </div>
      )}

      {/* Steps with nested events */}
      {steps.map((step) => (
        <StepSection key={step.step_id} step={step} baseTimestamp={baseTimestamp} />
      ))}

      {/* No events state */}
      {events.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          <Clock className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No events yet. Waiting for workflow execution...</p>
        </div>
      )}
    </div>
  );
}

interface StepSectionProps {
  step: {
    step_id: string;
    step_name: string;
    status: 'running' | 'completed' | 'failed' | 'skipped';
    started_at: string | null;
    completed_at: string | null;
    duration_ms: number | null;
    events: Event[];
  };
  baseTimestamp?: string;
}

function StepSection({ step, baseTimestamp }: StepSectionProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  const statusConfig = {
    running: {
      icon: <Clock className="w-5 h-5 text-blue-500 animate-spin" />,
      bgColor: 'bg-blue-50',
      borderColor: 'border-blue-300',
    },
    completed: {
      icon: <CheckCircle2 className="w-5 h-5 text-green-500" />,
      bgColor: 'bg-green-50',
      borderColor: 'border-green-300',
    },
    failed: {
      icon: <XCircle className="w-5 h-5 text-red-500" />,
      bgColor: 'bg-red-50',
      borderColor: 'border-red-300',
    },
    skipped: {
      icon: <Clock className="w-5 h-5 text-gray-400" />,
      bgColor: 'bg-gray-50',
      borderColor: 'border-gray-300',
    },
  };

  const config = statusConfig[step.status];

  return (
    <div className={`border ${config.borderColor} rounded-lg overflow-hidden`}>
      {/* Step Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className={`w-full ${config.bgColor} p-4 flex items-center justify-between hover:opacity-80 transition-opacity`}
      >
        <div className="flex items-center gap-3">
          {config.icon}
          <div className="text-left">
            <h3 className="font-semibold text-gray-900">{step.step_name}</h3>
            <div className="flex items-center gap-3 text-sm text-gray-600 mt-1">
              <span className="capitalize">{step.status}</span>
              {step.duration_ms && (
                <>
                  <span>•</span>
                  <span>{formatDuration(step.duration_ms)}</span>
                </>
              )}
              <span>•</span>
              <span>{step.events.length} events</span>
            </div>
          </div>
        </div>
        {isExpanded ? (
          <ChevronDown className="w-5 h-5 text-gray-500" />
        ) : (
          <ChevronRight className="w-5 h-5 text-gray-500" />
        )}
      </button>

      {/* Step Events */}
      {isExpanded && (
        <div className="p-4 space-y-2 bg-white">
          {step.events.map((event) => (
            <EventCard key={event.id} event={event} baseTimestamp={baseTimestamp} />
          ))}
        </div>
      )}
    </div>
  );
}
