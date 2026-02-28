import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const useAuthStore = create(
  persist(
    (set, get) => ({
      isAuthenticated: false,
      username: null,
      token: null,
      expiresAt: null,

      login: (username, token, expiresAt) => {
        set({
          isAuthenticated: true,
          username,
          token,
          expiresAt,
        });
      },

      logout: () => {
        set({
          isAuthenticated: false,
          username: null,
          token: null,
          expiresAt: null,
        });
      },

      isSessionValid: () => {
        const { isAuthenticated, expiresAt } = get();

        if (!isAuthenticated || !expiresAt) {
          return false;
        }

        const now = Date.now();
        const isValid = now < expiresAt;

        if (!isValid) {
          // Auto-logout on expired session
          set({
            isAuthenticated: false,
            username: null,
            token: null,
            expiresAt: null,
          });
        }

        return isValid;
      },
    }),
    {
      name: 'llm-ttcc-team-pro-auth',
      partialize: (state) => ({
        isAuthenticated: state.isAuthenticated,
        username: state.username,
        token: state.token,
        expiresAt: state.expiresAt,
      }),
    }
  )
);
