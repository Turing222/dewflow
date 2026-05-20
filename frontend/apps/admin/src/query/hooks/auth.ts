import { useQuery } from '@tanstack/react-query';
import { getUserProfileAPI } from '../../api/auth';
import { authKeys } from '../keys/auth';
import { useAuthStore } from '../../stores/auth-store';

export function useMeQuery() {
  const token = useAuthStore((s) => s.token);
  return useQuery({
    queryKey: authKeys.me(),
    queryFn: getUserProfileAPI,
    enabled: !!token,
    staleTime: 1000 * 60 * 5,
  });
}
