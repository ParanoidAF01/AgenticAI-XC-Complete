import { create } from 'zustand';
import type { User } from '@/types/auth';

interface AuthState {
  accessToken: string | null;
  user: User | null;
  isAuthenticated: boolean;
  setAuth: (token: string, user: User) => void;
  setUser: (user: User) => void;
  setToken: (token: string) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,

  setAuth: (token: string, user: User) =>
    set({
      accessToken: token,
      user,
      isAuthenticated: true,
    }),

  setUser: (user: User) =>
    set({ user }),

  setToken: (token: string) =>
    set({ accessToken: token, isAuthenticated: true }),

  clearAuth: () =>
    set({
      accessToken: null,
      user: null,
      isAuthenticated: false,
    }),
}));
