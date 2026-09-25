import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { ApiError, api, getToken, setToken } from './api/client';
import type { User } from './api/types';

interface AuthState {
  user: User | null;
  loading: boolean;
  signIn: (user: User) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    // Токен мог истечь между сеансами — проверяем его до показа интерфейса.
    // Разлогинивает только отказ сервера (401/403). Обрыв сети — не отказ:
    // ТЗ требует переживать сбои связи до 30 секунд, поэтому при сетевой
    // ошибке токен остаётся, а проверка повторяется, пока связь не вернётся.
    let cancelled = false;
    let attempts = 0;
    const check = () => {
      api
        .me()
        .then((me) => {
          if (cancelled) return;
          setUser(me);
          setLoading(false);
        })
        .catch((e) => {
          if (cancelled) return;
          const network = e instanceof ApiError && e.network;
          if (network && attempts < 20) {
            attempts += 1;
            setTimeout(check, 3000);
            return;
          }
          if (!network) setToken(null);
          setLoading(false);
        });
    };
    check();
    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, signIn: setUser, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth вызван вне AuthProvider');
  return context;
}
