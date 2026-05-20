import { QueryClient } from '@tanstack/react-query';
import { AppHttpError } from '../lib/http/errors';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 2,
      gcTime: 1000 * 60 * 5,
      retry: (failureCount, error) => {
        if (error instanceof AppHttpError && ['unauthorized', 'forbidden', 'validation'].includes(error.code)) {
          return false;
        }
        return failureCount < 2;
      },
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: false,
    },
  },
});
