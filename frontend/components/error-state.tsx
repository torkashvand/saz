import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ApiError } from '@/lib/api';

interface ErrorStateProps {
  error: Error | ApiError | unknown;
  onRetry?: () => void;
  title?: string;
}

export function ErrorState({
  error,
  onRetry,
  title = 'Something went wrong',
}: ErrorStateProps) {
  const getErrorMessage = () => {
    if (error instanceof ApiError) {
      return error.message;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return 'An unexpected error occurred';
  };

  const getErrorDetails = () => {
    if (error instanceof ApiError && error.details) {
      return error.details.map((d) => d.message).join(', ');
    }
    return null;
  };

  const getRequestId = () => {
    if (error instanceof ApiError && error.requestId) {
      return error.requestId;
    }
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
      {getRequestId() && (
        <p className="text-xs text-red-500 mb-4">Request ID: {getRequestId()}</p>
      )}
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