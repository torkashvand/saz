/**
 * The WS stream must authenticate with a short-lived run-scoped ticket minted
 * over the authed HTTP channel — never the long-lived access token, which
 * would otherwise land in proxy/server logs via the URL.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import { _internalAuth } from '@/lib/auth';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onmessage: unknown = null;
  onerror: unknown = null;
  onclose: unknown = null;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  addEventListener() {}
  close() {}
}

describe('api.connectRunEventStream', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    FakeWebSocket.instances = [];
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('WebSocket', FakeWebSocket);
    _internalAuth.setAccessToken('jwt-secret-token');
  });

  afterEach(() => {
    _internalAuth.setAccessToken(null);
    vi.unstubAllGlobals();
  });

  it('exchanges the token for a ticket and never puts the token in the WS URL', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ ticket: 'short-lived-ticket', expires_in: 60 }),
    });

    await api.connectRunEventStream('run-1', () => {});

    // Ticket minted over the authed HTTP channel...
    const [mintUrl, mintInit] = fetchMock.mock.calls[0];
    expect(mintUrl).toContain('/api/v1/runs/run-1/stream_ticket');
    expect(mintInit.method).toBe('POST');
    expect((mintInit.headers as Record<string, string>).Authorization).toBe(
      'Bearer jwt-secret-token',
    );

    // ...and only the ticket rides the WS URL.
    expect(FakeWebSocket.instances).toHaveLength(1);
    const wsUrl = FakeWebSocket.instances[0].url;
    expect(wsUrl).toContain('/api/v1/runs/run-1/stream?ticket=short-lived-ticket');
    expect(wsUrl).not.toContain('jwt-secret-token');
    expect(wsUrl).not.toContain('token=jwt');
  });

  it('does not open a socket when the ticket mint fails', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 403,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ error: 'forbidden', message: 'nope' }),
      text: async () => '{"error":"forbidden","message":"nope"}',
    });

    await expect(api.connectRunEventStream('run-1', () => {})).rejects.toBeDefined();
    expect(FakeWebSocket.instances).toHaveLength(0);
  });
});
