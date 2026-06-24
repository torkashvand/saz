'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck, Plug, Trash2, Pencil, Eye, EyeOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { ErrorBanner } from '@/components/ui/error-banner';
import { api } from '@/lib/api';
import type { AuthProvider, CreateAuthProviderRequest } from '@/lib/types';
import type { AppError } from '@/lib/errors';

export default function AdminAuthProvidersPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'auth-providers'],
    queryFn: () => api.listAuthProviders(),
  });

  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<AuthProvider | null>(null);
  const [testResult, setTestResult] = useState<{ key: string; ok: boolean; detail: string } | null>(
    null,
  );

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['admin', 'auth-providers'] });
  const providers = data?.items ?? [];

  async function runTest(p: AuthProvider) {
    setTestResult(null);
    try {
      const r = await api.testAuthProvider(p.id);
      setTestResult({ key: p.provider_key, ok: r.ok, detail: r.detail });
    } catch {
      setTestResult({ key: p.provider_key, ok: false, detail: 'Test request failed.' });
    }
  }

  async function remove(p: AuthProvider) {
    if (!confirm(`Delete SSO provider "${p.display_name}"?`)) return;
    await api.deleteAuthProvider(p.id);
    invalidate();
  }

  async function toggleEnabled(p: AuthProvider) {
    await api.updateAuthProvider(p.id, { enabled: !p.enabled });
    invalidate();
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">SSO providers</h1>
          <p className="text-sm text-slate-600 mt-1">
            Configure OIDC identity providers. Client secrets are write-only and never shown after
            saving. Local password login always remains available as a break-glass path.
          </p>
        </div>
        <Button onClick={() => setShowCreate(true)} data-testid="admin-add-provider">
          <Plug className="w-4 h-4 mr-2" /> Add provider
        </Button>
      </div>

      {error && <ErrorBanner error={error as unknown as AppError} />}
      {testResult && (
        <div
          className={`text-sm rounded-md px-3 py-2 ${testResult.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}
        >
          <strong>{testResult.key}</strong>: {testResult.detail}
        </div>
      )}

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-6 text-sm text-slate-500">Loading providers…</div>
          ) : providers.length === 0 ? (
            <div className="p-6 text-sm text-slate-500">No SSO providers configured yet.</div>
          ) : (
            <table className="w-full text-sm" data-testid="admin-providers-table">
              <thead className="text-left text-slate-500 border-b border-slate-200">
                <tr>
                  <th className="px-4 py-2 font-medium">Provider</th>
                  <th className="px-4 py-2 font-medium">Issuer</th>
                  <th className="px-4 py-2 font-medium">JIT</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {providers.map((p) => (
                  <tr
                    key={p.id}
                    className="border-b border-slate-100"
                    data-testid={`provider-row-${p.provider_key}`}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium">{p.display_name}</div>
                      <div className="text-xs text-slate-500">{p.provider_key}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{p.issuer}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {p.jit_enabled ? `${p.default_role}` : 'off'}
                    </td>
                    <td className="px-4 py-3">
                      {p.enabled ? (
                        <span className="inline-flex items-center gap-1 text-emerald-700">
                          <ShieldCheck className="w-3 h-3" /> enabled
                        </span>
                      ) : (
                        <span className="text-slate-500">disabled</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex gap-2">
                        <Button size="sm" variant="outline" onClick={() => toggleEnabled(p)}>
                          {p.enabled ? 'Disable' : 'Enable'}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => runTest(p)}>
                          Test
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setEditTarget(p)}
                          data-testid={`provider-edit-${p.provider_key}`}
                        >
                          <Pencil className="w-3 h-3" />
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => remove(p)}>
                          <Trash2 className="w-3 h-3" />
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
        <ProviderModal
          onClose={() => setShowCreate(false)}
          onSaved={() => {
            setShowCreate(false);
            invalidate();
          }}
        />
      )}
      {editTarget && (
        <ProviderModal
          target={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={() => {
            setEditTarget(null);
            invalidate();
          }}
        />
      )}
    </div>
  );
}

function ProviderModal({
  target,
  onClose,
  onSaved,
}: {
  target?: AuthProvider;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!target;
  const [form, setForm] = useState<CreateAuthProviderRequest>({
    provider_key: target?.provider_key ?? '',
    display_name: target?.display_name ?? '',
    issuer: target?.issuer ?? '',
    client_id: target?.client_id ?? '',
    client_secret: '',
    scopes: target?.scopes ?? 'openid profile email',
    redirect_uri: target?.redirect_uri ?? '',
    enabled: target?.enabled ?? false,
    jit_enabled: target?.jit_enabled ?? false,
    default_role: target?.default_role ?? 'viewer',
  });
  const [error, setError] = useState<AppError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showSecret, setShowSecret] = useState(false);

  const set = (patch: Partial<CreateAuthProviderRequest>) => setForm((f) => ({ ...f, ...patch }));

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      if (isEdit && target) {
        const { provider_key: _k, client_secret, ...rest } = form;
        await api.updateAuthProvider(target.id, {
          ...rest,
          ...(client_secret ? { client_secret } : {}),
        });
      } else {
        await api.createAuthProvider(form);
      }
      onSaved();
    } catch (err) {
      setError(
        err && typeof err === 'object' && 'kind' in err
          ? (err as AppError)
          : { kind: 'unknown', message: 'Failed to save provider.' },
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-lg p-5 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-slate-900 mb-3">
          {isEdit ? `Edit ${target?.display_name}` : 'Add SSO provider'}
        </h2>
        {error && <ErrorBanner error={error} />}
        <div className="space-y-3">
          {!isEdit && (
            <Field label="Provider key (slug)">
              <Input
                value={form.provider_key}
                onChange={(e) => set({ provider_key: e.target.value })}
                placeholder="okta"
                data-testid="provider-key"
              />
            </Field>
          )}
          <Field label="Display name">
            <Input
              value={form.display_name}
              onChange={(e) => set({ display_name: e.target.value })}
              placeholder="Okta"
            />
          </Field>
          <Field label="Issuer URL">
            <Input
              value={form.issuer}
              onChange={(e) => set({ issuer: e.target.value })}
              placeholder="https://example.okta.com"
            />
          </Field>
          <Field label="Client ID">
            <Input value={form.client_id} onChange={(e) => set({ client_id: e.target.value })} />
          </Field>
          <Field
            label={
              isEdit
                ? 'Client secret (leave blank to keep)'
                : 'Client secret (leave blank for public/PKCE clients)'
            }
          >
            <div className="relative">
              <Input
                type={showSecret ? 'text' : 'password'}
                autoComplete="off"
                data-1p-ignore
                data-lpignore="true"
                data-bwignore
                value={form.client_secret}
                onChange={(e) => set({ client_secret: e.target.value })}
                className="pr-10"
                data-testid="provider-secret"
              />
              <button
                type="button"
                onClick={() => setShowSecret((s) => !s)}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-600"
                aria-label={showSecret ? 'Hide secret' : 'Show secret'}
              >
                {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </Field>
          <Field label="Scopes">
            <Input value={form.scopes} onChange={(e) => set({ scopes: e.target.value })} />
          </Field>
          <Field label="Redirect URI (leave blank for default backend callback)">
            <Input
              value={form.redirect_uri ?? ''}
              onChange={(e) => set({ redirect_uri: e.target.value })}
              placeholder="http://localhost:8000/api/v1/auth/oidc/callback"
              data-testid="provider-redirect-uri"
            />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.jit_enabled}
              onChange={(e) => set({ jit_enabled: e.target.checked })}
            />
            Auto-create users on first login (JIT)
          </label>
          {form.jit_enabled && (
            <Field label="Default role for new users">
              <select
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                value={form.default_role}
                onChange={(e) => set({ default_role: e.target.value as 'viewer' | 'operator' })}
              >
                <option value="viewer">viewer</option>
                <option value="operator">operator</option>
              </select>
            </Field>
          )}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => set({ enabled: e.target.checked })}
            />
            Enabled (show on login screen)
          </label>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={submitting} data-testid="provider-save">
            {submitting ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
