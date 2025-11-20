'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { api } from './api';
import type { Event } from './types';

export function useRunEvents(runId: string) {
  const [events, setEvents] = useState<Event[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();

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
        setIsConnected(false);
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

  return {
    events,
    isConnected,
  };
}
