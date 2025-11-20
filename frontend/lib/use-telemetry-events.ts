'use client';

/**
 * DEPRECATED: Use useRunEvents from 'use-run-events.ts' instead
 * 
 * This hook has been migrated to use the unified Event system
 * with proper WebSocket handling via api.connectRunEventStream()
 * 
 * Migration guide:
 * - Replace: import { useTelemetryEvents } from '@/lib/use-telemetry-events'
 * - With: import { useRunEvents } from '@/lib/use-run-events'
 * - Change: useTelemetryEvents(runId) -> useRunEvents(runId)
 * - Update event type references from TelemetryEvent to Event
 * - Update event_type checks from trace.* to new unified event types
 */

import { useRunEvents } from './use-run-events';

/**
 * Legacy hook - DEPRECATED
 * @deprecated Use useRunEvents instead
 */
export function useTelemetryEvents(runId: string) {
  console.warn(
    'useTelemetryEvents is deprecated. Please use useRunEvents from use-run-events.ts instead'
  );
  return useRunEvents(runId);
}
