import React from 'react';
import Link from 'next/link';
import { Shield, ArrowRight } from 'lucide-react';
import { tx } from '../lib/typography';

export default function NotFound() {
  return (
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2] flex items-center justify-center p-4">
      <div className="max-w-md w-full rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-8 text-center shadow-2xl space-y-6 overflow-hidden">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-[#4C2A85] text-[#FAF7F2] shadow-md">
          <Shield className="h-7 w-7" />
        </div>

        <div className={tx('metricNumeral', 'text-[#8B5CF6]')}>
          404
        </div>

        <div className="space-y-2">
          <h1 className={tx('sectionHeader', 'text-[#FAF7F2] normal-case text-xl font-semibold')}>
            Page Not Found
          </h1>
          <p className={tx('cardSummary', 'text-[#6B6560]')}>
            The route or incident resource you requested does not exist or has been decommissioned.
          </p>
        </div>

        <Link
          href="/incidents"
          className={tx(
            'ctaButton',
            'inline-flex items-center justify-center gap-2 rounded-lg bg-[#8B5CF6] px-6 py-3 text-xs text-[#FAF7F2] hover:bg-[#8B5CF6]/90 transition-colors shadow-md w-full'
          )}
        >
          <span>Return to Incidents Console</span>
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </div>
  );
}
