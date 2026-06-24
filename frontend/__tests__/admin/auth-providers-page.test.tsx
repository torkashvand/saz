/**
 * Admin SSO providers page: lists configured providers and creates new ones.
 * Pins that the client secret field is sent on create and that the create
 * call is wired through.
 */

import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

afterEach(cleanup);

const listAuthProviders = vi.fn();
const createAuthProvider = vi.fn();

vi.mock('@/lib/api', () => ({
  api: {
    listAuthProviders: (...a: any[]) => listAuthProviders(...a),
    createAuthProvider: (...a: any[]) => createAuthProvider(...a),
    updateAuthProvider: vi.fn(),
    deleteAuthProvider: vi.fn(),
    testAuthProvider: vi.fn(),
  },
}));

import AdminAuthProvidersPage from '@/app/admin/auth/page';

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdminAuthProvidersPage />
    </QueryClientProvider>,
  );
}

describe('AdminAuthProvidersPage', () => {
  beforeEach(() => {
    listAuthProviders.mockReset();
    createAuthProvider.mockReset();
  });

  it('renders configured providers', async () => {
    listAuthProviders.mockResolvedValue({
      items: [
        {
          id: 'p1',
          provider_key: 'okta',
          display_name: 'Okta',
          issuer: 'https://x.okta.com',
          client_id: 'c',
          scopes: 'openid',
          enabled: true,
          jit_enabled: false,
          default_role: 'viewer',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('Okta')).toBeInTheDocument());
    expect(screen.getByTestId('provider-row-okta')).toBeInTheDocument();
    expect(screen.getByText('enabled')).toBeInTheDocument();
  });

  it('creates a provider with the entered secret', async () => {
    listAuthProviders.mockResolvedValue({ items: [], total: 0 });
    createAuthProvider.mockResolvedValue({ id: 'new' });
    renderPage();

    await waitFor(() => expect(screen.getByTestId('admin-add-provider')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('admin-add-provider'));

    fireEvent.change(screen.getByTestId('provider-key'), { target: { value: 'google' } });
    fireEvent.click(screen.getByTestId('provider-save'));

    await waitFor(() => expect(createAuthProvider).toHaveBeenCalled());
    expect(createAuthProvider.mock.calls[0][0].provider_key).toBe('google');
  });

  it('keeps password managers off the secret field and toggles visibility', async () => {
    listAuthProviders.mockResolvedValue({ items: [], total: 0 });
    renderPage();

    await waitFor(() => expect(screen.getByTestId('admin-add-provider')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('admin-add-provider'));

    const secret = screen.getByTestId('provider-secret') as HTMLInputElement;
    // Opt-out attributes that stop extensions from hijacking (and blocking paste on) the field.
    expect(secret.getAttribute('autocomplete')).toBe('off');
    expect(secret.getAttribute('data-1p-ignore')).not.toBeNull();
    expect(secret.getAttribute('data-lpignore')).toBe('true');
    expect(secret.getAttribute('data-bwignore')).not.toBeNull();

    // Masked by default, reveal toggle flips to a plain text field.
    expect(secret.type).toBe('password');
    fireEvent.click(screen.getByLabelText('Show secret'));
    expect((screen.getByTestId('provider-secret') as HTMLInputElement).type).toBe('text');
    fireEvent.click(screen.getByLabelText('Hide secret'));
    expect((screen.getByTestId('provider-secret') as HTMLInputElement).type).toBe('password');
  });
});
