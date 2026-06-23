/**
 * Minimal client-side auth state: token storage + a React Context that
 * exposes the current user and login/logout actions.
 *
 * Notes:
 * - The token lives in localStorage so it survives page reloads.
 *   localStorage is vulnerable to XSS, so the backend never returns
 *   sensitive data (password hashes, raw secrets) and the JWT scope is
 *   intentionally tied to a single user with no elevated privileges.
 * - When RBAC, SSO, or session-server-state arrives, swap this for an
 *   HttpOnly cookie + a /me-based session check; the React surface
 *   (useAuth) is what every component depends on, not the storage choice.
 */

'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from './api';
import type { CurrentUser, UserRole } from './types';

const STORAGE_KEY = 'saz.access_token';

let _token: string | null = null;

export function getAccessToken(): string | null {
  // Read straight from localStorage so non-React callers (the API fetch
  // wrapper, the WebSocket helper) always see the latest value without
  // having to subscribe to React state.
  if (typeof window === 'undefined') return _token;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return _token;
  }
}

function setAccessToken(token: string | null) {
  _token = token;
  if (typeof window === 'undefined') return;
  try {
    if (token) {
      window.localStorage.setItem(STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // localStorage can be unavailable in private-mode contexts; the in-
    // memory copy at least keeps the current tab usable until reload.
  }
}

interface AuthContextValue {
  user: CurrentUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  role: UserRole | null;
  // Whether the current tier may perform write actions (admin/operator).
  // UI convenience only — the backend enforces the same rule on every
  // mutating endpoint, so a viewer who bypasses the UI still gets a 403.
  canWrite: boolean;
  mustChangePassword: boolean;
  login: (identifier: string, password: string) => Promise<void>;
  // Establish the session after an OIDC redirect: exchange the refresh
  // cookie set by the callback for an access token + user.
  completeSso: () => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  // Start in loading state until we've done one /me probe — pages that
  // gate rendering on `isAuthenticated` should not flash the login page
  // on first paint when the user actually has a valid token.
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    try {
      const me = await api.getCurrentUser();
      setUser(me);
    } catch {
      // Token is no longer valid (expired/revoked/user disabled).
      setAccessToken(null);
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (identifier: string, password: string) => {
    const resp = await api.login({ identifier, password });
    setAccessToken(resp.access_token);
    setUser(resp.user);
  }, []);

  const completeSso = useCallback(async () => {
    const resp = await api.refreshSession();
    setAccessToken(resp.access_token);
    setUser(resp.user);
  }, []);

  const logout = useCallback(async () => {
    // Revoke the server-side session so the refresh cookie can't mint new
    // tokens. Best-effort: clear local state even if the call fails.
    try {
      await api.logout();
    } catch {
      // ignore — local sign-out proceeds regardless
    }
    setAccessToken(null);
    setUser(null);
  }, []);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    const updated = await api.changePassword({
      current_password: currentPassword,
      new_password: newPassword,
    });
    setUser(updated);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: user !== null,
      isAdmin: user?.role === 'admin',
      role: user?.role ?? null,
      canWrite: user !== null && user.role !== 'viewer',
      mustChangePassword: user?.must_change_password ?? false,
      login,
      completeSso,
      logout,
      refresh,
      changePassword,
    }),
    [user, isLoading, login, completeSso, logout, refresh, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside an <AuthProvider>');
  return ctx;
}

// Exposed for tests + the API client. Direct callers should prefer useAuth().
export const _internalAuth = {
  getAccessToken,
  setAccessToken,
  STORAGE_KEY,
};
