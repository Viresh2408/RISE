'use client';

import React from 'react';
import Link from 'next/link';
import { useAuth } from '../../lib/auth-context';
import { Lock, ShieldAlert } from 'lucide-react';
import { CardSkeleton } from './CardSkeleton';
import { tx } from '../../lib/typography';

interface AdminGateProps {
  children: React.ReactNode;
}

export function AdminGate({ children }: AdminGateProps) {
  const { session, loading, hasRole } = useAuth();

  // Show skeleton during auth check
  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        <CardSkeleton count={3} variant="policy" />
      </div>
    );
  }

  // Check for admin role
  const isAdmin = hasRole('admin');

  if (!session || !isAdmin) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center px-4 py-12">
        <div className="max-w-md w-full rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-8 text-center shadow-2xl">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-[#4C2A85]/20 border border-[#8B5CF6]/30 text-[#8B5CF6] mb-6">
            <Lock className="h-7 w-7" />
          </div>

          <h2 className={tx('sectionHeader', 'text-[#FAF7F2] normal-case text-xl mb-3 font-semibold')}>
            Admin Access Required
          </h2>

          <p className={tx('rcaProse', 'text-[#6B6560] text-sm mb-8')}>
            Your current role does not have permission to view or manage this section. Please contact your system administrator for access.
          </p>

          <Link
            href="/incidents"
            className="inline-flex items-center justify-center rounded-lg border border-[#8B5CF6]/40 bg-[#4C2A85]/30 px-6 py-3 text-sm font-semibold text-[#FAF7F2] hover:bg-[#8B5CF6]/20 transition-all duration-200"
          >
            Return to Incidents Console
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
