'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../../lib/auth-context';
import { Shield, Lock, Mail, AlertCircle, ArrowRight, Sparkles } from 'lucide-react';

export default function LoginPage() {
  const { session, login, loading } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState('engineer@rise.internal');
  const [password, setPassword] = useState('Password123!');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (session) {
      router.push('/incidents');
    }
  }, [session, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setSubmitting(true);

    try {
      await login(email.trim(), password);
      router.push('/incidents');
    } catch (err: any) {
      setErrorMsg(err.message || 'Invalid email or password');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col justify-center py-12 sm:px-6 lg:px-8 bg-[#0E0B14] text-[#FAF7F2] font-hanken">
      <div className="sm:mx-auto sm:w-full sm:max-w-md text-center space-y-3">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-purple-950/80 border border-purple-500/40 text-amber-400 glow-purple">
          <Shield className="h-6 w-6" />
        </div>
        <h2 className="font-fraunces text-3xl font-bold tracking-tight text-white">
          RISE Antigravity Auth
        </h2>
        <p className="text-xs font-mono text-purple-300">
          Autonomous Incident Remediation & Human Approval Console
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <div className="glass-panel p-8 rounded-xl border border-white/10 shadow-2xl">
          {errorMsg && (
            <div className="mb-6 flex items-center space-x-2.5 rounded-lg border border-red-500/40 bg-red-950/40 p-3.5 text-xs text-red-300 font-mono">
              <AlertCircle className="h-4 w-4 flex-shrink-0 text-red-400" />
              <span>{errorMsg}</span>
            </div>
          )}

          <form className="space-y-5 font-mono text-xs" onSubmit={handleSubmit}>
            <div>
              <label className="block text-gray-300 mb-1.5 font-semibold">
                Work Email Address
              </label>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-gray-500">
                  <Mail className="h-4 w-4 text-purple-400" />
                </div>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="engineer@rise.internal"
                  className="w-full rounded-lg border border-white/10 bg-black/60 pl-10 pr-3 py-2.5 text-xs text-white placeholder-gray-600 focus:border-amber-400 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-gray-300 mb-1.5 font-semibold">
                Supabase Auth Password
              </label>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-gray-500">
                  <Lock className="h-4 w-4 text-purple-400" />
                </div>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full rounded-lg border border-white/10 bg-black/60 pl-10 pr-3 py-2.5 text-xs text-white placeholder-gray-600 focus:border-amber-400 focus:outline-none"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting || loading}
              className="w-full flex items-center justify-center space-x-2 rounded-lg bg-amber-500 hover:bg-amber-400 py-3 text-xs font-bold text-black disabled:opacity-50 transition-all glow-amber font-mono"
            >
              {submitting ? (
                <span>Authenticating...</span>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  <span>Sign In to Console</span>
                </>
              )}
            </button>
          </form>

          <div className="mt-6 border-t border-white/10 pt-4 text-center">
            <p className="text-[11px] font-mono text-gray-400">
              Guarded by Supabase JWT & OPA RBAC Policy Matrix
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
