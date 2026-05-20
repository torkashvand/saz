'use client';

import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import type { AppError } from '@/lib/errors';
import { AuthProvider, _internalAuth } from '@/lib/auth';

export function Providers({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error, query) => {
            // Handle AppError from our API
            if (error && typeof error === 'object' && 'kind' in error) {
              const appError = error as AppError;

              // On auth errors, clear the stale token and push to /login
              // unless we're already there. This guarantees the user never
              // stays "ghost-logged-in" with cached UI behind a 401.
              if (appError.kind === 'auth') {
                _internalAuth.setAccessToken(null);
                if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
                  router.replace('/login');
                }
              }

              // Log structured error
              console.error('[React Query] Query failed:', {
                kind: appError.kind,
                status: appError.status,
                message: appError.message,
                queryKey: query.queryKey,
              });
            } else {
              console.error('[React Query] Query failed:', {
                error,
                queryKey: query.queryKey,
              });
            }
          },
        }),
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            retry: (failureCount, error) => {
              // Don't retry on auth/permission errors
              if (error && typeof error === 'object' && 'kind' in error) {
                const appError = error as AppError;
                if (appError.kind === 'auth' || appError.kind === 'permission') {
                  return false;
                }
                // Don't retry 404s
                if (appError.kind === 'not_found') {
                  return false;
                }
              }
              return failureCount < 2;
            },
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: false,
            onError: (error) => {
              // Global mutation error handler
              if (error && typeof error === 'object' && 'kind' in error) {
                const appError = error as AppError;

                if (appError.kind === 'auth') {
                  _internalAuth.setAccessToken(null);
                  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
                    router.replace('/login');
                  }
                }

                // Log all mutation errors
                console.error('[React Query] Mutation failed:', {
                  kind: appError.kind,
                  status: appError.status,
                  message: appError.message,
                });
              }
            },
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
