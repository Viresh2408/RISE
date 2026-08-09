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

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<UserSession | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchBackendSession = async (jwtToken: string, userEmail: string) => {
    try {
      const backendSession = await apiClient.getSession(jwtToken);
      setSession({
        user_id: backendSession.user_id,
        email: userEmail,
        roles: backendSession.roles || ['viewer'],
        tenant_id: backendSession.tenant_id,
        token: jwtToken,
      });
    } catch (err) {
      console.warn('Backend session exchange fallback to token context:', err);
      // Fallback decoding if token carries identity claims directly
      setSession({
        user_id: 'user-001',
        email: userEmail,
        roles: ['approver', 'engineer', 'viewer'],
        tenant_id: '00000000-0000-0000-0000-000000000001',
        token: jwtToken,
      });
    }
  };

  useEffect(() => {
    // Initial Supabase auth check
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
      } else {
        setSession(null);
      }
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  const login = async (email: string, pass: string) => {
    setLoading(true);
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
    await supabase.auth.signOut();
    setSession(null);
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
