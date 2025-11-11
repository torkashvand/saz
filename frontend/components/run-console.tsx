'use client';

import { useState, useMemo } from 'react';
import { Filter } from 'lucide-react';
import { useTelemetryEvents } from '@/lib/use-telemetry-events';
import { TelemetryTimeline } from './telemetry-timeline';
import { TelemetryProgressHeader } from './telemetry-progress-header';
import { TelemetryStepDrawer } from './telemetry-step-drawer';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { TelemetryEvent, TelemetryUsageEvent, TelemetryProgressEvent } from '@/lib/types';

interface RunConsoleProps {
  runId: string;
  runStatus: string;
  startedAt?: string;
  completedAt?: string;
}

export function RunConsole({ runId, runStatus, startedAt, completedAt }: RunConsoleProps) {
  const { events, isConnected } = useTelemetryEvents(runId);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'errors' | 'policy'>('all');

  // Calculate elapsed time
  const elapsedMs = useMemo(() => {
    if (!startedAt) return undefined;
    const start = new Date(startedAt).getTime();
    const end = completedAt ? new Date(completedAt).getTime() : Date.now();
    return end - start;
  }, [startedAt, completedAt]);

  // Filter events based on selected filter
  const filteredEvents = useMemo(() => {
    if (filter === 'errors') {
      return events.filter(
        (e) =>
          (e.type === 'trace.tool.end' && e.status === 'error') ||
          (e.type === 'trace.critique' && e.verdict !== 'PASS') ||
          (e.type === 'trace.policy.check' && !e.allowed),
      );
    } else if (filter === 'policy') {
      return events.filter(
        (e) =>
          e.type === 'trace.policy.check' ||
          (e.type === 'trace.tool.start' &&
            events.some(
              (pe) => pe.type === 'trace.policy.check' && (pe as any).step_id === (e as any).step_id,
            )),
      );
    }
    return events;
  }, [events, filter]);

  // Extract latest progress event
  const latestProgress = useMemo(() => {
    const progressEvents = events.filter((e) => e.type === 'trace.progress') as TelemetryProgressEvent[];
    return progressEvents[progressEvents.length - 1];
  }, [events]);

  // Extract all usage events
  const usageEvents = useMemo(() => {
    return events.filter((e) => e.type === 'trace.usage') as TelemetryUsageEvent[];
  }, [events]);

  return (
    <div className="relative">
      {/* Connection status indicator */}
      {!isConnected && (
        <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-yellow-500 rounded-full animate-pulse" />
            Reconnecting to telemetry stream...
          </div>
        </div>
      )}

      {/* Progress Header */}
      <TelemetryProgressHeader
        progressEvent={latestProgress}
        usageEvents={usageEvents}
        runStatus={runStatus}
        elapsedMs={elapsedMs}
      />

      {/* Filter Controls */}
      <Card className="mb-4">
        <CardContent className="p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-muted-foreground" />
              <span className="text-sm font-medium">Filter</span>
            </div>

            <div className="flex gap-2">
              <Button
                variant={filter === 'all' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setFilter('all')}
              >
                All ({events.length})
              </Button>
              <Button
                variant={filter === 'errors' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setFilter('errors')}
              >
                Errors Only
              </Button>
              <Button
                variant={filter === 'policy' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setFilter('policy')}
              >
                Policy Events
              </Button>
            </div>
          </div>

          {filteredEvents.length < events.length && (
            <div className="mt-2 text-xs text-muted-foreground">
              Showing {filteredEvents.length} of {events.length} events
            </div>
          )}
        </CardContent>
      </Card>

      {/* Timeline */}
      <TelemetryTimeline events={filteredEvents} onStepClick={setSelectedStepId} />

      {/* Step Drawer */}
      {selectedStepId && (
        <TelemetryStepDrawer
          stepId={selectedStepId}
          events={events}
          onClose={() => setSelectedStepId(null)}
        />
      )}
    </div>
  );
}
