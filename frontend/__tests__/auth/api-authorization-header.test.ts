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

  it('silently refreshes and replays a 401 on a non-refresh auth endpoint (e.g. change_password)', async () => {
    _internalAuth.setAccessToken('stale');
    const unauthorized = {
      ok: false,
      status: 401,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ error: 'unauthorized', message: 'expired' }),
    };
    const refreshed = {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ access_token: 'fresh', token_type: 'bearer', expires_at: 'x' }),
    };
    const okChange = {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ id: 'u1' }),
    };
    // 1) change_password 401 → 2) /auth/refresh 200 → 3) change_password replay 200
    fetchMock
      .mockResolvedValueOnce(unauthorized)
      .mockResolvedValueOnce(refreshed)
      .mockResolvedValueOnce(okChange);

    await expect(
      api.changePassword({ current_password: 'a', new_password: 'b' }),
    ).resolves.toBeDefined();

    const urls = fetchMock.mock.calls.map((c) => c[0]);
    expect(urls[1]).toContain('/api/v1/auth/refresh');
    expect(urls[2]).toContain('/api/v1/auth/change_password');
    expect(_internalAuth.getAccessToken()).toBe('fresh');
  });

  it('does not attempt a refresh loop when /auth/login itself 401s', async () => {
    const unauthorized = {
      ok: false,
      status: 401,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ error: 'invalid_credentials', message: 'bad' }),
    };
    fetchMock.mockResolvedValue(unauthorized);
    await expect(api.login({ identifier: 'a', password: 'b' })).rejects.toBeDefined();
    // Only the login call — no /auth/refresh replay.
    expect(fetchMock).toHaveBeenCalledTimes(1);
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
