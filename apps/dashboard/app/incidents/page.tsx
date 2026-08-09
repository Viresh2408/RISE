'use client';

import React, { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { Navbar } from '../../components/navbar';
import { IncidentCard } from '../../components/incident-card';
import { IncidentDTO, IncidentStatus, SeverityLevel } from '../../lib/types';
import { apiClient } from '../../lib/api-client';
import { useAuth } from '../../lib/auth-context';
import { supabase } from '../../lib/supabase';
import {
  AlertCircle,
  Filter,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  LayoutDashboard,
  CheckCircle2,
  Clock,
  ChevronRight,
} from 'lucide-react';

export default function IncidentsDashboard() {
  const { session } = useAuth();
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

  const fetchIncidents = async (silent = false) => {
    if (!session?.token) return;
    if (!silent) setLoading(true);

    try {
      const data = await apiClient.listIncidents(session.token, {
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
    if (!session?.token) return;

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
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2] font-hanken">
      <Navbar realtimeConnected={realtimeConnected} />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="font-fraunces text-3xl font-bold text-white flex items-center gap-3">
              <LayoutDashboard className="w-8 h-8 text-amber-400" />
              <span>Incident Command Center</span>
            </h1>
            <p className="text-sm text-gray-400 mt-1 font-mono">
              Live multi-agent telemetry, OPA policy approvals, and real-time execution logs
            </p>
          </div>

          <div className="flex items-center space-x-3">
            <button
              onClick={() => fetchIncidents()}
              className="flex items-center space-x-1.5 glass-panel hover:bg-white/10 text-gray-300 px-3.5 py-2 rounded-lg text-xs font-mono transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>

            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center space-x-2 bg-amber-500 hover:bg-amber-400 text-black font-bold text-xs px-4 py-2 rounded-lg transition-all glow-amber font-mono"
            >
              <Plus className="w-4 h-4" />
              <span>Report Incident</span>
            </button>
          </div>
        </div>

        {/* Filters & Search Row */}
        <div className="glass-panel p-4 rounded-xl mb-8 flex flex-col md:flex-row md:items-center justify-between gap-4 border border-white/10">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-mono text-gray-400 mr-2 flex items-center gap-1">
              <Filter className="w-3.5 h-3.5 text-purple-400" /> Filter:
            </span>

            {['all', 'in_progress', 'awaiting_approval', 'resolved'].map((st) => (
              <button
                key={st}
                onClick={() => setStatusFilter(st)}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all ${
                  statusFilter === st
                    ? 'bg-purple-900/80 text-amber-300 border border-purple-500/50 font-bold'
                    : 'bg-white/5 text-gray-400 hover:text-white border border-white/5'
                }`}
              >
                {st.replace('_', ' ').toUpperCase()}
              </button>
            ))}
          </div>

          <div className="relative">
            <Search className="w-4 h-4 text-gray-500 absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search by title, ID, service..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-black/60 border border-white/10 rounded-lg pl-9 pr-4 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 font-mono w-full md:w-64"
            />
          </div>
        </div>

        {/* Incident List Grid */}
        {loading && incidents.length === 0 ? (
          <div className="text-center py-20 font-mono text-gray-400">
            <RefreshCw className="w-8 h-8 animate-spin mx-auto text-amber-400 mb-3" />
            <p>Loading real-time incidents from backend pipeline...</p>
          </div>
        ) : filteredIncidents.length === 0 ? (
          <div className="glass-panel rounded-xl p-12 text-center my-8">
            <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto mb-3" />
            <h3 className="font-fraunces text-xl font-bold text-white">No Active Incidents Found</h3>
            <p className="text-sm text-gray-400 mt-1 max-w-md mx-auto">
              All infrastructure services are nominal. Click &quot;Report Incident&quot; above to trigger a test simulation.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {filteredIncidents.map((incident) => (
              <IncidentCard key={incident.id} incident={incident} />
            ))}
          </div>
        )}
      </main>

      {/* Create Incident Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="glass-panel w-full max-w-md rounded-xl p-6 border border-white/20 shadow-2xl">
            <h3 className="font-fraunces text-xl font-bold text-white mb-4 flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 text-amber-400" />
              <span>Simulate New Incident Event</span>
            </h3>

            <form onSubmit={handleCreateIncidentSubmit} className="space-y-4 font-mono text-xs">
              <div>
                <label className="block text-gray-400 mb-1">Incident Title</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Auth Service DB Connection Spike"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  className="w-full bg-black/70 border border-white/10 rounded px-3 py-2 text-white focus:outline-none focus:border-amber-400"
                />
              </div>

              <div>
                <label className="block text-gray-400 mb-1">Affected Service</label>
                <input
                  type="text"
                  required
                  value={newService}
                  onChange={(e) => setNewService(e.target.value)}
                  className="w-full bg-black/70 border border-white/10 rounded px-3 py-2 text-white focus:outline-none focus:border-amber-400"
                />
              </div>

              <div>
                <label className="block text-gray-400 mb-1">Severity</label>
                <select
                  value={newSeverity}
                  onChange={(e) => setNewSeverity(e.target.value as SeverityLevel)}
                  className="w-full bg-black/70 border border-white/10 rounded px-3 py-2 text-white focus:outline-none focus:border-amber-400"
                >
                  <option value="SEV1">SEV1 — Critical Production Outage</option>
                  <option value="SEV2">SEV2 — Major Service Degradation</option>
                  <option value="SEV3">SEV3 — Minor Functional Issue</option>
                  <option value="SEV4">SEV4 — Informational Warning</option>
                </select>
              </div>

              <div>
                <label className="block text-gray-400 mb-1">Description / Symptoms</label>
                <textarea
                  rows={3}
                  placeholder="Describe error rates, latency spikes, or alert payload..."
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  className="w-full bg-black/70 border border-white/10 rounded px-3 py-2 text-white focus:outline-none focus:border-amber-400"
                />
              </div>

              <div className="flex items-center justify-end space-x-3 pt-4 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 rounded text-gray-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="bg-amber-500 hover:bg-amber-400 text-black font-bold px-5 py-2 rounded transition-all glow-amber"
                >
                  {creating ? 'Ingesting...' : 'Trigger Pipeline'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
