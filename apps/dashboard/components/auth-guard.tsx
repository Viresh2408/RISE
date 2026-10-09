'use client';

import React, { useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { useAuth } from '../lib/auth-context';

const PUBLIC_PATHS = ['/', '/login', '/design-system'];

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  // '/design-system' is a static, data-free primitive/token showcase used for
  // visual verification — it makes no API calls and reads no session data, so
  // it is public like the marketing page. All data routes stay auth-gated.
  useEffect(() => {
    if (!loading && !session && !PUBLIC_PATHS.includes(pathname)) {
      router.push('/login');
    }
  }, [session, loading, pathname, router]);

  if (loading && !PUBLIC_PATHS.includes(pathname)) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0a0d14]">
        <div className="flex flex-col items-center space-y-4">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent"></div>
          <p className="text-sm font-medium text-gray-400">Authenticating RISE Session...</p>
        </div>
      </div>
    );
  }

  if (!session && !PUBLIC_PATHS.includes(pathname)) {
    return null;
  }

  return <>{children}</>;
}
