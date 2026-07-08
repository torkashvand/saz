/**
 * The fetch wrapper must attach `Authorization: Bearer <token>` whenever
 * one is stored, and must omit the header when there isn't one. These
 * tests stub fetch and inspect the headers it received.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import { _internalAuth } from '@/lib/auth';

const okJson = () => ({
  ok: true,
  status: 200,
  headers: new Headers({ 'content-type': 'application/json' }),
  json: async () => ({}),
});

describe('API client Authorization header', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(okJson());
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    _internalAuth.setAccessToken(null);
    vi.unstubAllGlobals();
  });

  it('sends Authorization: Bearer <token> when a token is stored', async () => {
    _internalAuth.setAccessToken('jwt-abc');
    await api.listFlows();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-abc');
  });

  it('omits Authorization when no token is stored', async () => {
    await api.listFlows();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it('does not parse JSON on a 204 response (empty body)', async () => {
    // A 204 can carry an application/json content-type with an empty body;
    // calling response.json() would throw. The client must resolve cleanly so
    // callers (e.g. logout) run their follow-up logic.
    _internalAuth.setAccessToken('jwt-abc');
    fetchMock.mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => {
        throw new Error('Unexpected end of JSON input');
      },
      text: async () => '',
    });
    await expect(api.logout()).resolves.toBeDefined();
  });

  it('reads the token at request time, not module load time', async () => {
    // The first call has no token...
    await api.listFlows();
    // ...then login happens between calls.
    _internalAuth.setAccessToken('jwt-late');
    await api.listFlows();
    const headersFirst = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<
      string,
      string
    >;
    const headersSecond = (fetchMock.mock.calls[1][1] as RequestInit).headers as Record<
      string,
      string
    >;
    expect(headersFirst.Authorization).toBeUndefined();
    expect(headersSecond.Authorization).toBe('Bearer jwt-late');
  });
});
