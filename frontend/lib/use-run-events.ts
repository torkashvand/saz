'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { fromNetworkError, type AppError } from './errors';
import { captureException } from './monitoring';
import type { Event } from './types';

export function useRunEvents(runId: string) {
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
      }
    },
    [runId],
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
    isLoading,
    error,
    connectionError,
    retry,
  };
}
