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
  // Set true when we close the socket on purpose (effect cleanup on unmount /
  // navigation). Closing a still-CONNECTING socket fires onerror+onclose with
  // no real fault — React 18 StrictMode does this on every dev mount — so we
  // use this flag to stay silent (no error log, no Sentry, no reconnect)
  // instead of reporting a connection failure that did not happen.
  const intentionalCloseRef = useRef(false);

  // Fetch historical events from database. (Run details are the page's
  // concern via useRunDetails — duplicating that query here just wasted a
  // request and returned data no consumer read.)
  const { data: historicalEventsData } = useQuery({
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

        // A newly written artifact must appear in the Artifacts panel without
        // a page reload — the panel has its own query cache entry.
        if (event.event_type === 'artifact.created') {
          queryClient.invalidateQueries({ queryKey: ['artifacts', runId] });
        }
      }
    },
    [runId, queryClient],
  );

  // True while a ticket fetch + socket open is in flight. During the ticket
  // fetch wsRef is still null, so the readyState guard alone can't prevent a
  // concurrent connect from starting a second handshake.
  const connectingRef = useRef(false);

  const connect = useCallback(() => {
    // Bail if a socket is already OPEN or still CONNECTING. Without the
    // CONNECTING guard, a reconnect timer (or the exported retry()) firing
    // mid-handshake would spawn a second socket, orphan the first (its onclose
    // then schedules yet another reconnect), and multiply connections.
    const existing = wsRef.current;
    if (
      connectingRef.current ||
      (existing &&
        (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING))
    ) {
      return;
    }

    // A pending reconnect timer is about to be superseded by this attempt.
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = undefined;
    }

    // Fresh connection attempt — not a teardown.
    intentionalCloseRef.current = false;
    connectingRef.current = true;

    void (async () => {
      let ws: WebSocket;
      try {
        // Exchanges the access token for a short-lived run-scoped ticket
        // before opening the socket (the token itself never rides the URL).
        ws = await api.connectRunEventStream(
          runId,
          handleEvent,
          (error) => {
            // Suppress errors from an intentional teardown: closing a still-
            // CONNECTING socket is not a real failure and must not surface a
            // connection error or page an error tracker.
            if (intentionalCloseRef.current) {
              return;
            }
            console.error('[RunEvents] WebSocket error:', error);
            const appError = fromNetworkError(
              new Error('Failed to connect to event stream. Please check your connection.'),
            );
            setConnectionError(appError);
            setIsConnected(false);

            captureException(error as any, {
              context: 'websocket',
              runId,
              errorType: 'connection',
            });
          },
          () => {
            setIsConnected(false);
            // Do not reconnect after an intentional teardown (unmount/navigation).
            if (intentionalCloseRef.current) {
              return;
            }
            console.log('[RunEvents] Disconnected, reconnecting in 2s...');
            if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
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
      } catch (error) {
        // Ticket fetch failed (network, auth). Surface it and retry on the
        // same cadence as a dropped socket — unless we're tearing down.
        connectingRef.current = false;
        if (intentionalCloseRef.current) return;
        console.error('[RunEvents] Failed to obtain stream ticket:', error);
        setConnectionError(
          fromNetworkError(
            new Error('Failed to connect to event stream. Please check your connection.'),
          ),
        );
        setIsConnected(false);
        if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = setTimeout(connect, 2000);
        return;
      }

      connectingRef.current = false;
      wsRef.current = ws;

      ws.addEventListener('open', () => {
        // The component unmounted while the socket was still connecting — close
        // it cleanly now (rather than calling close() on a CONNECTING socket,
        // which the browser warns about) and stay silent.
        if (intentionalCloseRef.current) {
          ws.close();
          return;
        }
        console.log('[RunEvents] Connected to event stream for run:', runId);
        setIsConnected(true);
        setConnectionError(null); // Clear any previous connection errors
      });
    })();
  }, [runId, handleEvent, queryClient]);

  useEffect(() => {
    connect();

    return () => {
      intentionalCloseRef.current = true;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      const ws = wsRef.current;
      if (ws && ws.readyState !== WebSocket.CONNECTING) {
        // OPEN/CLOSING: safe to close now. A CONNECTING socket is closed by
        // the 'open' handler above once it finishes connecting, which avoids
        // the browser's "closed before the connection is established" warning.
        ws.close();
      }
    };
  }, [connect]);

  const retry = useCallback(() => {
    setConnectionError(null);
    connect();
  }, [connect]);

  return {
    events,
    isConnected,
    connectionError,
    retry,
  };
}
