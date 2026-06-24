/**
 * SSO completion must call /refresh exactly once. React StrictMode double-
 * invokes effects; a second /refresh replays the just-rotated refresh secret,
 * which the backend treats as theft and revokes the session — bouncing the
 * user straight back to login after a "successful" SSO sign-in.
 */

import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, waitFor } from '@testing-library/react';
import { _internalAuth } from '@/lib/auth';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => ({ get: (k: string) => (k === 'sso' ? 'ok' : null) }),
  usePathname: () => '/login',
}));

const refreshSession = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    login: vi.fn(),
    getCurrentUser: vi.fn().mockRejectedValue({ kind: 'auth', message: 'nope' }),
    refreshSession: (...a: unknown[]) => refreshSession(...a),
    listPublicProviders: vi.fn().mockResolvedValue([]),
  },
}));

import { AuthProvider } from '@/lib/auth';
import LoginPage from '@/app/login/page';

describe('SSO completion idempotency', () => {
  afterEach(cleanup);

  it('calls refreshSession once even under StrictMode double-invoke', async () => {
    _internalAuth.setAccessToken(null);
    refreshSession.mockResolvedValue({
      access_token: 'tok',
      expires_at: new Date().toISOString(),
      user: { id: 'u1', username: 'sso', role: 'viewer', is_active: true },
    });

    render(
      <StrictMode>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </StrictMode>,
    );

    await waitFor(() => expect(refreshSession).toHaveBeenCalledTimes(1));
    // Give any erroneous second invocation a chance to fire before asserting.
    await new Promise((r) => setTimeout(r, 20));
    expect(refreshSession).toHaveBeenCalledTimes(1);
  });
});
