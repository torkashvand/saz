'use client';

import { usePathname } from 'next/navigation';
import { NavHeader } from './nav-header';
import { ProtectedRoute } from './protected-route';

const PUBLIC_PATHS = ['/login'];

/**
 * Top-level chrome + auth gate.
 *
 * Every page except those in PUBLIC_PATHS gets wrapped in ProtectedRoute,
 * which pushes unauthenticated visitors to /login. The login page itself
 * is rendered raw so users can sign in without an infinite redirect loop.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isPublic = PUBLIC_PATHS.includes(pathname || '');

  return (
    <div className="min-h-screen flex flex-col">
      <NavHeader />
      <main className="flex-1">
        {isPublic ? children : <ProtectedRoute>{children}</ProtectedRoute>}
      </main>
    </div>
  );
}
