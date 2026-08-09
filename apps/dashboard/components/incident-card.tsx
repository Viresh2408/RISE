'use client';

import React from 'react';
import Link from 'next/link';
import { IncidentDTO } from '../lib/types';
import { AlertCircle, CheckCircle2, Clock, AlertTriangle, ArrowRight, Server } from 'lucide-react';

export function IncidentCard({ incident }: { incident: IncidentDTO }) {
  const getSeverityBadgeClass = (sev: string) => {
    switch (sev) {
      case 'SEV1':
        return 'badge-sev1';
      case 'SEV2':
        return 'badge-sev2';
      case 'SEV3':
        return 'badge-sev3';
      case 'SEV4':
      default:
        return 'badge-sev4';
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'awaiting_approval':
        return (
          <span className="flex items-center space-x-1 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-400 border border-amber-500/30">
            <AlertTriangle className="h-3 w-3" />
            <span>Awaiting Approval</span>
          </span>
        );
      case 'investigating':
        return (
          <span className="flex items-center space-x-1 rounded-full bg-blue-500/10 px-2.5 py-0.5 text-xs font-semibold text-blue-400 border border-blue-500/30">
            <Clock className="h-3 w-3 animate-spin" />
            <span>Investigating</span>
          </span>
        );
      case 'resolved':
      case 'closed':
        return (
          <span className="flex items-center space-x-1 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-semibold text-emerald-400 border border-emerald-500/30">
            <CheckCircle2 className="h-3 w-3" />
            <span className="capitalize">{status}</span>
          </span>
        );
      case 'open':
      default:
        return (
          <span className="flex items-center space-x-1 rounded-full bg-red-500/10 px-2.5 py-0.5 text-xs font-semibold text-red-400 border border-red-500/30">
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
        second: '2-digit',
      })
    : 'Just now';

  return (
    <Link href={`/incidents/${incident.id}`} className="block group">
      <div className="glass-card p-5 relative overflow-hidden">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-2 flex-1">
            <div className="flex items-center space-x-3 flex-wrap gap-y-2">
              <span className={`px-2.5 py-0.5 rounded-md text-xs font-bold ${getSeverityBadgeClass(incident.severity)}`}>
                {incident.severity}
              </span>
              {getStatusBadge(incident.status)}
              <span className="text-xs font-mono text-gray-500">#{incident.id.substring(0, 8)}</span>
            </div>

            <h3 className="text-base font-semibold text-white group-hover:text-blue-400 transition-colors">
              {incident.title}
            </h3>

            {incident.description && (
              <p className="text-xs text-gray-400 line-clamp-2">{incident.description}</p>
            )}

            <div className="flex items-center space-x-4 pt-1 text-xs text-gray-500">
              {incident.affected_service && (
                <div className="flex items-center space-x-1 text-gray-400">
                  <Server className="h-3.5 w-3.5 text-gray-500" />
                  <span>{incident.affected_service}</span>
                </div>
              )}
              <div className="flex items-center space-x-1">
                <Clock className="h-3.5 w-3.5" />
                <span>{formattedDate}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end md:self-center">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#1a2333] text-gray-400 group-hover:bg-blue-600 group-hover:text-white transition-all">
              <ArrowRight className="h-4 w-4" />
            </div>
          </div>
        </div>
      </div>
    </Link>
  );
}
