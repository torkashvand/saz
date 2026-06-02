'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import { fromNetworkError, type AppError } from './errors';
import { captureException } from './monitoring';
import type { Event } from './types';

/**
 * Deterministic event order: by timestamp, then the monotonic per-run seq as a
 * tie-breaker (timestamps can collide within a batch), then id. This is what
 * keeps the live overlay from contradicting canonical DB state.
 */
function compareEvents(a: Event, b: Event): number {
  if (a.timestamp !== b.timestamp) {
    return a.timestamp < b.timestamp ? -1 : 1;
  }
  const sa = a.seq ?? Number.MAX_SAFE_INTEGER;
  const sb = b.seq ?? Number.MAX_SAFE_INTEGER;
  if (sa !== sb) return sa - sb;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** Merge events by id (dedupe) and return a new array sorted deterministically. */
function mergeEvents(existing: Event[], incoming: Event[]): Event[] {
  const byId = new Map<string, Event>();
  for (const e of existing) byId.set(e.id, e);
  for (const e of incoming) byId.set(e.id, e);
  return Array.from(byId.values()).sort(compareEvents);
}

export function useRunEvents(runId: string) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<Event[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<AppError | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();

  // Fetch run data
  const {
    data: run,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRunDetails(runId),
  });

  // Fetch historical events from database
  const { data: historicalEventsData, isLoading: isLoadingEvents } = useQuery({
    queryKey: ['run-events', runId],
    queryFn: () => api.getRunEvents(runId, { limit: 500 }),
  });

  // Merge historical events into state when fetched. Merge (not replace) so
  // live events that arrived before the historical fetch resolved are not
  // dropped; the result is deduped by id and deterministically sorted.
  useEffect(() => {
    if (historicalEventsData?.events) {
      setEvents((prev) => mergeEvents(prev, historicalEventsData.events));
    }
  }, [historicalEventsData]);

  const handleEvent = useCallback(
    (event: Event) => {
      if (event.run_id === runId) {
        setEvents((prev) => {
          if (prev.some((e) => e.id === event.id)) {
            return prev;
          }
          return mergeEvents(prev, [event]);
        });

        // Invalidate run details cache when run state changes materially.
        //
        // run.started triggers a refetch so run.status updates from
        // "queued" to "running". step.started is NOT included because
        // it doesn't change run.status and the live overlay already
        // handles step-level running state — including it would cause
        // unnecessary refetch churn (one per step).
        //
        // step.completed/failed ARE included because they persist
        // step results and may change run-level aggregates.
        if (
          event.event_type === 'run.started' ||
          event.event_type === 'step.completed' ||
          event.event_type === 'step.failed' ||
          event.event_type === 'run.completed' ||
          event.event_type === 'run.failed' ||
          event.event_type === 'run.suspended' ||
          event.event_type === 'approval.requested' ||
          event.event_type === 'run.resumed'
        ) {
          queryClient.invalidateQueries({ queryKey: ['run', runId] });
        }
      }
    },
    [runId, queryClient],
  );

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const ws = api.connectRunEventStream(
      runId,
      handleEvent,
      (error) => {
        console.error('[RunEvents] WebSocket error:', error);
        const appError = fromNetworkError(
          new Error('Failed to connect to event stream. Please check your connection.'),
        );
        setConnectionError(appError);
        setIsConnected(false);

        // Capture to Sentry
        captureException(error as any, {
          context: 'websocket',
          runId,
          errorType: 'connection',
        });
      },
      () => {
        console.log('[RunEvents] Disconnected, reconnecting in 2s...');
        setIsConnected(false);
        reconnectTimeoutRef.current = setTimeout(connect, 2000);
      },
      () => {
        // Server signalled a gap (dropped events for a slow consumer). Treat
        // REST/DB as canonical and refetch the historical timeline.
        console.warn('[RunEvents] Event gap signalled; refetching from REST');
        queryClient.invalidateQueries({ queryKey: ['run-events', runId] });
        queryClient.invalidateQueries({ queryKey: ['run', runId] });
      },
    );

    wsRef.current = ws;

    ws.addEventListener('open', () => {
      console.log('[RunEvents] Connected to event stream for run:', runId);
      setIsConnected(true);
      setConnectionError(null); // Clear any previous connection errors
    });
  }, [runId, handleEvent, queryClient]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  const retry = useCallback(() => {
    setConnectionError(null);
    connect();
  }, [connect]);

  return {
    run,
    events,
    isConnected,
    isLoading: isLoading || isLoadingEvents,
    error,
    connectionError,
    retry,
  };
}
