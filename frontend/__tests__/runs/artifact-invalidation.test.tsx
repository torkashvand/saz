/**
 * artifact.created events must invalidate the artifacts query so a newly
 * written artifact appears in the Artifacts panel without a page reload.
 * (The panel caches under ['artifacts', runId]; no run-level invalidation
 * refreshes it.)
 */

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useRunEvents } from '@/lib/use-run-events';
import { _internalAuth } from '@/lib/auth';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  url: string;
  readyState = 1;
  onmessage: ((msg: { data: string }) => void) | null = null;
  onerror: unknown = null;
  onclose: unknown = null;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  addEventListener() {}
  close() {}
}

function wsEvent(eventType: string, runId: string, id: string) {
  return {
    data: JSON.stringify({
      id,
      run_id: runId,
      event_type: eventType,
      timestamp: '2026-07-10T10:00:00Z',
      severity: 'info',
      summary: eventType,
      payload: {},
      step_id: null,
    }),
  };
}

describe('useRunEvents — artifact.created invalidation', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    FakeWebSocket.instances = [];
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('WebSocket', FakeWebSocket);
    _internalAuth.setAccessToken('jwt');

    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes('stream_ticket')) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ ticket: 't', expires_in: 60 }),
        };
      }
      // Historical events fetch
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ events: [], next_cursor: null }),
      };
    });
  });

  afterEach(() => {
    _internalAuth.setAccessToken(null);
    vi.unstubAllGlobals();
  });

  async function setup(runId: string) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    renderHook(() => useRunEvents(runId), { wrapper });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    return { invalidateSpy, ws: FakeWebSocket.instances[0] };
  }

  it('REGRESSION: artifact.created invalidates the artifacts query for the run', async () => {
    const { invalidateSpy, ws } = await setup('run-1');

    act(() => {
      ws.onmessage?.(wsEvent('artifact.created', 'run-1', 'e1'));
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['artifacts', 'run-1'] });
  });

  it('unrelated events do not invalidate the artifacts query', async () => {
    const { invalidateSpy, ws } = await setup('run-1');

    act(() => {
      ws.onmessage?.(wsEvent('step.completed', 'run-1', 'e2'));
    });

    const artifactCalls = invalidateSpy.mock.calls.filter(
      ([arg]) => Array.isArray(arg?.queryKey) && arg.queryKey[0] === 'artifacts',
    );
    expect(artifactCalls).toHaveLength(0);
  });
});
