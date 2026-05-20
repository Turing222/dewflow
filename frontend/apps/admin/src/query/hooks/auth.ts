import { useQuery } from '@tanstack/react-query';
import { getUserProfileAPI } from '../../api/auth';
import { authKeys } from '../keys/auth';
import { getAccessToken } from '../../lib/http/auth';

export function useAuthMeQuery() {
  const token = getAccessToken();
  return useQuery({
    queryKey: authKeys.me(),
    queryFn: getUserProfileAPI,
    enabled: !!token,
    staleTime: 1000 * 60 * 5,
  });
}
