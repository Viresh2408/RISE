'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '../lib/auth-context';
import {
  Shield,
  LogOut,
  User,
  Server,
  Sparkles,
  LayoutDashboard,
  BarChart2,
  BookOpen,
  Lock,
  Plug,
  Menu,
  X,
} from 'lucide-react';
import { tx } from '../lib/typography';

const NAV_LINKS = [
  { href: '/', label: 'Platform', icon: null, exact: true },
  { href: '/incidents', label: 'Incidents', icon: LayoutDashboard, exact: false },
  { href: '/reports', label: 'Reports', icon: BarChart2, exact: false },
  { href: '/knowledge', label: 'Knowledge', icon: BookOpen, exact: false },
  { href: '/policies', label: 'Policies', icon: Lock, exact: false },
  { href: '/integrations', label: 'Integrations', icon: Plug, exact: false },
];

export function Navbar({ realtimeConnected = true }: { realtimeConnected?: boolean }) {
  const { session, logout } = useAuth();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const primaryRole = session?.roles?.[0] || 'viewer';

  const isActive = (href: string, exact: boolean) =>
    exact ? pathname === href : pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-50 bg-[#0E0B14]/90 backdrop-blur-md border-b border-[#E8E2D9]/10">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Brand */}
        <div className="flex items-center space-x-6">
          <Link href="/" className="flex items-center space-x-3 group flex-shrink-0">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#4C2A85] text-[#FAF7F2] shadow-sm group-hover:bg-[#8B5CF6] transition-colors">
              <Shield className="h-5 w-5" />
            </div>
            <span className={tx('navLogo', 'text-[#FAF7F2]')}>
              RISE
            </span>
          </Link>

          {/* Desktop Nav Links */}
          <nav className="hidden lg:flex items-center space-x-1">
            {NAV_LINKS.map(({ href, label, icon: Icon, exact }) => {
              const active = isActive(href, exact);
              return (
                <Link
                  key={href}
                  href={href}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors duration-150 ${tx(
                    'filterTab'
                  )} ${
                    active
                      ? 'bg-[#8B5CF6]/15 text-[#8B5CF6] font-semibold border border-[#8B5CF6]/30'
                      : 'text-[#6B6560] hover:text-[#FAF7F2] hover:bg-[#E8E2D9]/5'
                  }`}
                >
                  {Icon && <Icon className="w-3.5 h-3.5" />}
                  <span>{label}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Right side */}
        <div className="flex items-center space-x-4">
          {/* Live Status — desktop */}
          <div className="hidden xl:flex items-center space-x-2 bg-[#151121] border border-[#E8E2D9]/10 px-3 py-1.5 rounded-full">
            <span
              className={`h-2 w-2 rounded-full ${
                realtimeConnected ? 'bg-[#22C55E] animate-pulse' : 'bg-[#F5A623]'
              }`}
            />
            <span className={tx('cardMeta', 'text-[#E8E2D9] uppercase font-mono')}>
              {realtimeConnected ? 'Nominal Stream' : '3s Polling'}
            </span>
          </div>

          {session ? (
            <>
              <div className="hidden sm:flex items-center space-x-3 border-r border-[#E8E2D9]/10 pr-4 text-xs font-mono">
                <div className="flex items-center space-x-1.5 text-[#6B6560]">
                  <Server className="h-3.5 w-3.5 text-[#8B5CF6]" />
                  <span className="text-[#E8E2D9]">
                    {session.tenant_id ? `${session.tenant_id.substring(0, 8)}…` : 'dev-tenant'}
                  </span>
                </div>
                <div className="flex items-center space-x-1.5 rounded bg-[#4C2A85]/30 px-2.5 py-1 font-semibold text-[#8B5CF6] border border-[#8B5CF6]/30">
                  <User className="h-3.5 w-3.5 text-[#F5A623]" />
                  <span className="capitalize">{primaryRole}</span>
                </div>
              </div>
              <button
                onClick={() => logout()}
                className="flex items-center space-x-1.5 rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 px-3 py-1.5 text-xs font-semibold text-[#EF4444] hover:bg-[#EF4444]/20 transition-colors"
              >
                <LogOut className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Sign Out</span>
              </button>
            </>
          ) : (
            <div className="flex items-center space-x-3">
              <Link
                href="/login"
                className={tx('filterTab', 'text-[#E8E2D9] hover:text-[#8B5CF6] transition-colors')}
              >
                Sign In
              </Link>
              <Link
                href="/incidents"
                className="flex items-center space-x-1.5 rounded-lg bg-[#F5A623] px-4 py-1.5 text-xs font-semibold text-[#0E0B14] hover:bg-[#F5A623]/90 transition-colors"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>Console</span>
              </Link>
            </div>
          )}

          {/* Mobile hamburger */}
          <button
            className="lg:hidden text-[#6B6560] hover:text-[#FAF7F2] p-1"
            onClick={() => setMobileOpen(!mobileOpen)}
          >
            {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Menu */}
      {mobileOpen && (
        <div className="lg:hidden bg-[#0E0B14] border-t border-[#E8E2D9]/10 px-4 py-4 space-y-1">
          {NAV_LINKS.map(({ href, label, icon: Icon, exact }) => {
            const active = isActive(href, exact);
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setMobileOpen(false)}
                className={`flex items-center gap-2 px-3 py-2.5 rounded-lg transition-colors ${tx(
                  'filterTab'
                )} ${
                  active
                    ? 'bg-[#8B5CF6]/15 text-[#8B5CF6] font-semibold border border-[#8B5CF6]/30'
                    : 'text-[#6B6560] hover:text-[#FAF7F2] hover:bg-[#E8E2D9]/5'
                }`}
              >
                {Icon && <Icon className="w-4 h-4" />}
                <span>{label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </header>
  );
}
