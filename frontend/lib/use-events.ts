'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useToast } from '@/components/ui/use-toast';

const WS_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace('http://', 'ws://').replace('https://', 'wss://') ||
  'ws://localhost:8000';

interface DomainEvent {
  type: string;
  id: string;
  ts: string;
  data: Record<string, any>;
}

export function useGlobalEvents() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const handleEvent = useCallback(
    (event: DomainEvent) => {
      console.log('[Events] Received:', event.type, event.id);

      // Invalidate relevant queries based on event type
      switch (event.type) {
        case 'run.started':
          // Invalidate runs list
          queryClient.invalidateQueries({ queryKey: ['runs'] });
          break;

        case 'run.completed':
          // Invalidate runs list and specific run detail
          queryClient.invalidateQueries({ queryKey: ['runs'] });
          queryClient.invalidateQueries({ queryKey: ['run', event.id] });
          queryClient.invalidateQueries({ queryKey: ['runGraph', event.id] });
          toast({
            title: 'Run Completed',
            description: `Run ${event.id.slice(0, 8)} completed successfully`,
          });
          break;

        case 'run.failed':
          // Invalidate runs list and specific run detail
          queryClient.invalidateQueries({ queryKey: ['runs'] });
          queryClient.invalidateQueries({ queryKey: ['run', event.id] });
          queryClient.invalidateQueries({ queryKey: ['runGraph', event.id] });

          const errorMsg = event.data.error?.message || event.data.message || 'Unknown error';
          toast({
            title: 'Run Failed',
            description: `Run ${event.id.slice(0, 8)}: ${errorMsg}`,
            variant: 'destructive',
          });
          break;

        case 'run.suspended':
          // Invalidate runs list and specific run detail
          queryClient.invalidateQueries({ queryKey: ['runs'] });
          queryClient.invalidateQueries({ queryKey: ['run', event.id] });
          toast({
            title: 'Run Suspended',
            description: `Run ${event.id.slice(0, 8)} suspended: ${event.data.reason || 'Unknown reason'}`,
          });
          break;

        case 'step.started':
        case 'step.completed':
          // Invalidate run detail and graph for the run this step belongs to
          if (event.data.run_id) {
            queryClient.invalidateQueries({ queryKey: ['run', event.data.run_id] });
            queryClient.invalidateQueries({ queryKey: ['runGraph', event.data.run_id] });
          }
          break;

        case 'step.failed':
          // Invalidate queries
          if (event.data.run_id) {
            queryClient.invalidateQueries({ queryKey: ['run', event.data.run_id] });
            queryClient.invalidateQueries({ queryKey: ['runGraph', event.data.run_id] });
          }
          // Show toast for step failure
          const stepErrorMsg = event.data.error?.message || 'Step failed';
          toast({
            title: 'Step Failed',
            description: `${event.data.step_id || 'Step'}: ${stepErrorMsg}`,
            variant: 'destructive',
          });
          break;

        case 'system.connected':
        case 'system.ping':
        case 'system.pong':
          // Ignore system events
          break;

        default:
          console.log('[Events] Unhandled event type:', event.type);
      }
    },
    [queryClient, toast],
  );

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const ws = new WebSocket(`${WS_BASE_URL}/ws/events`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[Events] Connected to global event stream');
    };

    ws.onmessage = (event) => {
      try {
        const domainEvent: DomainEvent = JSON.parse(event.data);
        handleEvent(domainEvent);
      } catch (err) {
        console.error('[Events] Failed to parse event:', err);
      }
    };

    ws.onerror = (error) => {
      console.error('[Events] WebSocket error:', error);
    };

    ws.onclose = () => {
      console.log('[Events] Disconnected, reconnecting in 2s...');
      reconnectTimeoutRef.current = setTimeout(connect, 2000);
    };
  }, [handleEvent]);

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

  return null;
}
