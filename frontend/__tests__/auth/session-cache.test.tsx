/**
 * Regression coverage for session hygiene:
 *  - logout / login clear the React Query cache (no cross-user data leak).
 *  - a 401 caught in the query cache fully signs the user out (token + user
 *    state), not just the token — otherwise the UI stays ghost-authenticated.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const apiLogin = vi.fn();
const apiLogout = vi.fn();
const apiGetCurrentUser = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    login: (...a: unknown[]) => apiLogin(...a),
    logout: (...a: unknown[]) => apiLogout(...a),
    getCurrentUser: (...a: unknown[]) => apiGetCurrentUser(...a),
  },
}));

import { AuthProvider, useAuth, _internalAuth } from '@/lib/auth';

const USER = {
  id: 'u1',
  username: 'alice',
  email: 'a@e.com',
  is_active: true,
  role: 'operator' as const,
  must_change_password: false,
  created_at: '2026-01-01T00:00:00Z',
};

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['runs'], [{ id: 'prev-user-run' }]);
  const clearSpy = vi.spyOn(client, 'clear');
  // Providers layer normally registers this; wire it directly for the test.
  _internalAuth.registerQueryCacheClearer(() => client.clear());
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
  return { client, clearSpy, wrapper };
}

describe('auth session cache hygiene', () => {
  beforeEach(() => {
    apiLogin.mockReset();
    apiLogout.mockReset();
    apiGetCurrentUser.mockReset();
    apiGetCurrentUser.mockRejectedValue({ kind: 'auth', message: 'unauth' });
    _internalAuth.setAccessToken(null);
  });

  afterEach(() => {
    cleanup();
    _internalAuth.registerQueryCacheClearer(null);
    _internalAuth.setAccessToken(null);
  });

  it('clears the query cache on login', async () => {
    apiLogin.mockResolvedValue({
      access_token: 't',
      token_type: 'bearer',
      expires_at: 'x',
      user: USER,
    });
    const { clearSpy, wrapper } = makeWrapper();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.login('alice', 'pw');
    });
    expect(clearSpy).toHaveBeenCalled();
    expect(result.current.isAuthenticated).toBe(true);
  });

  it('clears the query cache on logout', async () => {
    apiLogout.mockResolvedValue({});
    const { clearSpy, wrapper } = makeWrapper();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.logout();
    });
    expect(clearSpy).toHaveBeenCalled();
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('forceSignOut clears user state and cache (no ghost session)', async () => {
    apiLogin.mockResolvedValue({
      access_token: 't',
      token_type: 'bearer',
      expires_at: 'x',
      user: USER,
    });
    const { clearSpy, wrapper } = makeWrapper();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(async () => {
      await result.current.login('alice', 'pw');
    });
    expect(result.current.isAuthenticated).toBe(true);

    act(() => {
      _internalAuth.forceSignOut();
    });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(false));
    expect(_internalAuth.getAccessToken()).toBeNull();
    expect(clearSpy).toHaveBeenCalled();
  });
});
