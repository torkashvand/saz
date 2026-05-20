'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { LogOut, Workflow } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth';

export function NavHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isAuthenticated, logout } = useAuth();

  const links = [
    { href: '/', label: 'Home' },
    { href: '/flows', label: 'Flows' },
    { href: '/runs', label: 'Runs' },
    { href: '/credentials', label: 'Credentials' },
  ];

  function handleLogout() {
    logout();
    router.replace('/login');
  }

  // The nav is reused on the login page itself; hide the navigation links
  // there since they all 401 without a session and just confuse users.
  const showLinks = pathname !== '/login';

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 text-slate-900 font-semibold text-lg">
          <Workflow className="w-6 h-6 text-blue-600" />
          Saz
        </Link>
        {showLinks && (
          <nav className="flex gap-6">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`text-sm font-medium transition-colors ${
                  pathname === link.href ? 'text-blue-600' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {link.label}
              </Link>
            ))}
          </nav>
        )}
        <div className="flex items-center gap-3">
          {isAuthenticated && user ? (
            <>
              <span
                className="text-sm text-slate-700"
                data-testid="nav-current-user"
                title={user.email}
              >
                {user.display_name || user.username}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleLogout}
                aria-label="Sign out"
                data-testid="nav-logout"
              >
                <LogOut className="w-4 h-4 mr-1" />
                Sign out
              </Button>
            </>
          ) : (
            pathname !== '/login' && (
              <Link
                href="/login"
                className="text-sm font-medium text-blue-600 hover:text-blue-700"
                data-testid="nav-login"
              >
                Sign in
              </Link>
            )
          )}
        </div>
      </div>
    </header>
  );
}
