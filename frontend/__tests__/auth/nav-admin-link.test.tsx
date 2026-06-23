/**
 * Admin nav visibility is a UX detail, not a security boundary, but
 * pinning it prevents a careless change from showing the admin link to
 * normal users (which would be confusing — clicks would 403).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/',
}));

const apiGetCurrentUser = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    getCurrentUser: (...args: unknown[]) => apiGetCurrentUser(...args),
    login: vi.fn(),
  },
}));

import { AuthProvider, _internalAuth } from '@/lib/auth';
import { NavHeader } from '@/components/layout/nav-header';

function renderNav() {
  return render(
    <AuthProvider>
      <NavHeader />
    </AuthProvider>,
  );
}

describe('NavHeader admin link', () => {
  beforeEach(() => {
    _internalAuth.setAccessToken('jwt-1');
    apiGetCurrentUser.mockReset();
  });
  afterEach(() => {
    cleanup();
    _internalAuth.setAccessToken(null);
  });

  it('does not show the Admin link for non-admin users', async () => {
    apiGetCurrentUser.mockResolvedValue({
      id: 'u1',
      username: 'alice',
      email: 'a@e',
      is_active: true,
      role: 'operator',
      must_change_password: false,
      created_at: '2026-01-01T00:00:00Z',
    });
    renderNav();
    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument());
    expect(screen.queryByText('Admin')).toBeNull();
  });

  it('shows the Admin link for admin users', async () => {
    apiGetCurrentUser.mockResolvedValue({
      id: 'u1',
      username: 'admin',
      email: 'a@e',
      is_active: true,
      role: 'admin',
      must_change_password: false,
      created_at: '2026-01-01T00:00:00Z',
    });
    renderNav();
    await waitFor(() => expect(screen.getByText('Admin')).toBeInTheDocument());
  });
});
