'use client';

import { useState, useMemo, useEffect } from 'react';
import { Filter } from 'lucide-react';
import { useRunEvents } from '@/lib/use-run-events';
import { TelemetryTimeline } from './telemetry-timeline';
import { TelemetryProgressHeader } from './telemetry-progress-header';
import { TelemetryStepDrawer } from './telemetry-step-drawer';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ErrorBanner } from '@/components/ui/error-banner';
import type { Event } from '@/lib/types';

interface RunConsoleProps {
  runId: string;
  runStatus: string;
  startedAt?: string;
  completedAt?: string;
}

export function RunConsole({ runId, runStatus, startedAt, completedAt }: RunConsoleProps) {
  const { events, isConnected, connectionError, retry } = useRunEvents(runId);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'errors' | 'policy'>('all');

  // Debug: log events as they arrive
  useEffect(() => {
    if (events.length > 0) {
      console.log('[Console] Total events:', events.length, 'Last:', events[events.length - 1].event_type);
    }
  }, [events]);

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
      return events.filter((e) => {
        if (e.event_type === 'tool.failed') {
          return true;
        }
        if (e.event_type === 'system.error') {
          return true;
        }
        if (e.event_type === 'policy.blocked' || e.event_type === 'policy.rate_limited') {
          return true;
        }
        return false;
      });
    } else if (filter === 'policy') {
      return events.filter((e) => {
        if (e.event_type.startsWith('policy.')) {
          return true;
        }
        return false;
      });
    }
    return events;
  }, [events, filter]);

  // Extract latest progress event
  const latestProgress = useMemo(() => {
    const progressEvents = events.filter((e) => e.event_type === 'progress.updated');
    if (progressEvents.length === 0) return undefined;
    const lastEvent = progressEvents[progressEvents.length - 1];
    return lastEvent.payload as any;
  }, [events]);

  // Extract all usage events
  const usageEvents = useMemo(() => {
    return events.filter((e) => e.event_type === 'usage.recorded');
  }, [events]);

  return (
    <div className="relative">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div className={`flex items-center gap-2 text-sm ${isConnected ? 'text-green-600' : 'text-yellow-600'}`}>
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-yellow-500 animate-pulse'}`} />
          {isConnected ? 'Live telemetry connected' : 'Reconnecting...'}
        </div>
        {events.length > 0 && (
          <div className="text-xs text-muted-foreground">
            {events.length} events captured
          </div>
        )}
      </div>

      <TelemetryProgressHeader
        progressEvent={latestProgress}
        usageEvents={usageEvents}
        runStatus={runStatus}
        elapsedMs={elapsedMs}
      />

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

      <TelemetryTimeline events={filteredEvents} onStepClick={setSelectedStepId} />

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
