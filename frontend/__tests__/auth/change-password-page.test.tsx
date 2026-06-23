/**
 * Change-password screen behavior:
 *  - Submit calls api.changePassword
 *  - On success, redirects to /
 *  - Mismatched new/confirm shows an error and does not call the API
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const replaceMock = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: replaceMock }),
  useSearchParams: () => ({ get: () => null }),
  usePathname: () => '/change-password',
}));

const apiChangePassword = vi.fn();
const apiGetCurrentUser = vi.fn();
vi.mock('@/lib/api', () => ({
  api: {
    changePassword: (...args: unknown[]) => apiChangePassword(...args),
    getCurrentUser: (...args: unknown[]) => apiGetCurrentUser(...args),
  },
}));

import { AuthProvider, _internalAuth } from '@/lib/auth';
import ChangePasswordPage from '@/app/change-password/page';

function renderPage() {
  return render(
    <AuthProvider>
      <ChangePasswordPage />
    </AuthProvider>,
  );
}

describe('ChangePasswordPage', () => {
  beforeEach(() => {
    replaceMock.mockReset();
    apiChangePassword.mockReset();
    apiGetCurrentUser.mockReset();
    // Pretend the user just logged in with a forced-change token.
    _internalAuth.setAccessToken('jwt-1');
    apiGetCurrentUser.mockResolvedValue({
      id: 'u1',
      username: 'alice',
      email: 'alice@example.com',
      is_active: true,
      role: 'operator',
      must_change_password: true,
      created_at: '2026-01-01T00:00:00Z',
    });
  });
  afterEach(() => {
    cleanup();
    _internalAuth.setAccessToken(null);
  });

  it('submits the change and redirects on success', async () => {
    apiChangePassword.mockResolvedValue({
      id: 'u1',
      username: 'alice',
      email: 'alice@example.com',
      is_active: true,
      role: 'operator',
      must_change_password: false,
      created_at: '2026-01-01T00:00:00Z',
    });

    renderPage();
    fireEvent.change(screen.getByLabelText(/current password/i), {
      target: { value: 'temp-pw' },
    });
    fireEvent.change(screen.getByLabelText(/^new password/i), {
      target: { value: 'self-chosen-pw-1' },
    });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), {
      target: { value: 'self-chosen-pw-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: /update password/i }));

    await waitFor(() => expect(apiChangePassword).toHaveBeenCalledTimes(1));
    expect(apiChangePassword).toHaveBeenCalledWith({
      current_password: 'temp-pw',
      new_password: 'self-chosen-pw-1',
    });
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith('/'));
  });

  it('rejects mismatched confirmation without calling the API', async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText(/current password/i), {
      target: { value: 'temp-pw' },
    });
    fireEvent.change(screen.getByLabelText(/^new password/i), {
      target: { value: 'self-chosen-pw-1' },
    });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), {
      target: { value: 'different-pw-2' },
    });
    fireEvent.click(screen.getByRole('button', { name: /update password/i }));

    await waitFor(() => {
      expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
    });
    expect(apiChangePassword).not.toHaveBeenCalled();
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
