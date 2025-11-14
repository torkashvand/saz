'use client';

import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { useGlobalEvents } from '@/lib/use-events';
import { toast } from '@/components/ui/use-toast';
import { ApiError } from '@/lib/api';

function EventsProvider() {
  useGlobalEvents();
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error, query) => {
            console.error('[React Query] Query failed:', {
              error,
              queryKey: query.queryKey,
            });

            // Show toast notification for query errors
            const errorMessage =
              error instanceof ApiError
                ? error.message
                : error instanceof Error
                ? error.message
                : 'An unexpected error occurred';

            toast({
              title: 'Request Failed',
              description: errorMessage,
              variant: 'destructive',
            });
          },
        }),
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            retry: false, // Disable auto-retry to show errors immediately
            refetchOnWindowFocus: false, // Prevent unwanted refetches
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <EventsProvider />
      {children}
    </QueryClientProvider>
  );
}
