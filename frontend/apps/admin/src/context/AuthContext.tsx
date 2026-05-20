import React, { useEffect, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { getUserProfileAPI } from '../api/auth';
import {
    AUTH_UNAUTHORIZED_EVENT,
    clearAccessToken,
    getAccessToken,
    setAccessToken,
} from '../lib/http/auth';
import { authKeys } from '../query/keys/auth';
import type { User } from '../types/user';
import { AuthContext } from './auth-context';

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [token, setToken] = useState<string | null>(getAccessToken());
    const [isLoading, setIsLoading] = useState<boolean>(true);
    const [showAuthModal, setShowAuthModal] = useState(false);
    const [authTab, setAuthTab] = useState<'login' | 'register'>('login');

    const queryClient = useQueryClient();

    const refreshUser = async () => {
        if (token) {
            try {
                const userData = await getUserProfileAPI();
                setUser(userData);
                queryClient.setQueryData(authKeys.me(), userData);
            } catch (error) {
                console.error('Failed to refresh user profile', error);
            }
        }
    };

    useEffect(() => {
        const initAuth = async () => {
            if (token) {
                try {
                    const userData = await queryClient.fetchQuery({
                        queryKey: authKeys.me(),
                        queryFn: getUserProfileAPI,
                    });
                    setUser(userData);
                } catch {
                    // Token 过期或无效，清除但不跳转（匿名也可用）
                    clearAccessToken();
                    setToken(null);
                    setUser(null);
                }
            }
            setIsLoading(false);
        };
        initAuth();
    }, [token, queryClient]);

    useEffect(() => {
        const handleUnauthorized = () => {
            setToken(null);
            setUser(null);
            queryClient.clear();
        };

        window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
        return () => {
            window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
        };
    }, [queryClient]);

    const login = async (newToken: string) => {
        setAccessToken(newToken);
        setToken(newToken);
        try {
            setIsLoading(true);
            const userData = await queryClient.fetchQuery({
                queryKey: authKeys.me(),
                queryFn: getUserProfileAPI,
            });
            setUser(userData);
            setShowAuthModal(false); // 登录成功自动关闭弹窗
        } catch (error) {
            console.error('Failed to get user profile', error);
            logout();
            throw error;
        } finally {
            setIsLoading(false);
        }
    };

    const logout = () => {
        clearAccessToken();
        setToken(null);
        setUser(null);
        queryClient.clear();
    };

    return (
        <AuthContext.Provider value={{
            user,
            token,
            login,
            logout,
            isLoading,
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
