'use client';

import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';

/**
 * Wraps app pages that require an authenticated session.
 *
 * Behavior:
 *  - While the AuthProvider is still resolving the initial /me probe,
 *    render nothing (avoid flashing a login redirect on a refresh of an
 *    already-authenticated user).
 *  - If unauthenticated, push to /login?next=<current path> so the user
 *    lands back on the same page after signing in.
 *  - If authenticated but ``must_change_password`` is set, push to
 *    /change-password. The backend ALSO blocks operational endpoints in
 *    this state — the redirect is UX, not the security boundary.
 *  - The /login and /change-password pages opt out by not being wrapped.
 */
export function ProtectedRoute({
  children,
  requireAdmin = false,
}: {
  children: React.ReactNode;
  requireAdmin?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { isAuthenticated, isLoading, isAdmin, mustChangePassword } = useAuth();

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated && pathname !== '/login') {
      const next = encodeURIComponent(pathname || '/');
      router.replace(`/login?next=${next}`);
      return;
    }
    if (
      isAuthenticated &&
      mustChangePassword &&
      pathname !== '/change-password' &&
      pathname !== '/login'
    ) {
      router.replace('/change-password');
      return;
    }
    if (requireAdmin && isAuthenticated && !isAdmin) {
      // Non-admins land on / rather than a 403 page; the nav doesn't
      // show admin links to them anyway, so this is the polite fallback
      // if someone deep-links into the admin area.
      router.replace('/');
    }
  }, [isAuthenticated, isLoading, isAdmin, mustChangePassword, pathname, router, requireAdmin]);

  if (isLoading) {
    return null;
  }
  if (!isAuthenticated) {
    return null;
  }
  if (mustChangePassword && pathname !== '/change-password') {
    return null;
  }
  if (requireAdmin && !isAdmin) {
    return null;
  }
  return <>{children}</>;
}
