import { create } from 'zustand';
import type { User } from '../types/api';

interface AuthState {
  user: User | null;
  /**
   * False until the initial /auth/me probe has resolved (either with a user
   * or with a 401). ProtectedRoute must wait for this to be true so that a
   * logged-in user is not bounced to /login on a hard reload.
   */
  authLoaded: boolean;
  setUser: (user: User | null) => void;
  setAuthLoaded: (loaded: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  authLoaded: false,
  setUser: (user) => set({ user }),
  setAuthLoaded: (loaded) => set({ authLoaded: loaded }),
}));
