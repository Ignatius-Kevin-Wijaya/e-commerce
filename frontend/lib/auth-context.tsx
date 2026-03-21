'use client';

/**
 * Auth Context — provides authentication state and actions to the entire app.
 *
 * Stores JWT tokens in localStorage and auto-fetches the current user on mount.
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { authApi, User, ApiError } from './api';

interface AuthContextType {
    user: User | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    login: (email: string, password: string) => Promise<void>;
    register: (data: { email: string; username: string; password: string; full_name?: string }) => Promise<void>;
    logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    const fetchUser = useCallback(async () => {
        try {
            const token = localStorage.getItem('access_token');
            if (!token) {
                setIsLoading(false);
                return;
            }
            const userData = await authApi.me();
            setUser(userData);
        } catch {
            // Token expired or invalid — clear tokens
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            setUser(null);
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchUser();
    }, [fetchUser]);

    const login = async (email: string, password: string) => {
        const tokens = await authApi.login({ email, password });
        localStorage.setItem('access_token', tokens.access_token);
        localStorage.setItem('refresh_token', tokens.refresh_token);
        const userData = await authApi.me();
        setUser(userData);
    };

    const register = async (data: { email: string; username: string; password: string; full_name?: string }) => {
        await authApi.register(data);
        // Auto-login after registration
        await login(data.email, data.password);
    };

    const logout = async () => {
        try {
            const refreshToken = localStorage.getItem('refresh_token');
            if (refreshToken) {
                await authApi.logout(refreshToken);
            }
        } catch {
            // Ignore errors on logout
        } finally {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            setUser(null);
        }
    };

    return (
        <AuthContext.Provider
            value={{
                user,
                isAuthenticated: !!user,
                isLoading,
                login,
                register,
                logout,
            }}
        >
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
}
