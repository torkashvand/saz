'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import { fromNetworkError, type AppError } from './errors';
import { captureException } from './monitoring';
import type { Event } from './types';

export function useRunEvents(runId: string) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<Event[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<AppError | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();

  // Fetch run data
  const { data: run, isLoading, error } = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRunDetails(runId),
  });

  // Fetch historical events from database
  const { data: historicalEventsData, isLoading: isLoadingEvents } = useQuery({
    queryKey: ['run-events', runId],
    queryFn: () => api.getRunEvents(runId, { limit: 500 }),
  });

  // Load historical events into state when fetched
  useEffect(() => {
    if (historicalEventsData?.events) {
      console.log('[RunEvents] Loaded', historicalEventsData.events.length, 'historical events from DB');
      setEvents(historicalEventsData.events);
    }
  }, [historicalEventsData]);

  const handleEvent = useCallback(
    (event: Event) => {
      if (event.run_id === runId) {
        setEvents((prev) => {
          const exists = prev.some((e) => e.id === event.id);
          if (exists) {
            return prev;
          }
          return [...prev, event];
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
          new Error('Failed to connect to event stream. Please check your connection.')
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
    );

    wsRef.current = ws;

    ws.addEventListener('open', () => {
      console.log('[RunEvents] Connected to event stream for run:', runId);
      setIsConnected(true);
      setConnectionError(null); // Clear any previous connection errors
    });
  }, [runId, handleEvent]);

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
