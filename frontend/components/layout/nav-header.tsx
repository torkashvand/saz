'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Workflow } from 'lucide-react';

export function NavHeader() {
  const pathname = usePathname();

  const links = [
    { href: '/', label: 'Home' },
    { href: '/flows', label: 'Flows' },
    { href: '/runs', label: 'Runs' },
    { href: '/credentials', label: 'Credentials' },
  ];

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 text-slate-900 font-semibold text-lg">
          <Workflow className="w-6 h-6 text-blue-600" />
          Saz
        </Link>
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
      </div>
    </header>
  );
}
