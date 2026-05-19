import { Event, StepTimeline } from './types';

/**
 * Group events by step ID to create a timeline view
 */
export function groupEventsByStep(events: Event[]): {
  steps: StepTimeline[];
  orphanEvents: Event[];
} {
  const stepMap = new Map<string, Event[]>();
  const orphanEvents: Event[] = [];

  // Group events by step_id
  for (const event of events) {
    if (event.step_id) {
      const existing = stepMap.get(event.step_id) || [];
      existing.push(event);
      stepMap.set(event.step_id, existing);
    } else {
      orphanEvents.push(event);
    }
  }

  // Build step timelines
  const steps: StepTimeline[] = [];

  for (const [stepId, stepEvents] of stepMap.entries()) {
    // Find step metadata from events
    const startEvent = stepEvents.find((e) => e.event_type === 'step.started');
    const completeEvent = stepEvents.find((e) => e.event_type === 'step.completed');
    const failedEvent = stepEvents.find((e) => e.event_type === 'step.failed');

    // Determine step status
    let status: 'running' | 'completed' | 'failed' | 'skipped' = 'running';
    if (completeEvent) status = 'completed';
    else if (failedEvent) status = 'failed';
    else if (stepEvents.some((e) => e.event_type === 'step.skipped')) status = 'skipped';

    // Extract step name from events
    const stepName =
      startEvent?.payload?.step_name ||
      startEvent?.payload?.name ||
      stepEvents[0]?.payload?.name ||
      `Step ${stepId.slice(-8)}`;

    // Calculate duration
    let duration_ms: number | null = null;
    if (startEvent && (completeEvent || failedEvent)) {
      const endEvent = completeEvent || failedEvent;
      if (endEvent) {
        duration_ms =
          new Date(endEvent.timestamp).getTime() - new Date(startEvent.timestamp).getTime();
      }
    }

    steps.push({
      step_id: stepId,
      step_name: stepName,
      status,
      started_at: startEvent?.timestamp || stepEvents[0].timestamp,
      completed_at: completeEvent?.timestamp || failedEvent?.timestamp || null,
      duration_ms,
      events: stepEvents.sort(
        (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
      ),
    });
  }

  // Sort steps by start time
  steps.sort((a, b) => {
    const aTime = new Date(a.started_at || 0).getTime();
    const bTime = new Date(b.started_at || 0).getTime();
    return aTime - bTime;
  });

  return { steps, orphanEvents };
}
