'use client';

import Link from 'next/link';
import { useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { LogOut, Menu, Workflow, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth';

export function NavHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isAuthenticated, isAdmin, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  const links = [
    { href: '/', label: 'Home' },
    { href: '/flows', label: 'Flows' },
    { href: '/runs', label: 'Runs' },
    { href: '/credentials', label: 'Credentials' },
    // Admin link is appended only for admins. The backend is the
    // source of truth — hiding the link is UX, not a security boundary.
    ...(isAdmin
      ? [
          { href: '/admin/users', label: 'Admin' },
          { href: '/admin/auth', label: 'SSO' },
        ]
      : []),
  ];

  function handleLogout() {
    logout();
    router.replace('/login');
  }

  const linkClass = (href: string) =>
    `text-sm font-medium transition-colors ${
      pathname === href ? 'text-blue-600' : 'text-slate-600 hover:text-slate-900'
    }`;

  // The nav is reused on the login page (where every link 401s) and on
  // /change-password (where the user is gated until they finish the
  // password change). Hide the links in both places to avoid confusing
  // dead-ends.
  const showLinks = pathname !== '/login' && pathname !== '/change-password';

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
        <Link href="/" className="flex items-center gap-2 text-slate-900 font-semibold text-lg">
          <Workflow className="w-6 h-6 text-blue-600" />
          Saz
        </Link>

        {/* Desktop links */}
        {showLinks && (
          <nav className="hidden md:flex gap-6">
            {links.map((link) => (
              <Link key={link.href} href={link.href} className={linkClass(link.href)}>
                {link.label}
              </Link>
            ))}
          </nav>
        )}

        <div className="flex items-center gap-2">
          {isAuthenticated && user ? (
            <>
              <span
                className="hidden sm:inline text-sm text-slate-700"
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
                className="hidden md:inline-flex"
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

          {/* Mobile menu toggle */}
          {showLinks && (
            <button
              type="button"
              className="md:hidden inline-flex items-center justify-center p-2 -mr-2 text-slate-600 hover:text-slate-900"
              aria-label="Toggle navigation menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
              data-testid="nav-menu-toggle"
            >
              {menuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          )}
        </div>
      </div>

      {/* Mobile dropdown */}
      {showLinks && menuOpen && (
        <nav
          className="md:hidden border-t border-slate-200 px-4 py-2 flex flex-col gap-1"
          data-testid="nav-mobile-menu"
        >
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setMenuOpen(false)}
              className={`py-2 ${linkClass(link.href)}`}
            >
              {link.label}
            </Link>
          ))}
          {isAuthenticated && user && (
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                handleLogout();
              }}
              className="py-2 inline-flex items-center gap-1 text-left text-sm font-medium text-slate-600 hover:text-slate-900"
            >
              <LogOut className="w-4 h-4" />
              Sign out
            </button>
          )}
        </nav>
      )}
    </header>
  );
}
