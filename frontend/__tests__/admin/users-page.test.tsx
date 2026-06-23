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

vi.mock('@/lib/api', () => ({
  api: {
    listUsers: (...a: any[]) => listUsers(...a),
    setUserRole: (...a: any[]) => setUserRole(...a),
    updateUser: (...a: any[]) => updateUser(...a),
    setUserActive: (...a: any[]) => setUserActive(...a),
  },
}));

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ user: { id: 'admin-1', username: 'root', role: 'admin' } }),
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
});
