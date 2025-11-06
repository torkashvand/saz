import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Providers } from './providers';
import { Toaster } from '@/components/ui/toaster';
import Link from 'next/link';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Saz UI',
  description: 'YAML Forms & Workflow Engine',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          <div className="min-h-screen flex flex-col">
            <header className="border-b">
              <div className="container mx-auto px-4 py-4">
                <nav className="flex items-center justify-between">
                  <Link href="/" className="text-xl font-bold">
                    Saz
                  </Link>
                  <div className="flex gap-6">
                    <Link href="/flows" className="text-sm hover:underline hover:text-blue-600">
                      Flows
                    </Link>
                    <Link href="/runs" className="text-sm hover:underline hover:text-blue-600">
                      Runs
                    </Link>
                    <Link
                      href="/credentials"
                      className="text-sm hover:underline hover:text-blue-600"
                    >
                      Credentials
                    </Link>
                    <Link href="/register" className="text-sm hover:underline hover:text-blue-600">
                      Register Flow
                    </Link>
                    <Link href="/runs/new" className="text-sm hover:underline hover:text-blue-600">
                      New Run
                    </Link>
                  </div>
                </nav>
              </div>
            </header>
            <main className="flex-1">{children}</main>
          </div>
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
