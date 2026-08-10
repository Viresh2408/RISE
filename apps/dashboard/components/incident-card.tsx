'use client';

import React from 'react';
import Link from 'next/link';
import { IncidentDTO } from '../lib/types';
import { AlertCircle, CheckCircle2, Clock, AlertTriangle, ArrowRight, Server } from 'lucide-react';
import { tx } from '../lib/typography';

export function IncidentCard({ incident }: { incident: IncidentDTO }) {
  // Severity left border color strip
  const getSevBorderColor = (sev: string) => {
    switch (sev) {
      case 'SEV1': return 'border-l-[#EF4444]';
      case 'SEV2': return 'border-l-[#F97316]';
      case 'SEV3': return 'border-l-[#F59E0B]';
      case 'SEV4':
      default: return 'border-l-[#64748B]';
    }
  };

  // Severity badge style
  const getSevBadgeStyle = (sev: string) => {
    switch (sev) {
      case 'SEV1': return 'bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30';
      case 'SEV2': return 'bg-[#F97316]/15 text-[#F97316] border-[#F97316]/30';
      case 'SEV3': return 'bg-[#F59E0B]/15 text-[#F59E0B] border-[#F59E0B]/30';
      case 'SEV4':
      default: return 'bg-[#64748B]/15 text-[#64748B] border-[#64748B]/30';
    }
  };

  // Status badge style
  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'awaiting_approval':
        return (
          <span className={`inline-flex items-center gap-1.5 rounded-md bg-[#F59E0B]/15 px-2.5 py-1 text-[#F59E0B] border border-[#F59E0B]/30 ${tx('badge')}`}>
            <AlertTriangle className="h-3 w-3" />
            <span>Awaiting Approval</span>
          </span>
        );
      case 'investigating':
        return (
          <span className={`inline-flex items-center gap-1.5 rounded-md bg-[#8B5CF6]/15 px-2.5 py-1 text-[#8B5CF6] border border-[#8B5CF6]/30 ${tx('badge')}`}>
            <Clock className="h-3 w-3 animate-spin" />
            <span>Investigating</span>
          </span>
        );
      case 'resolved':
      case 'closed':
        return (
          <span className={`inline-flex items-center gap-1.5 rounded-md bg-[#22C55E]/15 px-2.5 py-1 text-[#22C55E] border border-[#22C55E]/30 ${tx('badge')}`}>
            <CheckCircle2 className="h-3 w-3" />
            <span>{status}</span>
          </span>
        );
      case 'open':
      default:
        return (
          <span className={`inline-flex items-center gap-1.5 rounded-md bg-[#EF4444]/15 px-2.5 py-1 text-[#EF4444] border border-[#EF4444]/30 ${tx('badge')}`}>
            <AlertCircle className="h-3 w-3" />
            <span>Open</span>
          </span>
        );
    }
  };

  const formattedDate = incident.created_at
    ? new Date(incident.created_at).toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : 'Just now';

  return (
    <Link href={`/incidents/${incident.id}`} className="block group" data-testid="incident-card">
      <div
        className={`rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-4 sm:p-6 border-l-[3px] ${getSevBorderColor(
          incident.severity
        )} hover:border-[#8B5CF6]/50 hover:shadow-lg transition-all duration-200 relative overflow-hidden`}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-2.5 flex-1 min-w-0">
            {/* Badges & ID row */}
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className={`px-2.5 py-1 rounded-md border ${getSevBadgeStyle(incident.severity)} ${tx('badge')}`}>
                {incident.severity}
              </span>
              {getStatusBadge(incident.status)}
              <span className={tx('cardMeta', 'text-[#6B6560] font-mono')}>
                #{incident.id.substring(0, 8)}
              </span>
            </div>

            {/* Title */}
            <h3 className={tx('cardTitle', 'text-[#FAF7F2] group-hover:text-[#8B5CF6] transition-colors truncate')}>
              {incident.title}
            </h3>

            {/* Summary */}
            {incident.description && (
              <p className={tx('cardSummary', 'text-[#6B6560] line-clamp-2')}>
                {incident.description}
              </p>
            )}

            {/* Service & Timestamp */}
            <div className="flex items-center gap-4 pt-1 text-xs text-[#6B6560]">
              {incident.affected_service && (
                <div className="flex items-center gap-1.5">
                  <Server className="h-3.5 w-3.5 text-[#6B6560]" />
                  <span className={tx('cardMeta', 'text-[#E8E2D9]')}>{incident.affected_service}</span>
                </div>
              )}
              <div className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-[#6B6560]" />
                <span className={tx('cardMeta', 'text-[#6B6560] tabular-nums')}>{formattedDate}</span>
              </div>
            </div>
          </div>

          {/* Arrow */}
          <div className="flex items-center justify-end sm:self-center flex-shrink-0">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] text-[#6B6560] group-hover:border-[#8B5CF6] group-hover:bg-[#8B5CF6] group-hover:text-[#FAF7F2] transition-all duration-200">
              <ArrowRight className="h-4 w-4" />
            </div>
          </div>
        </div>
      </div>
    </Link>
  );
}
