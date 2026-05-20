'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, ShieldCheck, KeyRound, UserPlus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorBanner } from '@/components/ui/error-banner';
import { api } from '@/lib/api';
import type { AdminUser } from '@/lib/types';
import type { AppError } from '@/lib/errors';
import { useAuth } from '@/lib/auth';

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => api.listUsers(),
  });

  const [showCreate, setShowCreate] = useState(false);
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });

  const setActiveMut = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api.setUserActive(id, is_active),
    onSuccess: invalidate,
  });

  const setAdminMut = useMutation({
    mutationFn: ({ id, is_admin }: { id: string; is_admin: boolean }) =>
      api.setUserAdmin(id, is_admin),
    onSuccess: invalidate,
  });

  const users = data?.items ?? [];

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Users</h1>
          <p className="text-sm text-slate-600 mt-1">
            Create users, disable accounts, and reset passwords. There is no public registration or
            self-service forgot-password flow — admins are the only path to account recovery.
          </p>
        </div>
        <Button onClick={() => setShowCreate(true)} data-testid="admin-create-user-button">
          <UserPlus className="w-4 h-4 mr-2" /> New user
        </Button>
      </div>

      {error && <ErrorBanner error={error as unknown as AppError} />}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6 text-sm text-slate-500">Loading users…</div>
          ) : (
            <table className="w-full text-sm" data-testid="admin-users-table">
              <thead className="text-left text-slate-500 border-b border-slate-200">
                <tr>
                  <th className="px-4 py-2 font-medium">Username</th>
                  <th className="px-4 py-2 font-medium">Email</th>
                  <th className="px-4 py-2 font-medium">Display name</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Last login</th>
                  <th className="px-4 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const isSelf = currentUser?.id === u.id;
                  return (
                    <tr
                      key={u.id}
                      className={`border-b border-slate-100 ${u.is_active ? '' : 'bg-slate-50/60 text-slate-500'}`}
                      data-testid={`admin-user-row-${u.username}`}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{u.username}</span>
                          {u.is_admin && (
                            <span
                              className="inline-flex items-center gap-1 text-xs text-blue-700 bg-blue-50 px-2 py-0.5 rounded-full"
                              title="Admin"
                            >
                              <ShieldCheck className="w-3 h-3" /> admin
                            </span>
                          )}
                          {u.must_change_password && (
                            <span
                              className="inline-flex items-center gap-1 text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full"
                              title="Must change password on next login"
                            >
                              <ShieldAlert className="w-3 h-3" /> pw change required
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">{u.email}</td>
                      <td className="px-4 py-3 text-slate-600">{u.display_name || '—'}</td>
                      <td className="px-4 py-3">
                        {u.is_active ? (
                          <span className="text-green-700">Active</span>
                        ) : (
                          <span className="text-slate-500">Disabled</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="inline-flex gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setResetTarget(u)}
                            disabled={!u.is_active}
                            title="Reset password"
                            data-testid={`admin-reset-${u.username}`}
                          >
                            <KeyRound className="w-3 h-3 mr-1" /> Reset
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={isSelf || setAdminMut.isPending}
                            onClick={() => {
                              if (!isSelf) {
                                setAdminMut.mutate({ id: u.id, is_admin: !u.is_admin });
                              }
                            }}
                            title={
                              isSelf
                                ? 'Cannot change your own admin capability'
                                : u.is_admin
                                  ? 'Revoke admin'
                                  : 'Grant admin'
                            }
                          >
                            {u.is_admin ? 'Demote' : 'Promote'}
                          </Button>
                          <Button
                            size="sm"
                            variant={u.is_active ? 'outline' : 'default'}
                            disabled={isSelf || setActiveMut.isPending}
                            onClick={() => {
                              if (
                                isSelf ||
                                (!u.is_active && !confirm(`Reactivate ${u.username}?`)) ||
                                (u.is_active && !confirm(`Disable ${u.username}?`))
                              ) {
                                return;
                              }
                              setActiveMut.mutate({ id: u.id, is_active: !u.is_active });
                            }}
                            title={isSelf ? 'Cannot disable your own account' : undefined}
                            data-testid={`admin-toggle-active-${u.username}`}
                          >
                            {u.is_active ? 'Disable' : 'Activate'}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {showCreate && (
        <CreateUserModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            invalidate();
          }}
        />
      )}
      {resetTarget && (
        <ResetPasswordModal
          target={resetTarget}
          onClose={() => setResetTarget(null)}
          onReset={() => {
            setResetTarget(null);
            invalidate();
          }}
        />
      )}
    </div>
  );
}

function CreateUserModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<AppError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await api.createUser({
        username,
        email,
        password,
        display_name: displayName || undefined,
        is_admin: isAdmin,
        // Admin-minted accounts always force a password change on first
        // login. The admin only knows the temporary password they typed
        // here, never the user's final one.
        must_change_password: true,
      });
      onCreated();
    } catch (err) {
      if (err && typeof err === 'object' && 'kind' in err) {
        setError(err as AppError);
      } else {
        setError({ kind: 'unknown', message: 'Failed to create user.' });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell title="Create user" onClose={onClose}>
      {error && <ErrorBanner error={error} />}
      <div className="space-y-3">
        <div className="space-y-1">
          <Label htmlFor="cu-username">Username</Label>
          <Input
            id="cu-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cu-email">Email</Label>
          <Input
            id="cu-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cu-display">Display name (optional)</Label>
          <Input
            id="cu-display"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cu-password">Temporary password</Label>
          <Input
            id="cu-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
          <p className="text-xs text-slate-500">
            Share this with the user out-of-band. They will be required to change it on their first
            login.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
          Make this user an admin
        </label>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <Button variant="ghost" onClick={onClose} disabled={submitting}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={submitting}>
          {submitting ? 'Creating…' : 'Create user'}
        </Button>
      </div>
    </ModalShell>
  );
}

function ResetPasswordModal({
  target,
  onClose,
  onReset,
}: {
  target: AdminUser;
  onClose: () => void;
  onReset: () => void;
}) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<AppError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await api.resetUserPassword(target.id, password);
      onReset();
    } catch (err) {
      if (err && typeof err === 'object' && 'kind' in err) {
        setError(err as AppError);
      } else {
        setError({ kind: 'unknown', message: 'Reset failed.' });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell title={`Reset password for ${target.username}`} onClose={onClose}>
      {error && <ErrorBanner error={error} />}
      <p className="text-sm text-slate-600 mb-3">
        After you reset this password, the user will be required to change it on their next login.
        Share the temporary password with them out-of-band — Saz will not email or display it again.
      </p>
      <div className="space-y-1">
        <Label htmlFor="rp-password">Temporary password</Label>
        <Input
          id="rp-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={8}
          required
        />
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <Button variant="ghost" onClick={onClose} disabled={submitting}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={submitting}>
          {submitting ? 'Resetting…' : 'Reset password'}
        </Button>
      </div>
    </ModalShell>
  );
}

function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-md p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        </div>
        {children}
      </div>
    </div>
  );
}
