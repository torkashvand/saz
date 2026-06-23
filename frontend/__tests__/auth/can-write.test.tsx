/**
 * canWrite is the UI's read of the role tier: admin/operator may write,
 * viewer may not. It mirrors the backend get_operator_user gate; pages use
 * it to hide write affordances a viewer would only get a 403 from.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

const apiGetCurrentUser = vi.fn();
vi.mock('@/lib/api', () => ({
  api: { getCurrentUser: (...a: unknown[]) => apiGetCurrentUser(...a), login: vi.fn() },
}));

import { AuthProvider, useAuth, _internalAuth } from '@/lib/auth';

function Probe() {
  const { role, canWrite } = useAuth();
  return <div data-testid="probe">{`${role ?? 'none'}:${canWrite}`}</div>;
}

function renderProbe() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

function mockUser(role: string) {
  apiGetCurrentUser.mockResolvedValue({
    id: 'u1',
    username: 'u',
    email: 'u@e',
    is_active: true,
    role,
    is_admin: role === 'admin',
    must_change_password: false,
    created_at: '2026-01-01T00:00:00Z',
  });
}

describe('useAuth canWrite', () => {
  beforeEach(() => {
    _internalAuth.setAccessToken('jwt-1');
    apiGetCurrentUser.mockReset();
  });
  afterEach(() => {
    cleanup();
    _internalAuth.setAccessToken(null);
  });

  it.each([
    ['admin', true],
    ['operator', true],
    ['viewer', false],
  ])('role %s → canWrite %s', async (role, expected) => {
    mockUser(role);
    renderProbe();
    await waitFor(() =>
      expect(screen.getByTestId('probe')).toHaveTextContent(`${role}:${expected}`),
    );
  });
});
