'use client';

import React from 'react';
import { LucideIcon } from 'lucide-react';
import { tx } from '../../lib/typography';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  theme?: 'dark' | 'light';
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  theme = 'dark',
}: EmptyStateProps) {
  const isDark = theme === 'dark';

  return (
    <div
      className={`min-h-[240px] w-full rounded-xl border p-8 text-center flex flex-col items-center justify-center transition-colors ${
        isDark
          ? 'border-[#E8E2D9]/15 bg-[#151121]/50'
          : 'border-[#E8E2D9] bg-[#FAF7F2]/60'
      }`}
    >
      <div
        className={`flex h-12 w-12 items-center justify-center rounded-xl mb-4 ${
          isDark
            ? 'bg-[#4C2A85]/20 border border-[#8B5CF6]/30 text-[#8B5CF6]'
            : 'bg-[#4C2A85]/10 border border-[#4C2A85]/20 text-[#4C2A85]'
        }`}
      >
        <Icon className="h-6 w-6" />
      </div>

      <h3
        className={tx(
          'cardTitle',
          isDark ? 'text-[#FAF7F2]' : 'text-[#0E0B14]'
        )}
      >
        {title}
      </h3>

      {description && (
        <p
          className={tx(
            'cardSummary',
            `mt-1.5 max-w-sm ${isDark ? 'text-[#6B6560]' : 'text-[#5A5550]'}`
          )}
        >
          {description}
        </p>
      )}

      {action && (
        <button
          onClick={action.onClick}
          className="mt-5 inline-flex items-center gap-2 rounded-lg border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 px-4 py-2 text-xs font-semibold text-[#8B5CF6] hover:bg-[#8B5CF6]/20 transition-all duration-200"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
