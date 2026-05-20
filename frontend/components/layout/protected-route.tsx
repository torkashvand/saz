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
 *  - The /login page itself opts out by not being wrapped.
 */
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { isAuthenticated, isLoading } = useAuth();

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated && pathname !== '/login') {
      const next = encodeURIComponent(pathname || '/');
      router.replace(`/login?next=${next}`);
    }
  }, [isAuthenticated, isLoading, pathname, router]);

  if (isLoading) {
    return null;
  }
  if (!isAuthenticated) {
    return null;
  }
  return <>{children}</>;
}
