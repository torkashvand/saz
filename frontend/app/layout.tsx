import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Providers } from './providers';
import { Toaster } from '@/components/ui/toaster';
import { AppShell } from '@/components/layout/app-shell';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Saz - Agentic Workflow Engine',
  description: 'Internal platform for auditable, policy-driven workflows',
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
          <AppShell>{children}</AppShell>
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
