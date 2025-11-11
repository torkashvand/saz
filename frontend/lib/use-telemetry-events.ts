'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import type { TelemetryEvent } from './types';

const WS_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace('http://', 'ws://').replace('https://', 'wss://') ||
  'ws://localhost:8000';

interface DomainEvent {
  type: string;
  id: string;
  ts: string;
  data: Record<string, any>;
}

export function useTelemetryEvents(runId: string) {
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();

  const handleEvent = useCallback(
    (domainEvent: DomainEvent) => {
      // Filter for telemetry events (trace.*)
      if (domainEvent.type.startsWith('trace.')) {
        const telemetryEvent = domainEvent.data as TelemetryEvent;

        // Only process events for this run
        if (telemetryEvent.run_id === runId) {
          setEvents((prev) => {
            // Dedupe: check if we already have this event
            const stepId = 'step_id' in telemetryEvent ? telemetryEvent.step_id : undefined;
            const exists = prev.some(
              (e) =>
                e.type === telemetryEvent.type &&
                ('step_id' in e ? e.step_id : undefined) === stepId &&
                e.timestamp === telemetryEvent.timestamp,
            );

            if (exists) {
              return prev;
            }

            return [...prev, telemetryEvent];
          });
        }
      }
    },
    [runId],
  );

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    // Connect to global event stream (telemetry events go through here)
    const ws = new WebSocket(`${WS_BASE_URL}/ws/events`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[Telemetry] Connected to event stream for run:', runId);
      setIsConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const domainEvent: DomainEvent = JSON.parse(event.data);
        handleEvent(domainEvent);
      } catch (err) {
        console.error('[Telemetry] Failed to parse event:', err);
      }
    };

    ws.onerror = (error) => {
      console.error('[Telemetry] WebSocket error:', error);
      setIsConnected(false);
    };

    ws.onclose = () => {
      console.log('[Telemetry] Disconnected, reconnecting in 2s...');
      setIsConnected(false);
      reconnectTimeoutRef.current = setTimeout(connect, 2000);
    };
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
