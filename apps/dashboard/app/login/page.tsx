'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../../lib/auth-context';
import { Shield, Lock, Mail, AlertCircle, ArrowRight } from 'lucide-react';
import { tx } from '../../lib/typography';

export default function LoginPage() {
  const { session, login, loading } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState('demo@rise.internal');
  const [password, setPassword] = useState('demo1234');
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
    <div className="flex min-h-screen flex-col justify-center py-12 px-4 sm:px-6 lg:px-8 bg-[#FAF7F2] text-[#0E0B14]">
      <div className="sm:mx-auto sm:w-full sm:max-w-md text-center space-y-3">
        <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-[#4C2A85] text-[#FAF7F2] shadow-md">
          <Shield className="h-6 w-6" />
        </div>
        <h1 className={tx('loginTitle', 'text-[#0E0B14]')}>
          Sign in to RISE
        </h1>
        <p className={tx('cardMeta', 'text-[#6B6560]')}>
          Autonomous Incident Remediation & Operations Control Plane
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <div className="rounded-xl border border-[#E8E2D9] bg-white p-6 sm:p-8 shadow-xl space-y-6">
          {/* Demo credentials banner */}
          <div className="rounded-lg border border-[#F5A623]/40 bg-[#F5A623]/10 p-3.5 space-y-1">
            <p className={tx('formLabel', 'text-[#4C2A85]')}>
              Demo Credentials (Local Dev)
            </p>
            <div className="space-y-0.5 font-mono text-xs text-[#0E0B14]">
              <div>
                <span className="text-[#6B6560]">Email: </span>
                <code className="font-semibold text-[#4C2A85]">demo@rise.internal</code>
              </div>
              <div>
                <span className="text-[#6B6560]">Pass : </span>
                <code className="font-semibold text-[#4C2A85]">demo1234</code>
              </div>
            </div>
          </div>

          {errorMsg && (
            <div className="flex items-center space-x-2.5 rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 p-3.5 text-[#EF4444]">
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              <span className={tx('errorText')}>{errorMsg}</span>
            </div>
          )}

          <form className="space-y-5" onSubmit={handleSubmit}>
            <div className="space-y-1.5">
              <label className={tx('formLabel', 'block text-[#6B6560]')}>
                Email Address
              </label>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-[#6B6560]">
                  <Mail className="h-4 w-4" />
                </div>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="engineer@rise.internal"
                  className={tx(
                    'inputText',
                    'w-full rounded-lg border border-[#E8E2D9] bg-[#FAF7F2] pl-10 pr-3.5 py-2.5 text-[#0E0B14] placeholder-[#6B6560]/60 focus:border-[#8B5CF6] focus:outline-none focus:ring-2 focus:ring-[#8B5CF6]/20 transition-all duration-150'
                  )}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className={tx('formLabel', 'block text-[#6B6560]')}>
                Password
              </label>
              <div className="relative">
                <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-[#6B6560]">
                  <Lock className="h-4 w-4" />
                </div>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className={tx(
                    'inputText',
                    'w-full rounded-lg border border-[#E8E2D9] bg-[#FAF7F2] pl-10 pr-3.5 py-2.5 text-[#0E0B14] placeholder-[#6B6560]/60 focus:border-[#8B5CF6] focus:outline-none focus:ring-2 focus:ring-[#8B5CF6]/20 transition-all duration-150'
                  )}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting || loading}
              className={tx(
                'ctaButton',
                'w-full flex items-center justify-center space-x-2 rounded-lg bg-[#4C2A85] hover:bg-[#8B5CF6] py-3 text-[#FAF7F2] disabled:opacity-50 transition-colors duration-200 shadow-md'
              )}
            >
              {submitting ? (
                <span>Signing in...</span>
              ) : (
                <>
                  <span>Sign In</span>
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </form>

          <div className="border-t border-[#E8E2D9] pt-4 text-center">
            <p className={tx('cardMeta', 'text-[#6B6560]')}>
              Guarded by Supabase JWT & OPA RBAC Policy Matrix
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
