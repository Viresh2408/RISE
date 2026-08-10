'use client';

import React from 'react';

interface CardSkeletonProps {
  count?: number;
  variant?: 'incident' | 'report' | 'policy' | 'knowledge' | 'integration';
  theme?: 'dark' | 'light';
}

export function CardSkeleton({
  count = 3,
  variant = 'incident',
  theme = 'dark',
}: CardSkeletonProps) {
  const isDark = theme === 'dark';

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 w-full">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={`rounded-xl border p-6 animate-pulse relative overflow-hidden ${
            isDark
              ? 'border-[#E8E2D9]/10 bg-[#151121]'
              : 'border-[#E8E2D9] bg-white'
          }`}
        >
          {variant === 'incident' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="h-4 w-24 bg-[#E8E2D9]/10 rounded" />
                <div className="h-4 w-16 bg-[#E8E2D9]/10 rounded" />
              </div>
              <div className="h-5 w-3/4 bg-[#E8E2D9]/20 rounded" />
              <div className="space-y-2">
                <div className="h-3 w-full bg-[#E8E2D9]/10 rounded" />
                <div className="h-3 w-5/6 bg-[#E8E2D9]/10 rounded" />
              </div>
            </div>
          )}

          {variant === 'report' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="h-3 w-20 bg-[#E8E2D9]/10 rounded" />
                <div className="h-4 w-4 bg-[#E8E2D9]/20 rounded-full" />
              </div>
              <div className="h-8 w-28 bg-[#E8E2D9]/20 rounded" />
              <div className="h-3 w-32 bg-[#E8E2D9]/10 rounded" />
            </div>
          )}

          {variant === 'policy' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="h-4 w-28 bg-[#E8E2D9]/20 rounded" />
                <div className="h-4 w-20 bg-[#E8E2D9]/10 rounded-full" />
              </div>
              <div className="h-4 w-full bg-[#E8E2D9]/10 rounded" />
              <div className="flex gap-2">
                <div className="h-5 w-16 bg-[#E8E2D9]/10 rounded-full" />
                <div className="h-5 w-16 bg-[#E8E2D9]/10 rounded-full" />
              </div>
            </div>
          )}

          {variant === 'knowledge' && (
            <div className="space-y-4">
              <div className="h-5 w-4/5 bg-[#E8E2D9]/20 rounded" />
              <div className="space-y-2">
                <div className="h-3 w-full bg-[#E8E2D9]/10 rounded" />
                <div className="h-3 w-3/4 bg-[#E8E2D9]/10 rounded" />
              </div>
              <div className="flex gap-2">
                <div className="h-5 w-12 bg-[#E8E2D9]/10 rounded-full" />
                <div className="h-5 w-14 bg-[#E8E2D9]/10 rounded-full" />
              </div>
            </div>
          )}

          {variant === 'integration' && (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 bg-[#E8E2D9]/20 rounded-lg" />
                <div className="space-y-2">
                  <div className="h-4 w-24 bg-[#E8E2D9]/20 rounded" />
                  <div className="h-3 w-16 bg-[#E8E2D9]/10 rounded" />
                </div>
              </div>
              <div className="h-8 w-20 bg-[#E8E2D9]/20 rounded-lg" />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
