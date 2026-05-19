import { useToast } from '@/components/ui/use-toast';
import type { AppError } from './errors';
import { useCallback } from 'react';

export function useErrorToast() {
  const { toast } = useToast();

  const showError = useCallback(
    (error: AppError | Error | string) => {
      let appError: AppError;

      if (typeof error === 'string') {
        appError = { kind: 'unknown', message: error };
      } else if ('kind' in error) {
        appError = error;
      } else {
        appError = { kind: 'unknown', message: error.message };
      }

      const variant =
        ({
          validation: 'destructive',
          auth: 'default',
          permission: 'destructive',
          not_found: 'destructive',
          conflict: 'destructive',
          rate_limit: 'destructive',
          network: 'destructive',
          server: 'destructive',
          unknown: 'destructive',
        }[appError.kind] as 'default' | 'destructive' | undefined) || 'destructive';

      toast({
        variant,
        title: getErrorTitle(appError.kind),
        description: appError.message,
      });
    },
    [toast],
  );

  const showSuccess = useCallback(
    (message: string) => {
      toast({
        title: 'Success',
        description: message,
      });
    },
    [toast],
  );

  return { showError, showSuccess };
}

function getErrorTitle(kind: AppError['kind']): string {
  return {
    validation: 'Validation Error',
    auth: 'Authentication Required',
    permission: 'Permission Denied',
    not_found: 'Not Found',
    conflict: 'Conflict',
    rate_limit: 'Rate Limited',
    server: 'Server Error',
    network: 'Connection Error',
    unknown: 'Error',
  }[kind];
}
