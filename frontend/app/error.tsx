'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { AlertTriangle } from 'lucide-react';
import { fromUnknownError } from '@/lib/errors';
import { captureException } from '@/lib/monitoring';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const appError = fromUnknownError(error);

  useEffect(() => {
    // Capture to Sentry with error boundary context
    captureException(error, {
      errorBoundary: 'root',
      digest: error.digest,
    });
  }, [error]);

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <div className="max-w-md w-full bg-white rounded-lg shadow-lg p-8">
        <div className="flex flex-col items-center text-center">
          <div className="rounded-full bg-red-100 p-3 mb-4">
            <AlertTriangle className="h-8 w-8 text-red-600" />
          </div>

          <h1 className="text-2xl font-bold text-gray-900 mb-2">Something went wrong</h1>

          <p className="text-gray-600 mb-6">{appError.message}</p>

          {error.digest && <p className="text-xs text-gray-500 mb-4">Error ID: {error.digest}</p>}

          <div className="flex gap-3 w-full">
            <Button onClick={reset} className="flex-1">
              Try Again
            </Button>
            <Button
              variant="outline"
              onClick={() => (window.location.href = '/')}
              className="flex-1"
            >
              Go Home
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
