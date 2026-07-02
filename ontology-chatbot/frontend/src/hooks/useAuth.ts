import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/authStore';
import { authApi } from '@/api/auth';
import type { LoginRequest, SignupRequest } from '@/types/auth';

export function useAuth() {
  const navigate = useNavigate();
  const { setAuth, clearAuth, isAuthenticated, user, accessToken } = useAuthStore();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isInitialized, setIsInitialized] = useState(false);

  // Try to refresh token on mount (session recovery)
  useEffect(() => {
    const tryRefresh = async () => {
      try {
        const data = await authApi.refresh();
        setAuth(data.access_token, data.user);
      } catch {
        // No valid refresh token — stay logged out
        clearAuth();
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
        const response = await authApi.login(data);
        setAuth(response.access_token, response.user);
        navigate('/');
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
    [setAuth, navigate]
  );

  const signup = useCallback(
    async (data: SignupRequest) => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await authApi.signup(data);
        setAuth(response.access_token, response.user);
        navigate('/');
      } catch (err: unknown) {
        const message =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          'Signup failed. Please try again.';
        setError(message);
        throw err;
      } finally {
        setIsLoading(false);
      }
    },
    [setAuth, navigate]
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Ignore logout errors
    } finally {
      clearAuth();
      navigate('/login');
    }
  }, [clearAuth, navigate]);

  return {
    login,
    signup,
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
