'use client';

import { usePathname } from 'next/navigation';
import { NavHeader } from './nav-header';
import { ProtectedRoute } from './protected-route';

const PUBLIC_PATHS = ['/login'];
const ADMIN_PATH_PREFIX = '/admin';

/**
 * Top-level chrome + auth gate.
 *
 * - PUBLIC_PATHS: rendered raw (no auth check).
 * - /change-password: wrapped in ProtectedRoute but the route guard
 *   knows to allow users with must_change_password through.
 * - /admin/*: wrapped with requireAdmin=true so non-admins are bounced.
 * - Everything else: standard authenticated + password-set gate.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || '';
  const isPublic = PUBLIC_PATHS.includes(pathname);
  const requireAdmin = pathname.startsWith(ADMIN_PATH_PREFIX);

  let content: React.ReactNode = children;
  if (!isPublic) {
    content = <ProtectedRoute requireAdmin={requireAdmin}>{children}</ProtectedRoute>;
  }

  return (
    <div className="min-h-screen flex flex-col">
      <NavHeader />
      <main className="flex-1">{content}</main>
    </div>
  );
}
