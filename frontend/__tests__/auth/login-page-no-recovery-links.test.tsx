/**
 * The product rule is explicit: no public registration, no
 * forgot-password flow. These tests pin that into the UI so a
 * well-meaning future change can't quietly resurrect either link.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => ({ get: () => null }),
  usePathname: () => '/login',
}));

vi.mock('@/lib/api', () => ({
  api: {
    login: vi.fn(),
    getCurrentUser: vi.fn().mockRejectedValue({ kind: 'auth', message: 'nope' }),
  },
}));

import { AuthProvider, _internalAuth } from '@/lib/auth';
import LoginPage from '@/app/login/page';

function renderLogin() {
  return render(
    <AuthProvider>
      <LoginPage />
    </AuthProvider>,
  );
}

describe('LoginPage — no recovery links', () => {
  beforeEach(() => {
    _internalAuth.setAccessToken(null);
  });
  afterEach(() => {
    cleanup();
    _internalAuth.setAccessToken(null);
  });

  it('does not render a "Forgot password" link', () => {
    renderLogin();
    // Match anything resembling a forgot-password or reset-password link.
    const matches = screen.queryAllByText(/forgot.+password|reset.+password|forgot/i);
    expect(matches).toHaveLength(0);
  });

  it('does not render a registration / sign-up link', () => {
    renderLogin();
    const matches = screen.queryAllByText(/sign up|register|create an account|create account/i);
    expect(matches).toHaveLength(0);
  });
});
