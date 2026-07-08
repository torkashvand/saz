/**
 * Regression: /login?next= accepted any string starting with '/'. A
 * protocol-relative value like //evil.com passes that check and the router
 * resolves it to https://evil.com — an open redirect after successful login.
 * Only same-origin paths may be honored; anything else falls back to '/'.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { _internalAuth } from '@/lib/auth';

const pushMock = vi.fn();
const replaceMock = vi.fn();
const searchParamsGet = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  useSearchParams: () => ({ get: searchParamsGet }),
  usePathname: () => '/login',
}));

const apiLogin = vi.fn();
const apiGetCurrentUser = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    login: (...args: unknown[]) => apiLogin(...args),
    getCurrentUser: (...args: unknown[]) => apiGetCurrentUser(...args),
    listPublicProviders: () => Promise.resolve([]),
  },
}));

import { AuthProvider } from '@/lib/auth';
import LoginPage from '@/app/login/page';

async function loginWithNext(next: string | null) {
  searchParamsGet.mockImplementation((key: string) => (key === 'next' ? next : null));
  render(
    <AuthProvider>
      <LoginPage />
    </AuthProvider>,
  );
  fireEvent.change(screen.getByLabelText(/username or email/i), {
    target: { value: 'alice' },
  });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pw' } });
  fireEvent.click(screen.getByRole('button', { name: /sign in$/i }));
  await waitFor(() => expect(replaceMock).toHaveBeenCalled());
  return replaceMock.mock.calls[0][0] as string;
}

describe('login ?next= redirect validation', () => {
  beforeEach(() => {
    pushMock.mockReset();
    replaceMock.mockReset();
    searchParamsGet.mockReset();
    apiLogin.mockReset();
    apiGetCurrentUser.mockReset();
    _internalAuth.setAccessToken(null);
    apiGetCurrentUser.mockRejectedValue({ kind: 'auth', message: 'unauth' });
    apiLogin.mockResolvedValue({
      access_token: 'jwt-xyz',
      token_type: 'bearer',
      expires_at: '2099-01-01T00:00:00Z',
      user: {
        id: 'u1',
        username: 'alice',
        email: 'a@e.com',
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
      },
    });
  });

  afterEach(() => {
    cleanup();
    _internalAuth.setAccessToken(null);
  });

  it('honors a same-origin path including its query string', async () => {
    expect(await loginWithNext('/runs?status=failed')).toBe('/runs?status=failed');
  });

  it('rejects protocol-relative //evil.com', async () => {
    expect(await loginWithNext('//evil.com')).toBe('/');
  });

  it('rejects backslash variant /\\evil.com', async () => {
    expect(await loginWithNext('/\\evil.com')).toBe('/');
  });

  it('rejects absolute external URLs', async () => {
    expect(await loginWithNext('https://evil.com/phish')).toBe('/');
  });

  it('falls back to / when next is absent', async () => {
    expect(await loginWithNext(null)).toBe('/');
  });
});
