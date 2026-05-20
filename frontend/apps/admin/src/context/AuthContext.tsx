import React, { useEffect, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { AUTH_UNAUTHORIZED_EVENT } from '../lib/http/auth';
import { authKeys } from '../query/keys/auth';
import { useMeQuery } from '../query/hooks/auth';
import { useAuthStore } from '../stores/auth-store';
import { AuthContext } from './auth-context';

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const token = useAuthStore((s) => s.token);
    const showAuthModal = useAuthStore((s) => s.showAuthModal);
    const authTab = useAuthStore((s) => s.authTab);
    const setToken = useAuthStore((s) => s.setToken);
    const setShowAuthModal = useAuthStore((s) => s.setShowAuthModal);
    const setAuthTab = useAuthStore((s) => s.setAuthTab);
    const clearAuth = useAuthStore((s) => s.clearAuth);

    const { data: user, isLoading, refetch } = useMeQuery();
    const queryClient = useQueryClient();

    useEffect(() => {
        const handleUnauthorized = () => {
            clearAuth();
            queryClient.removeQueries({ queryKey: authKeys.all() });
        };

        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
        return () => {
            window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
        };
    }, [clearAuth, queryClient]);

    const login = async (newToken: string) => {
        setToken(newToken);
        const result = await refetch();
        if (result.error) {
            clearAuth();
            throw result.error;
        }
        setShowAuthModal(false);
    };

    const logout = () => {
        clearAuth();
        queryClient.clear();
    };

    const refreshUser = async () => {
        await refetch();
    };

    return (
        <AuthContext.Provider value={{
            user: user ?? null,
            token,
            login,
            logout,
            isLoading: isLoading && !!token,
            isAuthenticated: !!user,
            showAuthModal,
            setShowAuthModal,
            refreshUser,
            authTab,
            setAuthTab,
        }}>
            {children}
        </AuthContext.Provider>
    );
};
