'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '../lib/auth-context';
import { Shield, LogOut, Activity, User, Server, Sparkles, LayoutDashboard, Terminal, ExternalLink } from 'lucide-react';

export function Navbar({ realtimeConnected = true }: { realtimeConnected?: boolean }) {
  const { session, logout } = useAuth();
  const pathname = usePathname();

  const primaryRole = session?.roles?.[0] || 'viewer';

  return (
    <header className="sticky top-0 z-50 glass-nav border-b border-white/10">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        
        {/* Brand Logo & Tagline */}
        <div className="flex items-center space-x-8">
          <Link href="/" className="flex items-center space-x-3 group">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-purple-900/60 border border-purple-500/40 text-amber-400 group-hover:border-amber-400 group-hover:shadow-[0_0_15px_rgba(245,166,35,0.3)] transition-all">
              <Shield className="h-5 w-5" />
            </div>
            <div>
              <span className="font-fraunces text-xl font-bold tracking-tight text-white group-hover:text-amber-300 transition-colors">
                RISE
              </span>
              <span className="ml-2 hidden text-[11px] font-mono tracking-widest text-purple-300 uppercase sm:inline-block">
                Antigravity
              </span>
            </div>
          </Link>

          {/* Navigation Links */}
          <nav className="hidden md:flex items-center space-x-6 text-sm font-medium">
            <Link
              href="/"
              className={`transition-colors hover:text-amber-400 ${
                pathname === '/' ? 'text-amber-400 font-semibold' : 'text-gray-300'
              }`}
            >
              Platform
            </Link>
            <Link
              href="/incidents"
              className={`flex items-center gap-1.5 transition-colors hover:text-amber-400 ${
                pathname.startsWith('/incidents') ? 'text-amber-400 font-semibold' : 'text-gray-300'
              }`}
            >
              <LayoutDashboard className="w-4 h-4 text-purple-400" />
              <span>Live Incidents</span>
            </Link>
          </nav>
        </div>

        {/* Live Status Indicator */}
        <div className="hidden lg:flex items-center space-x-2 bg-black/50 border border-white/10 px-3.5 py-1.5 rounded-full text-xs font-mono">
          <span className={`pulse-dot ${realtimeConnected ? 'pulse-dot-green' : 'bg-amber-400'}`} />
          <span className="text-gray-300 font-medium">
            {realtimeConnected ? 'ALL SYSTEMS NOMINAL (WS)' : '3S POLLING FALLBACK'}
          </span>
        </div>

        {/* Session / Auth CTAs */}
        <div className="flex items-center space-x-4">
          {session ? (
            <>
              <div className="hidden sm:flex items-center space-x-3 border-r border-white/10 pr-4 text-xs font-mono">
                <div className="flex items-center space-x-1.5 text-gray-400">
                  <Server className="h-3.5 w-3.5 text-purple-400" />
                  <span className="text-gray-300">
                    {session.tenant_id ? `${session.tenant_id.substring(0, 8)}...` : 'dev-tenant'}
                  </span>
                </div>
                <div className="flex items-center space-x-1.5 rounded bg-purple-950/80 px-2.5 py-1 font-semibold text-purple-200 border border-purple-500/30">
                  <User className="h-3.5 w-3.5 text-amber-400" />
                  <span className="capitalize">{primaryRole}</span>
                </div>
              </div>

              <button
                onClick={() => logout()}
                className="flex items-center space-x-1.5 rounded-lg border border-red-500/30 bg-red-950/40 px-3.5 py-1.5 text-xs font-mono font-medium text-red-300 hover:bg-red-900/60 hover:border-red-400 transition-all"
              >
                <LogOut className="h-3.5 w-3.5" />
                <span>Sign Out</span>
              </button>
            </>
          ) : (
            <div className="flex items-center space-x-3">
              <Link
                href="/login"
                className="text-xs font-mono text-gray-300 hover:text-white px-3 py-1.5 transition-colors"
              >
                Sign In
              </Link>
              <Link
                href="/incidents"
                className="flex items-center space-x-1.5 rounded-lg bg-amber-500 px-4 py-1.5 text-xs font-bold text-black hover:bg-amber-400 transition-all glow-amber"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>Launch Console</span>
              </Link>
            </div>
          )}
        </div>

      </div>
    </header>
  );
}
