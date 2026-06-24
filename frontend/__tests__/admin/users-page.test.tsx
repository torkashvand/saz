/**
 * Admin users page: role is the authorization tier. These tests pin the
 * page-level wiring — the role badge in the list and the edit dialog's
 * role selector hitting the dedicated set_role endpoint — so a careless
 * change can't silently drop role management from the only UI that has it.
 */

import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

afterEach(cleanup);

const listUsers = vi.fn();
const setUserRole = vi.fn();
const updateUser = vi.fn();
const setUserActive = vi.fn();
const listUserSessions = vi.fn();
const revokeUserSession = vi.fn();
const revokeAllUserSessions = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    listUsers: (...a: any[]) => listUsers(...a),
    setUserRole: (...a: any[]) => setUserRole(...a),
    updateUser: (...a: any[]) => updateUser(...a),
    setUserActive: (...a: any[]) => setUserActive(...a),
    listUserSessions: (...a: any[]) => listUserSessions(...a),
    revokeUserSession: (...a: any[]) => revokeUserSession(...a),
    revokeAllUserSessions: (...a: any[]) => revokeAllUserSessions(...a),
  },
}));

const logout = vi.fn();
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: { id: 'admin-1', username: 'root', role: 'admin' },
    logout,
  }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

import AdminUsersPage from '@/app/admin/users/page';

function user(overrides: Record<string, unknown>) {
  return {
    id: 'u1',
    username: 'alice',
    email: 'alice@example.com',
    display_name: null,
    is_active: true,
    role: 'operator',
    must_change_password: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    last_login_at: null,
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdminUsersPage />
    </QueryClientProvider>,
  );
}

describe('AdminUsersPage role management', () => {
  beforeEach(() => {
    listUsers.mockReset();
    setUserRole.mockReset();
    updateUser.mockReset();
    setUserActive.mockReset();
    listUserSessions.mockReset();
    revokeUserSession.mockReset();
    revokeAllUserSessions.mockReset();
    logout.mockReset();
  });

  it('renders a role badge for each tier', async () => {
    listUsers.mockResolvedValue({
      items: [
        user({ id: 'a', username: 'theadmin', role: 'admin' }),
        user({ id: 'o', username: 'theop', role: 'operator' }),
        user({ id: 'v', username: 'theviewer', role: 'viewer' }),
      ],
      total: 3,
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('theadmin')).toBeInTheDocument());
    expect(screen.getByTestId('role-badge-admin')).toBeInTheDocument();
    expect(screen.getByTestId('role-badge-operator')).toBeInTheDocument();
    expect(screen.getByTestId('role-badge-viewer')).toBeInTheDocument();
  });

  it('flags SSO vs local accounts in the list', async () => {
    listUsers.mockResolvedValue({
      items: [
        user({ id: 's', username: 'ssoer', sso_providers: ['okta'] }),
        user({ id: 'l', username: 'localer', sso_providers: [] }),
      ],
      total: 2,
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('ssoer')).toBeInTheDocument());
    expect(screen.getByTestId('user-sso-ssoer')).toBeInTheDocument();
    expect(screen.queryByTestId('user-local-ssoer')).toBeNull();
    expect(screen.getByTestId('user-local-localer')).toBeInTheDocument();
    expect(screen.queryByTestId('user-sso-localer')).toBeNull();
  });

  it('changing the role in the edit dialog calls set_role with the new tier', async () => {
    listUsers.mockResolvedValue({ items: [user({})], total: 1 });
    setUserRole.mockResolvedValue(user({ role: 'viewer' }));
    renderPage();

    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('admin-edit-alice'));

    const select = await screen.findByTestId('admin-edit-role');
    fireEvent.change(select, { target: { value: 'viewer' } });
    fireEvent.click(screen.getByTestId('admin-edit-save'));

    await waitFor(() => expect(setUserRole).toHaveBeenCalledWith('u1', 'viewer'));
    expect(updateUser).not.toHaveBeenCalled();
    expect(setUserActive).not.toHaveBeenCalled();
  });

  it('removes a revoked session from the list without a manual refresh', async () => {
    listUsers.mockResolvedValue({ items: [user({})], total: 1 });
    const session = (id: string, is_current = false) => ({
      id,
      auth_method: 'local',
      provider_key: null,
      created_at: '2026-01-01T00:00:00Z',
      last_used_at: '2026-01-02T00:00:00Z',
      idle_expires_at: '2026-01-09T00:00:00Z',
      absolute_expires_at: '2026-02-01T00:00:00Z',
      ip: '10.0.0.1',
      user_agent: 'curl',
      is_current,
    });
    // First load returns two sessions; the post-revoke reconcile returns one.
    listUserSessions
      .mockResolvedValueOnce({ items: [session('sess-1'), session('sess-2')], total: 2 })
      .mockResolvedValue({ items: [session('sess-2')], total: 1 });
    revokeUserSession.mockResolvedValue(undefined);
    renderPage();

    await waitFor(() => expect(screen.getByText('alice')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('admin-sessions-alice'));
    expect(await screen.findByTestId('session-sess-1')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('revoke-sess-1'));
    await waitFor(() => expect(revokeUserSession).toHaveBeenCalledWith('u1', 'sess-1'));
    // The row disappears without the user refreshing the page.
    await waitFor(() => expect(screen.queryByTestId('session-sess-1')).toBeNull());
    expect(screen.getByTestId('session-sess-2')).toBeInTheDocument();
    // Revoking another user's session must not log the admin out.
    expect(logout).not.toHaveBeenCalled();
  });

  it('logs the admin out when they revoke their own current session', async () => {
    listUsers.mockResolvedValue({
      items: [user({ id: 'admin-1', username: 'root', role: 'admin' })],
      total: 1,
    });
    listUserSessions.mockResolvedValue({
      items: [
        {
          id: 'sess-self',
          auth_method: 'local',
          provider_key: null,
          created_at: '2026-01-01T00:00:00Z',
          last_used_at: '2026-01-02T00:00:00Z',
          idle_expires_at: '2026-01-09T00:00:00Z',
          absolute_expires_at: '2026-02-01T00:00:00Z',
          ip: '10.0.0.1',
          user_agent: 'curl',
          is_current: true,
        },
      ],
      total: 1,
    });
    revokeUserSession.mockResolvedValue(undefined);
    logout.mockResolvedValue(undefined);
    renderPage();

    await waitFor(() => expect(screen.getByText('root')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('admin-sessions-root'));
    expect(await screen.findByTestId('session-sess-self')).toBeInTheDocument();
    expect(screen.getByTestId('session-current-sess-self')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('revoke-sess-self'));
    await waitFor(() => expect(revokeUserSession).toHaveBeenCalledWith('admin-1', 'sess-self'));
    await waitFor(() => expect(logout).toHaveBeenCalled());
  });
});
