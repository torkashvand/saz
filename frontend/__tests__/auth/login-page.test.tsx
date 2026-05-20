/**
 * Login form behavior:
 *  - Valid credentials → calls api.login, stores token, redirects to /
 *    (or to ?next= when present).
 *  - Invalid credentials → shows the server's error message and keeps
 *    the user on the login page.
 *
 * We mock the next/navigation router and the api module so the test
 * focuses on UI semantics, not on the network or framework.
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
  },
}));

import { AuthProvider } from '@/lib/auth';
import LoginPage from '@/app/login/page';

function renderPage() {
  return render(
    <AuthProvider>
      <LoginPage />
    </AuthProvider>,
  );
}

describe('LoginPage', () => {
  beforeEach(() => {
    pushMock.mockReset();
    replaceMock.mockReset();
    searchParamsGet.mockReset();
    apiLogin.mockReset();
    apiGetCurrentUser.mockReset();
    _internalAuth.setAccessToken(null);
    // No stored token + no /me probe response — AuthProvider settles to
    // unauthenticated quickly without us having to wait on a fetch.
    apiGetCurrentUser.mockRejectedValue({ kind: 'auth', message: 'unauth' });
  });

  afterEach(() => {
    cleanup();
    _internalAuth.setAccessToken(null);
  });

  it('submits credentials, stores token, and redirects on success', async () => {
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

    renderPage();

    fireEvent.change(screen.getByLabelText(/username or email/i), {
      target: { value: 'alice' },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: 'hunter222' },
    });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(apiLogin).toHaveBeenCalledTimes(1));
    expect(apiLogin).toHaveBeenCalledWith({ identifier: 'alice', password: 'hunter222' });
    await waitFor(() => expect(_internalAuth.getAccessToken()).toBe('jwt-xyz'));
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('/'));
  });

  it('respects ?next= when redirecting after login', async () => {
    searchParamsGet.mockImplementation((k: string) => (k === 'next' ? '/flows/abc' : null));
    apiLogin.mockResolvedValue({
      access_token: 't',
      token_type: 'bearer',
      expires_at: '2099-01-01T00:00:00Z',
      user: { id: 'u1', username: 'a', email: 'a@e', is_active: true, created_at: '2026-01-01' },
    });

    renderPage();
    fireEvent.change(screen.getByLabelText(/username or email/i), { target: { value: 'a' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'p' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('/flows/abc'));
  });

  it('shows an error and keeps the user on the page on failed login', async () => {
    apiLogin.mockRejectedValue({ kind: 'auth', message: 'invalid credentials' });

    renderPage();
    fireEvent.change(screen.getByLabelText(/username or email/i), { target: { value: 'a' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'bad' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument());
    expect(replaceMock).not.toHaveBeenCalled();
    expect(_internalAuth.getAccessToken()).toBeNull();
  });
});
