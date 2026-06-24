/**
 * The nav collapses its links into a hamburger menu on small screens so the
 * header doesn't overflow the viewport. Pin the toggle behavior.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

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

describe('NavHeader responsive menu', () => {
  beforeEach(() => {
    _internalAuth.setAccessToken('jwt-1');
    apiGetCurrentUser.mockReset();
    apiGetCurrentUser.mockResolvedValue({
      id: 'u1',
      username: 'alice',
      email: 'a@e',
      is_active: true,
      role: 'operator',
      must_change_password: false,
      created_at: '2026-01-01T00:00:00Z',
    });
  });
  afterEach(() => {
    cleanup();
    _internalAuth.setAccessToken(null);
  });

  it('toggles a mobile menu with the nav links', async () => {
    render(
      <AuthProvider>
        <NavHeader />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('nav-menu-toggle')).toBeInTheDocument());

    // Closed by default.
    expect(screen.queryByTestId('nav-mobile-menu')).toBeNull();

    fireEvent.click(screen.getByTestId('nav-menu-toggle'));
    const menu = await screen.findByTestId('nav-mobile-menu');
    expect(menu).toBeInTheDocument();
    expect(within(menu).getByText('Flows')).toBeInTheDocument();

    // Clicking a link closes it again.
    fireEvent.click(within(menu).getByText('Flows'));
    await waitFor(() => expect(screen.queryByTestId('nav-mobile-menu')).toBeNull());
  });
});
