import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/authStore';
import { authApi } from '@/api/auth';
import type { LoginRequest } from '@/types/auth';

let initialRefreshPromise: Promise<void> | null = null;

export function useAuth() {
  const navigate = useNavigate();
  const { setAuth, clearAuth, isAuthenticated, user, accessToken } = useAuthStore();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isInitialized, setIsInitialized] = useState(false);

  // Try to refresh token on mount (session recovery)
  useEffect(() => {
    const tryRefresh = async () => {
      if (initialRefreshPromise) {
        try {
          await initialRefreshPromise;
        } finally {
          setIsInitialized(true);
        }
        return;
      }

      initialRefreshPromise = (async () => {
        const storedRefreshToken = useAuthStore.getState().refreshToken;
        if (!storedRefreshToken) {
          clearAuth();
          return;
        }
        try {
          const tokenData = await authApi.refresh(storedRefreshToken);
          useAuthStore.getState().setToken(tokenData.access_token);
          const userData = await authApi.getMe();
          setAuth(tokenData.access_token, tokenData.refresh_token, userData);
        } catch {
          clearAuth();
        }
      })();

      try {
        await initialRefreshPromise;
      } finally {
        setIsInitialized(true);
      }
    };

    if (!isAuthenticated) {
      tryRefresh();
    } else {
      setIsInitialized(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(
    async (data: LoginRequest) => {
      setIsLoading(true);
      setError(null);
      try {
        const tokenData = await authApi.login(data);
        // Set token first so the apiClient can use it for getMe
        useAuthStore.getState().setToken(tokenData.access_token);
        const userData = await authApi.getMe();
        setAuth(tokenData.access_token, tokenData.refresh_token, userData);
      } catch (err: unknown) {
        const message =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          'Login failed. Please check your credentials.';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [setAuth]
  );

  const logout = useCallback(async () => {
    try {
      const refreshToken = useAuthStore.getState().refreshToken;
      if (refreshToken) {
        await authApi.logout(refreshToken);
      }
    } catch {
      // Ignore logout errors
    } finally {
      clearAuth();
      navigate('/login');
    }
  }, [clearAuth, navigate]);

  return {
    login,
    logout,
    isLoading,
    error,
    setError,
    isAuthenticated,
    isInitialized,
    user,
    accessToken,
  };
}
