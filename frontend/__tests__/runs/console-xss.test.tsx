/**
 * Regression: log messages were injected with dangerouslySetInnerHTML, so any
 * HTML in a backend event summary/payload (e.g. an external tool's error body)
 * executed in the operator's browser. Messages must render as text; only the
 * search highlight may produce markup.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

afterEach(cleanup);
import { EnhancedConsolePanel } from '@/components/runs/console-panel';
import type { Event } from '@/lib/types';

function makeEvent(summary: string, id = 'evt-1'): Event {
  return {
    id,
    event_type: 'tool.failed',
    timestamp: '2026-07-08T10:00:00Z',
    schema_version: 1,
    seq: 1,
    run_id: 'run-1',
    step_id: null,
    correlation_id: null,
    planner_mode: 'deterministic',
    severity: 'error',
    actor: 'system',
    summary,
    payload: {},
    tags: {},
  };
}

function renderPanel(events: Event[]) {
  return render(
    <EnhancedConsolePanel
      events={events}
      steps={[]}
      selectedStepIndex={null}
      onSelectStep={() => {}}
      onClearStepFilter={() => {}}
    />,
  );
}

describe('console panel XSS hardening', () => {
  it('renders HTML in event summaries as literal text, not markup', () => {
    const payload = '<img src=x onerror="window.__pwned=true"> failed';
    const { container } = renderPanel([makeEvent(payload)]);
    expect(screen.getByText(payload)).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
  });

  it('renders HTML as text even while a search highlight is active', () => {
    const payload = '<script>alert(1)</script> request failed';
    const { container } = renderPanel([makeEvent(payload)]);
    fireEvent.change(screen.getByPlaceholderText('Search logs...'), {
      target: { value: 'failed' },
    });
    expect(container.querySelector('script')).toBeNull();
    // The matched term is wrapped in <mark>, the rest stays literal text.
    const mark = container.querySelector('mark');
    expect(mark?.textContent).toBe('failed');
    expect(container.textContent).toContain('<script>alert(1)</script> request');
  });
});
