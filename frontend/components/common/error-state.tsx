import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import type { AppError } from '@/lib/errors';

interface ErrorStateProps {
  error: Error | AppError | unknown;
  onRetry?: () => void;
  title?: string;
}

/**
 * @deprecated Use ErrorBanner from '@/components/ui/error-banner' instead
 */
export function ErrorState({ error, onRetry, title = 'Something went wrong' }: ErrorStateProps) {
  const getErrorMessage = () => {
    if (error && typeof error === 'object' && 'kind' in error) {
      return (error as AppError).message;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return 'An unexpected error occurred';
  };

  const getErrorDetails = () => {
    if (error && typeof error === 'object' && 'kind' in error) {
      const appError = error as AppError;
      if (appError.validationErrors) {
        return appError.validationErrors.map((d: any) => d.message).join(', ');
      }
    }
    return null;
  };

  const getRequestId = () => {
    // AppError doesn't have requestId, but we keep this for backwards compatibility
    return null;
  };

  return (
    <Card className="p-12 text-center border-red-200 bg-red-50">
      <div className="text-red-600 text-xl mb-3">⚠️</div>
      <h3 className="text-lg font-semibold text-red-900 mb-2">{title}</h3>
      <p className="text-red-700 mb-2">{getErrorMessage()}</p>
      {getErrorDetails() && (
        <p className="text-xs text-red-600 mb-2 font-mono">{getErrorDetails()}</p>
      )}
      {getRequestId() && <p className="text-xs text-red-500 mb-4">Request ID: {getRequestId()}</p>}
      {onRetry && (
        <Button
          variant="outline"
          onClick={onRetry}
          className="border-red-300 text-red-700 hover:bg-red-100"
        >
          Retry
        </Button>
      )}
    </Card>
  );
}
