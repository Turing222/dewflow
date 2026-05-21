import { useAuthStore } from '../../stores/auth-store';
import { queryClient } from '../../query/query-client';

export const AUTH_UNAUTHORIZED_EVENT = 'app:http:unauthorized';

export const getAccessToken = (): string | null => {
    return useAuthStore.getState().token;
};

export const setAccessToken = (token: string): void => {
    useAuthStore.getState().setToken(token);
};

export const clearAccessToken = (): void => {
    useAuthStore.getState().clearAuth();
};

export const notifyUnauthorized = (): void => {
    if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
    }
};

export const handleUnauthorized = (): void => {
    clearAccessToken();
    notifyUnauthorized();
    queryClient.removeQueries({ queryKey: ['auth'] });
};
