import { useEffect } from 'react';
import { toast } from '@/components/ui/use-toast';
import type { AppError } from './errors';

interface UseErrorHandlerOptions {
  error: Error | AppError | unknown | null;
  isError: boolean;
  context?: string; // E.g., "loading flows", "registering flow"
  showToast?: boolean; // Default: true
}

/**
 * Custom hook for consistent error handling across the application.
 *
 * @deprecated Use useErrorToast from '@/lib/use-error-toast' instead
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
      error && typeof error === 'object' && 'kind' in error
        ? (error as AppError).message
        : error instanceof Error
          ? error.message
          : 'An unexpected error occurred';

    console.error(`Error while ${context}:`, {
      error,
      message: errorMessage,
      kind:
        error && typeof error === 'object' && 'kind' in error
          ? (error as AppError).kind
          : undefined,
      validationErrors:
        error && typeof error === 'object' && 'kind' in error
          ? (error as AppError).validationErrors
          : undefined,
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
      error && typeof error === 'object' && 'kind' in error
        ? (error as AppError).message
        : error instanceof Error
          ? error.message
          : 'An unexpected error occurred',
    errorDetails:
      error && typeof error === 'object' && 'kind' in error
        ? (error as AppError).validationErrors
        : undefined,
    requestId: undefined, // AppError doesn't have requestId
  };
}
