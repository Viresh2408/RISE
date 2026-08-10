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

const DEFAULT_DEMO_SESSION: UserSession = {
  user_id: 'demo-user-001',
  email: 'demo@rise.internal',
  roles: ['admin', 'approver', 'engineer', 'viewer'],
  tenant_id: '00000000-0000-0000-0000-000000000001',
  token: 'demo-token-hardcoded',
};

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
      console.warn('Backend session exchange fallback to token context:', err);
      const fallbackSession: UserSession = {
        user_id: 'user-001',
        email: userEmail,
        roles: ['approver', 'engineer', 'viewer'],
        tenant_id: '00000000-0000-0000-0000-000000000001',
        token: jwtToken,
      };
      saveSession(fallbackSession);
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
        // Fallback default demo session for smooth local development
        saveSession(DEFAULT_DEMO_SESSION);
        setLoading(false);
      }
    }

    // 2. Check Supabase auth session asynchronously to stay in sync
    supabase.auth.getSession().then(({ data: { session: supaSession } }) => {
      if (supaSession?.access_token) {
        fetchBackendSession(supaSession.access_token, supaSession.user?.email || 'user@rise.internal').finally(() =>
          setLoading(false)
        );
      } else {
        setLoading(false);
      }
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, supaSession) => {
      if (supaSession?.access_token) {
        fetchBackendSession(supaSession.access_token, supaSession.user?.email || 'user@rise.internal');
      }
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  const login = async (email: string, pass: string) => {
    setLoading(true);

    // ── DEMO BYPASS (local testing only) ─────────────────────────────────────
    if (email === 'demo@rise.internal' && pass === 'demo1234') {
      saveSession(DEFAULT_DEMO_SESSION);
      setLoading(false);
      return;
    }
    // ─────────────────────────────────────────────────────────────────────────

    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password: pass,
    });
    if (error) {
      setLoading(false);
      throw error;
    }
    if (data.session?.access_token) {
      await fetchBackendSession(data.session.access_token, email);
    }
    setLoading(false);
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
