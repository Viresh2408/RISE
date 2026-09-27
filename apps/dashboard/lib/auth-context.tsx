'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';
import { supabase } from './supabase';
import { apiClient } from './api-client';

export interface UserSession {
  user_id: string;
  email: string;
  roles: string[];
  tenant_id: string;
  token: string;
}

interface AuthContextType {
  session: UserSession | null;
  loading: boolean;
  login: (email: string, pass: string) => Promise<void>;
  logout: () => Promise<void>;
  hasRole: (minRole: 'viewer' | 'engineer' | 'approver' | 'admin') => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const ROLE_HIERARCHY: Record<string, string[]> = {
  viewer: ['viewer', 'engineer', 'approver', 'admin'],
  engineer: ['engineer', 'approver', 'admin'],
  approver: ['approver', 'admin'],
  admin: ['admin'],
};

const STORAGE_KEY = 'rise_session';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSessionState] = useState<UserSession | null>(null);
  const [loading, setLoading] = useState(true);

  const saveSession = (sess: UserSession | null) => {
    setSessionState(sess);
    if (typeof window !== 'undefined') {
      if (sess) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(sess));
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
  };

  const fetchBackendSession = async (jwtToken: string, userEmail: string) => {
    try {
      const backendSession = await apiClient.getSession(jwtToken);
      const newSession: UserSession = {
        user_id: backendSession.user_id,
        email: userEmail,
        roles: backendSession.roles || ['viewer'],
        tenant_id: backendSession.tenant_id,
        token: jwtToken,
      };
      saveSession(newSession);
    } catch (err) {
      // SECURITY: never fabricate an elevated session when the backend session
      // exchange fails. The previous fallback invented roles
      // (['approver','engineer','viewer']), a user_id ('user-001') and a tenant,
      // showing privileged controls (approve/reject) to a user whose session
      // could not actually be established. Fail closed instead: clear any session
      // and propagate the error so the UI renders a "cannot reach backend" state
      // and the user re-authenticates against a healthy backend. Real
      // authorization is enforced server-side per request, but the client must
      // not display privileges it cannot substantiate.
      console.error('Backend session exchange failed; failing closed (no session):', err);
      saveSession(null);
      throw err;
    }
  };

  useEffect(() => {
    // 1. Immediately hydrate active session from localStorage on page reload
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        try {
          const parsed = JSON.parse(stored);
          if (parsed && parsed.token) {
            setSessionState(parsed);
            setLoading(false);
          }
        } catch {
          localStorage.removeItem(STORAGE_KEY);
        }
      } else {
        // No stored session — remain unauthenticated until a real login occurs.
        setLoading(false);
      }
    }

    // 2. Check Supabase auth session asynchronously to stay in sync
    supabase.auth.getSession().then(({ data: { session: supaSession } }) => {
      if (supaSession?.access_token) {
        fetchBackendSession(supaSession.access_token, supaSession.user?.email || 'user@rise.internal')
          .catch(() => {
            // fetchBackendSession already failed closed (session cleared); swallow
            // here so the effect has no unhandled rejection.
          })
          .finally(() => setLoading(false));
      } else {
        setLoading(false);
      }
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, supaSession) => {
      if (supaSession?.access_token) {
        fetchBackendSession(supaSession.access_token, supaSession.user?.email || 'user@rise.internal').catch(() => {
          // fetchBackendSession already failed closed (session cleared).
        });
      }
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  const login = async (email: string, pass: string) => {
    setLoading(true);
    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password: pass,
      });
      if (error) {
        throw error;
      }
      if (data.session?.access_token) {
        await fetchBackendSession(data.session.access_token, email);
      }
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    setLoading(true);
    try {
      await supabase.auth.signOut();
    } catch {
      // ignore
    }
    saveSession(null);
    setLoading(false);
  };

  const hasRole = (minRole: 'viewer' | 'engineer' | 'approver' | 'admin') => {
    if (!session) return false;
    const allowedRoles = ROLE_HIERARCHY[minRole] || [];
    return session.roles.some((r) => allowedRoles.includes(r));
  };

  return (
    <AuthContext.Provider value={{ session, loading, login, logout, hasRole }}>
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
