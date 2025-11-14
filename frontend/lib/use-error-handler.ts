import { useEffect } from 'react';
import { toast } from '@/components/ui/use-toast';
import { ApiError } from './api';

interface UseErrorHandlerOptions {
  error: Error | ApiError | unknown | null;
  isError: boolean;
  context?: string; // E.g., "loading flows", "registering flow"
  showToast?: boolean; // Default: true
}

/**
 * Custom hook for consistent error handling across the application.
 *
 * @example
 * const { data, isLoading, error, isError } = useQuery({...});
 * const { errorMessage, errorDetails, requestId } = useErrorHandler({
 *   error,
 *   isError,
 *   context: 'loading flows',
 *   showToast: false, // We show error in UI instead
 * });
 */
export function useErrorHandler({
  error,
  isError,
  context = 'performing this action',
  showToast = true,
}: UseErrorHandlerOptions) {
  useEffect(() => {
    if (!isError || !error) return;

    const errorMessage =
      error instanceof ApiError
        ? error.message
        : error instanceof Error
        ? error.message
        : 'An unexpected error occurred';

    console.error(`Error while ${context}:`, {
      error,
      message: errorMessage,
      requestId: error instanceof ApiError ? error.requestId : undefined,
      details: error instanceof ApiError ? error.details : undefined,
    });

    if (showToast) {
      toast({
        title: `Failed: ${context}`,
        description: errorMessage,
        variant: 'destructive',
      });
    }
  }, [isError, error, context, showToast]);

  return {
    errorMessage:
      error instanceof ApiError || error instanceof Error
        ? error.message
        : 'An unexpected error occurred',
    errorDetails: error instanceof ApiError ? error.details : undefined,
    requestId: error instanceof ApiError ? error.requestId : undefined,
  };
}