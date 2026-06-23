'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, ShieldCheck, KeyRound, Pencil, UserPlus, Monitor } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorBanner } from '@/components/ui/error-banner';
import { api } from '@/lib/api';
import type { AdminUser, UserRole } from '@/lib/types';
import type { AppError } from '@/lib/errors';
import { useAuth } from '@/lib/auth';

const ROLE_OPTIONS: UserRole[] = ['admin', 'operator', 'viewer'];

const ROLE_BADGE_CLASS: Record<UserRole, string> = {
  admin: 'text-blue-700 bg-blue-50',
  operator: 'text-slate-700 bg-slate-100',
  viewer: 'text-emerald-700 bg-emerald-50',
};

function RoleBadge({ role }: { role: UserRole }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${ROLE_BADGE_CLASS[role]}`}
      title={`Role: ${role}`}
      data-testid={`role-badge-${role}`}
    >
      <ShieldCheck className="w-3 h-3" /> {role}
    </span>
  );
}

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => api.listUsers(),
  });

  const [showCreate, setShowCreate] = useState(false);
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [editTarget, setEditTarget] = useState<AdminUser | null>(null);
  const [sessionsTarget, setSessionsTarget] = useState<AdminUser | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });

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
                {users.map((u) => (
                  <tr
                    key={u.id}
                    className={`border-b border-slate-100 ${u.is_active ? '' : 'bg-slate-50/60 text-slate-500'}`}
                    data-testid={`admin-user-row-${u.username}`}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{u.username}</span>
                        <RoleBadge role={u.role} />
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
                          onClick={() => setEditTarget(u)}
                          title="Edit profile, role, and status"
                          data-testid={`admin-edit-${u.username}`}
                        >
                          <Pencil className="w-3 h-3 mr-1" /> Edit
                        </Button>
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
                          onClick={() => setSessionsTarget(u)}
                          title="View and revoke active sessions"
                          data-testid={`admin-sessions-${u.username}`}
                        >
                          <Monitor className="w-3 h-3 mr-1" /> Sessions
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
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
      {editTarget && (
        <EditUserModal
          target={editTarget}
          isSelf={currentUser?.id === editTarget.id}
          onClose={() => setEditTarget(null)}
          onSaved={() => {
            setEditTarget(null);
            invalidate();
          }}
        />
      )}
      {sessionsTarget && (
        <SessionsModal target={sessionsTarget} onClose={() => setSessionsTarget(null)} />
      )}
    </div>
  );
}

function CreateUserModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('operator');
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
        role,
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
        <div className="space-y-1">
          <Label htmlFor="cu-role">Role</Label>
          <select
            id="cu-role"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
            data-testid="admin-create-role"
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
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

function EditUserModal({
  target,
  isSelf,
  onClose,
  onSaved,
}: {
  target: AdminUser;
  isSelf: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  // Pre-fill from the current row so the admin sees the value they're
  // editing rather than a blank field.
  const [username, setUsername] = useState(target.username);
  const [email, setEmail] = useState(target.email);
  const [displayName, setDisplayName] = useState(target.display_name ?? '');
  const [role, setRole] = useState<UserRole>(target.role);
  const [isActive, setIsActive] = useState(target.is_active);
  const [error, setError] = useState<AppError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const trimmedUsername = username.trim();
  const trimmedEmail = email.trim();
  const trimmedDisplay = displayName.trim();
  // Only send fields that actually changed so an admin who only wants to
  // tweak the display name doesn't accidentally re-submit a stale email.
  const usernameChanged = trimmedUsername !== target.username;
  const emailChanged = trimmedEmail !== target.email;
  const displayChanged = trimmedDisplay !== (target.display_name ?? '');
  const roleChanged = role !== target.role;
  const activeChanged = isActive !== target.is_active;
  const profileDirty = usernameChanged || emailChanged || displayChanged;
  const dirty = profileDirty || roleChanged || activeChanged;

  async function submit() {
    if (!dirty) {
      onClose();
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      // PATCH profile fields first so that on rename + role-toggle, the
      // role-change audit event already references the new username.
      // Sending display_name as "" clears it on the backend (Optional[str]
      // column) — that's the desired behavior for an admin who explicitly
      // empties the field.
      if (profileDirty) {
        await api.updateUser(target.id, {
          ...(usernameChanged ? { username: trimmedUsername } : {}),
          ...(emailChanged ? { email: trimmedEmail } : {}),
          ...(displayChanged ? { display_name: trimmedDisplay } : {}),
        });
      }
      // Each toggle hits its own dedicated endpoint so the audit trail
      // records "role changed" / "deactivated" as distinct events rather
      // than burying them inside a single "user.updated" blob.
      if (roleChanged) {
        await api.setUserRole(target.id, role);
      }
      if (activeChanged) {
        await api.setUserActive(target.id, isActive);
      }
      onSaved();
    } catch (err) {
      if (err && typeof err === 'object' && 'kind' in err) {
        setError(err as AppError);
      } else {
        setError({ kind: 'unknown', message: 'Failed to update user.' });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell title={`Edit ${target.username}`} onClose={onClose}>
      {error && <ErrorBanner error={error} />}
      <p className="text-sm text-slate-600 mb-3">
        Password is managed separately — use <strong>Reset</strong> on the row to issue a temporary
        password.
      </p>
      <div className="space-y-3">
        <div className="space-y-1">
          <Label htmlFor="eu-username">Username</Label>
          <Input
            id="eu-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            data-testid="admin-edit-username"
            minLength={3}
            maxLength={64}
            required
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="eu-email">Email</Label>
          <Input
            id="eu-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            data-testid="admin-edit-email"
            required
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="eu-display">Display name</Label>
          <Input
            id="eu-display"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            data-testid="admin-edit-display-name"
            placeholder="Leave blank to clear"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="eu-role">Role</Label>
          <select
            id="eu-role"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-50 disabled:text-slate-400"
            value={role}
            disabled={isSelf}
            onChange={(e) => setRole(e.target.value as UserRole)}
            data-testid="admin-edit-role"
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          {isSelf && <span className="text-xs text-slate-500">(cannot change your own role)</span>}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isActive}
            disabled={isSelf}
            onChange={(e) => setIsActive(e.target.checked)}
            data-testid="admin-edit-is-active"
          />
          Active
          {isSelf && (
            <span className="text-xs text-slate-500">(cannot disable your own account)</span>
          )}
        </label>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <Button variant="ghost" onClick={onClose} disabled={submitting}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={submitting || !dirty} data-testid="admin-edit-save">
          {submitting ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </ModalShell>
  );
}

function SessionsModal({ target, onClose }: { target: AdminUser; onClose: () => void }) {
  const queryClient = useQueryClient();
  const queryKey = ['admin', 'user-sessions', target.id];
  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () => api.listUserSessions(target.id),
  });
  const [busy, setBusy] = useState(false);

  const refresh = () => queryClient.invalidateQueries({ queryKey });
  const sessions = data?.items ?? [];

  async function revokeOne(sessionId: string) {
    setBusy(true);
    try {
      await api.revokeUserSession(target.id, sessionId);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function revokeAll() {
    if (!confirm(`Sign ${target.username} out of all ${sessions.length} session(s)?`)) return;
    setBusy(true);
    try {
      await api.revokeAllUserSessions(target.id);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell title={`Sessions for ${target.username}`} onClose={onClose}>
      {error && <ErrorBanner error={error as unknown as AppError} />}
      <p className="text-sm text-slate-600 mb-3">
        Active refresh sessions. Revoking one rejects its access token on the next request; revoking
        all signs the user out everywhere.
      </p>
      {isLoading ? (
        <div className="text-sm text-slate-500">Loading sessions…</div>
      ) : sessions.length === 0 ? (
        <div className="text-sm text-slate-500" data-testid="no-sessions">
          No active sessions.
        </div>
      ) : (
        <div className="space-y-2" data-testid="sessions-list">
          {sessions.map((s) => (
            <div
              key={s.id}
              className="flex items-center justify-between border border-slate-200 rounded-md px-3 py-2"
              data-testid={`session-${s.id}`}
            >
              <div className="text-xs text-slate-600">
                <div className="font-medium text-slate-800">
                  {s.auth_method}
                  {s.provider_key ? ` · ${s.provider_key}` : ''}
                </div>
                <div>{s.ip || 'unknown IP'}</div>
                <div>last used {new Date(s.last_used_at).toLocaleString()}</div>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => revokeOne(s.id)}
                data-testid={`revoke-${s.id}`}
              >
                Revoke
              </Button>
            </div>
          ))}
        </div>
      )}
      <div className="flex justify-between gap-2 mt-4">
        <Button
          variant="outline"
          onClick={revokeAll}
          disabled={busy || sessions.length === 0}
          data-testid="revoke-all-sessions"
        >
          Revoke all
        </Button>
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          Close
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
