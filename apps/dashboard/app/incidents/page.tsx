'use client';

import React, { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { Navbar } from '../../components/navbar';
import { IncidentCard } from '../../components/incident-card';
import { EmptyState } from '../../components/shared/EmptyState';
import { CardSkeleton } from '../../components/shared/CardSkeleton';
import { IncidentDTO, SeverityLevel } from '../../lib/types';
import { apiClient } from '../../lib/api-client';
import { useAuth } from '../../lib/auth-context';
import { supabase } from '../../lib/supabase';
import { tx } from '../../lib/typography';
import {
  AlertCircle,
  Filter,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  Inbox,
  X,
} from 'lucide-react';

const STATUS_TABS = [
  { id: 'all', label: 'All Incidents' },
  { id: 'open', label: 'Open' },
  { id: 'investigating', label: 'Investigating' },
  { id: 'awaiting_approval', label: 'Awaiting Approval' },
  { id: 'resolved', label: 'Resolved' },
  { id: 'closed', label: 'Closed' },
];

export default function IncidentsDashboard() {
  const { session, hasRole } = useAuth();
  const [incidents, setIncidents] = useState<IncidentDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Realtime & Polling status
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Create Modal State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newSeverity, setNewSeverity] = useState<SeverityLevel>('SEV2');
  const [newService, setNewService] = useState('auth-service');
  const [creating, setCreating] = useState(false);

  const canCreate = hasRole('engineer');

  const fetchIncidents = async (silent = false) => {
    const activeToken = session?.token || 'demo-token-hardcoded';
    if (!silent) setLoading(true);

    try {
      const data = await apiClient.listIncidents(activeToken, {
        status: statusFilter !== 'all' ? statusFilter : undefined,
        severity: severityFilter !== 'all' ? severityFilter : undefined,
      });
      setIncidents(data || []);
      setErrorMsg(null);
    } catch (err: any) {
      console.error('Failed fetching incidents:', err);
      if (!silent) setErrorMsg(err.message || 'Failed to load incidents');
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    fetchIncidents();
  }, [session, statusFilter, severityFilter]);

  // Realtime Subscription with Deduplicated 3s Polling Fallback
  useEffect(() => {
    const activeToken = session?.token || 'demo-token-hardcoded';

    const channel = supabase
      .channel('public:incidents')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'incidents' },
        () => {
          fetchIncidents(true);
        }
      )
      .subscribe((status) => {
        if (status === 'SUBSCRIBED') {
          setRealtimeConnected(true);
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
        } else {
          setRealtimeConnected(false);
          if (!pollingRef.current) {
            pollingRef.current = setInterval(() => {
              fetchIncidents(true);
            }, 3000);
          }
        }
      });

    return () => {
      supabase.removeChannel(channel);
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [session, statusFilter, severityFilter]);

  const handleCreateIncidentSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.token || !newTitle.trim()) return;

    setCreating(true);
    try {
      await apiClient.createIncident(session.token, {
        title: newTitle,
        description: newDesc,
        severity: newSeverity,
        affected_service: newService,
      });
      setShowCreateModal(false);
      setNewTitle('');
      setNewDesc('');
      fetchIncidents();
    } catch (err: any) {
      alert(`Failed to create incident: ${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  const filteredIncidents = incidents.filter((inc) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      inc.title.toLowerCase().includes(q) ||
      (inc.affected_service || '').toLowerCase().includes(q) ||
      inc.id.toLowerCase().includes(q)
    );
  });

  return (
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2]">
      <Navbar realtimeConnected={realtimeConnected} />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Header Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className={tx('incidentTitle', 'text-[#FAF7F2] flex items-center gap-3')}>
              <ShieldAlert className="w-7 h-7 text-[#8B5CF6]" />
              <span>Active Incidents Console</span>
            </h1>
            <p className={tx('cardMeta', 'text-[#6B6560] mt-1 font-mono')}>
              Real-time multi-agent triage, RCA evidence, and approval controls
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => fetchIncidents()}
              className="inline-flex items-center gap-2 rounded-lg border border-[#E8E2D9]/15 bg-[#151121] px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/10 transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>

            {canCreate && (
              <button
                onClick={() => setShowCreateModal(true)}
                className="inline-flex items-center gap-2 rounded-lg bg-[#8B5CF6] px-4 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#8B5CF6]/90 transition-colors shadow-md"
              >
                <Plus className="w-4 h-4" />
                <span>Trigger Incident</span>
              </button>
            )}
          </div>
        </div>

        {errorMsg && (
          <div className="flex items-center gap-3 rounded-xl border border-[#EF4444]/30 bg-[#EF4444]/10 p-4 text-[#EF4444] text-xs font-mono">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Filter Bar & Search */}
        <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
          {/* Status Tabs */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-2 md:pb-0 scrollbar-none">
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setStatusFilter(tab.id)}
                className={`px-3 py-1.5 rounded-lg text-xs transition-colors whitespace-nowrap ${tx(
                  'filterTab'
                )} ${
                  statusFilter === tab.id
                    ? 'bg-[#8B5CF6] text-[#FAF7F2] font-semibold'
                    : 'text-[#6B6560] hover:text-[#FAF7F2] hover:bg-[#E8E2D9]/5'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Severity & Search */}
          <div className="flex items-center gap-3">
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3 py-1.5 text-xs text-[#E8E2D9] focus:border-[#8B5CF6] focus:outline-none"
            >
              <option value="all">All Severities</option>
              <option value="SEV1">SEV1 - Critical</option>
              <option value="SEV2">SEV2 - High</option>
              <option value="SEV3">SEV3 - Medium</option>
              <option value="SEV4">SEV4 - Low</option>
            </select>

            <div className="relative flex-1 md:w-64">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-[#6B6560]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search service, title..."
                className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] pl-9 pr-3 py-1.5 text-xs text-[#FAF7F2] placeholder-[#6B6560] focus:border-[#8B5CF6] focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* Content Area */}
        {loading ? (
          <CardSkeleton count={6} variant="incident" />
        ) : filteredIncidents.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title="No incidents found"
            description={
              statusFilter !== 'all' || severityFilter !== 'all' || searchQuery
                ? 'No incidents match your current filter parameters. Try resetting your filters.'
                : 'All systems are operating normally. No active incidents registered.'
            }
            action={
              statusFilter !== 'all' || severityFilter !== 'all' || searchQuery
                ? {
                    label: 'Reset Filters',
                    onClick: () => {
                      setStatusFilter('all');
                      setSeverityFilter('all');
                      setSearchQuery('');
                    },
                  }
                : undefined
            }
            theme="dark"
          />
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {filteredIncidents.map((inc) => (
              <IncidentCard key={inc.id} incident={inc} />
            ))}
          </div>
        )}
      </main>

      {/* Manual Trigger Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-xl border border-[#E8E2D9]/20 bg-[#151121] p-6 shadow-2xl space-y-6">
            <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
              <h3 className={tx('sectionHeader', 'text-[#FAF7F2] normal-case text-lg font-semibold')}>
                Trigger Manual Incident Pipeline
              </h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-[#6B6560] hover:text-[#FAF7F2]"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleCreateIncidentSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className={tx('formLabel', 'text-[#6B6560]')}>Incident Title</label>
                <input
                  type="text"
                  required
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="e.g. API Gateway High Error Rate"
                  className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-sm text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                />
              </div>

              <div className="space-y-1.5">
                <label className={tx('formLabel', 'text-[#6B6560]')}>Affected Service</label>
                <input
                  type="text"
                  required
                  value={newService}
                  onChange={(e) => setNewService(e.target.value)}
                  placeholder="e.g. auth-service"
                  className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-sm text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                />
              </div>

              <div className="space-y-1.5">
                <label className={tx('formLabel', 'text-[#6B6560]')}>Severity Level</label>
                <select
                  value={newSeverity}
                  onChange={(e) => setNewSeverity(e.target.value as SeverityLevel)}
                  className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-sm text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                >
                  <option value="SEV1">SEV1 - Critical (Outage)</option>
                  <option value="SEV2">SEV2 - High (Degraded)</option>
                  <option value="SEV3">SEV3 - Medium (Partial)</option>
                  <option value="SEV4">SEV4 - Low (Minor)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className={tx('formLabel', 'text-[#6B6560]')}>Description & Log Context</label>
                <textarea
                  rows={3}
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="Provide initial error logs or context..."
                  className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-sm text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-[#E8E2D9]/10">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="rounded-lg border border-[#E8E2D9]/15 bg-transparent px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="rounded-lg bg-[#8B5CF6] px-5 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#8B5CF6]/90 disabled:opacity-50"
                >
                  {creating ? 'Dispatching Agent...' : 'Dispatch Agent'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
