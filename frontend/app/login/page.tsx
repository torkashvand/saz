'use client';

import { FormEvent, Suspense, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ErrorBanner } from '@/components/ui/error-banner';
import { useAuth } from '@/lib/auth';
import { api, API_BASE_URL } from '@/lib/api';
import { sanitizeNextPath } from '@/lib/utils';
import type { AppError } from '@/lib/errors';
import type { PublicProvider } from '@/lib/types';

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, completeSso } = useAuth();
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<AppError | null>(null);
  const [providers, setProviders] = useState<PublicProvider[]>([]);

  // Load SSO providers for the login screen (best-effort — a failure just
  // leaves password login available).
  useEffect(() => {
    api
      .listPublicProviders()
      .then(setProviders)
      .catch(() => setProviders([]));
  }, []);

  // Handle the OIDC redirect back from the callback. Guard against running
  // twice — React StrictMode double-invokes effects in dev, and calling
  // /refresh a second time replays the just-rotated refresh secret, which the
  // backend treats as theft and revokes the session (bouncing the user back
  // to login).
  const ssoHandled = useRef(false);
  useEffect(() => {
    const sso = searchParams.get('sso');
    if (sso === 'ok') {
      if (ssoHandled.current) return;
      ssoHandled.current = true;
      completeSso()
        .then(() => router.replace('/'))
        .catch(() =>
          setError({ kind: 'unknown', message: 'Single sign-on did not complete. Try again.' }),
        );
    } else if (sso === 'error') {
      setError({
        kind: 'unknown',
        message: searchParams.get('reason') || 'Single sign-on failed.',
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(identifier.trim(), password);
      // ?next= lets the redirect target be carried through from a
      // ProtectedRoute interception so users land back on the page they
      // actually wanted instead of dropping to "/".
      router.replace(sanitizeNextPath(searchParams.get('next')));
    } catch (err) {
      if (err && typeof err === 'object' && 'kind' in err) {
        setError(err as AppError);
      } else {
        setError({
          kind: 'unknown',
          message: 'Login failed. Please try again.',
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign in to Saz</CardTitle>
          <CardDescription>
            Use your username or email to sign in, or continue with a configured single sign-on
            provider.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && <ErrorBanner error={error} />}
            <div className="space-y-2">
              <Label htmlFor="identifier">Username or email</Label>
              <Input
                id="identifier"
                name="identifier"
                type="text"
                autoComplete="username"
                autoFocus
                required
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                disabled={submitting}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
              />
            </div>
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          {providers.length > 0 && (
            <div className="mt-6 space-y-2">
              <div className="relative text-center text-xs text-slate-400">
                <span className="bg-white px-2 relative z-10">or continue with</span>
                <div className="absolute inset-x-0 top-1/2 border-t border-slate-200" />
              </div>
              {providers.map((p) => (
                <Button
                  key={p.provider_key}
                  type="button"
                  variant="outline"
                  className="w-full"
                  data-testid={`sso-${p.provider_key}`}
                  onClick={() => {
                    window.location.href = `${API_BASE_URL}${p.start_url}`;
                  }}
                >
                  Sign in with {p.display_name}
                </Button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// useSearchParams() forces this subtree to bail out of static prerendering, so
// it must sit under a Suspense boundary or `next build` fails on /login.
export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
