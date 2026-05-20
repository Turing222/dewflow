import { useQuery } from '@tanstack/react-query';
import { getSessionsAPI, getSessionDetailAPI } from '../../api/chat';
import { chatKeys } from '../keys/chat';
import { useAuth } from '../../context/useAuth';

export function useChatSessionsQuery(skip = 0, limit = 50) {
  const { isAuthenticated } = useAuth();
  return useQuery({
    queryKey: chatKeys.sessions(),
    queryFn: () => getSessionsAPI(skip, limit),
    enabled: isAuthenticated,
  });
}

export function useSessionDetailQuery(
  sessionId: string | null,
  skip = 0,
  limit = 100,
) {
  const { isAuthenticated } = useAuth();
  return useQuery({
    queryKey: chatKeys.sessionDetail(sessionId!),
    queryFn: () => getSessionDetailAPI(sessionId!, skip, limit),
    enabled: isAuthenticated && !!sessionId,
  });
}
