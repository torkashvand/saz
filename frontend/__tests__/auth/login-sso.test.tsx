/**
 * Login page SSO affordances: enabled providers render as "Sign in with X"
 * buttons pointing at the backend start URL. Password login stays present.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { _internalAuth } from '@/lib/auth';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => ({ get: () => null }),
  usePathname: () => '/login',
}));

const listPublicProviders = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    login: vi.fn(),
    getCurrentUser: vi.fn().mockRejectedValue({ kind: 'auth', message: 'nope' }),
    refreshSession: vi.fn(),
    listPublicProviders: (...a: unknown[]) => listPublicProviders(...a),
  },
}));

import { AuthProvider } from '@/lib/auth';
import LoginPage from '@/app/login/page';

function renderLogin() {
  return render(
    <AuthProvider>
      <LoginPage />
    </AuthProvider>,
  );
}

describe('Login SSO buttons', () => {
  beforeEach(() => {
    _internalAuth.setAccessToken(null);
    listPublicProviders.mockReset();
  });
  afterEach(cleanup);

  it('renders an SSO button per enabled provider', async () => {
    listPublicProviders.mockResolvedValue([
      { provider_key: 'okta', display_name: 'Okta', start_url: '/api/v1/auth/oidc/okta/start' },
    ]);
    renderLogin();
    await waitFor(() => expect(screen.getByTestId('sso-okta')).toBeInTheDocument());
    expect(screen.getByText('Sign in with Okta')).toBeInTheDocument();
    // Password login remains available alongside SSO.
    expect(screen.getByLabelText('Username or email')).toBeInTheDocument();
  });

  it('shows no SSO section when no providers are configured', async () => {
    listPublicProviders.mockResolvedValue([]);
    renderLogin();
    await waitFor(() => expect(screen.getByLabelText('Username or email')).toBeInTheDocument());
    expect(screen.queryByText('or continue with')).toBeNull();
  });
});
