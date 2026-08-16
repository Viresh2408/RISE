'use client';

import React, { useEffect, useState } from 'react';
import { Navbar } from '../../components/navbar';
import { AdminGate } from '../../components/shared/AdminGate';
import { CardSkeleton } from '../../components/shared/CardSkeleton';
import { EmptyState } from '../../components/shared/EmptyState';
import { PolicyDTO, RiskTier } from '../../lib/types';
import { apiClient } from '../../lib/api-client';
import { useAuth } from '../../lib/auth-context';
import { tx } from '../../lib/typography';
import {
  Shield,
  Lock,
  Plus,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  ShieldAlert,
  X,
  FileCode,
  Zap,
  Edit2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

const DEMO_POLICIES: PolicyDTO[] = [
  {
    id: 'pol-001',
    name: 'Critical Service Restart Guard',
    description: 'Any restart_pod or kill_pod action targeting a CRITICAL service requires explicit human approval.',
    action_types: ['restart_pod', 'kill_pod'],
    risk_tier: 'critical',
    requires_approval: true,
    version: 3,
    created_at: new Date(Date.now() - 30 * 86400000).toISOString(),
  },
  {
    id: 'pol-002',
    name: 'Database Write Guard',
    description: 'Any direct database write operation (DDL or destructive DML) must be pre-approved.',
    action_types: ['run_sql', 'drop_table', 'truncate_table'],
    risk_tier: 'high',
    requires_approval: true,
    version: 2,
    created_at: new Date(Date.now() - 20 * 86400000).toISOString(),
  },
  {
    id: 'pol-003',
    name: 'Scale-Down Auto-Policy',
    description: 'Scaling down replica count on non-critical services may proceed autonomously during off-peak hours.',
    action_types: ['scale_deployment'],
    risk_tier: 'medium',
    requires_approval: false,
    version: 1,
    created_at: new Date(Date.now() - 15 * 86400000).toISOString(),
  },
  {
    id: 'pol-004',
    name: 'Log Rotation Automation',
    description: 'Log cleanup and rotation actions are fully autonomous with no approval required.',
    action_types: ['rotate_logs', 'archive_logs'],
    risk_tier: 'low',
    requires_approval: false,
    version: 1,
    created_at: new Date(Date.now() - 10 * 86400000).toISOString(),
  },
];

function getRiskTierStyle(tier: RiskTier) {
  switch (tier) {
    case 'critical':
      return { border: 'border-l-[#EF4444]', badge: 'bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30' };
    case 'high':
      return { border: 'border-l-[#F97316]', badge: 'bg-[#F97316]/15 text-[#F97316] border-[#F97316]/30' };
    case 'medium':
      return { border: 'border-l-[#F59E0B]', badge: 'bg-[#F59E0B]/15 text-[#F59E0B] border-[#F59E0B]/30' };
    case 'low':
    default:
      return { border: 'border-l-[#22C55E]', badge: 'bg-[#22C55E]/15 text-[#22C55E] border-[#22C55E]/30' };
  }
}

function PoliciesContent() {
  const { session } = useAuth();
  const [policies, setPolicies] = useState<PolicyDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [actions, setActions] = useState('');
  const [riskTier, setRiskTier] = useState<RiskTier>('medium');
  const [requiresApproval, setRequiresApproval] = useState(false);
  const [creating, setCreating] = useState(false);

  // Archived version toggle state per policy ID
  const [expandedHistory, setExpandedHistory] = useState<Record<string, boolean>>({});

  const fetchPolicies = async () => {
    if (!session?.token) return;
    setLoading(true);
    try {
      const data = await apiClient.listPolicies(session.token);
      setPolicies(data || DEMO_POLICIES);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load policies');
      setPolicies(DEMO_POLICIES);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPolicies();
  }, [session]);

  // Lock requires_approval to true when risk_tier === 'critical'
  useEffect(() => {
    if (riskTier === 'critical') {
      setRequiresApproval(true);
    }
  }, [riskTier]);

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.token || !name.trim()) return;

    setCreating(true);
    try {
      const actionArray = actions.split(',').map((a) => a.trim()).filter(Boolean);
      await apiClient.createPolicy(session.token, {
        name,
        description: desc,
        action_types: actionArray,
        action_pattern: actionArray[0] || name || 'k8s.pod.restart',
        environment: 'production',
        max_blast_radius: 1,
        risk_tier: riskTier,
        requires_approval: riskTier === 'critical' ? true : requiresApproval,
      });
      setShowCreateModal(false);
      setName('');
      setDesc('');
      setActions('');
      fetchPolicies();
    } catch (err: any) {
      alert(`Failed to save policy: ${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className={tx('incidentTitle', 'text-[#FAF7F2] flex items-center gap-3')}>
            <Lock className="w-7 h-7 text-[#8B5CF6]" />
            <span>OPA Risk & Approval Policies</span>
          </h1>
          <p className={tx('cardMeta', 'text-[#6B6560] mt-1 font-mono')}>
            Deterministic action gating, environment scoping, and approval rule matrices
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchPolicies}
            className="inline-flex items-center gap-2 rounded-lg border border-[#E8E2D9]/15 bg-[#151121] px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/10 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>

          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-[#8B5CF6] px-4 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#8B5CF6]/90 transition-colors shadow-md"
          >
            <Plus className="w-4 h-4" />
            <span>New Risk Policy</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-xl border border-[#F5A623]/30 bg-[#F5A623]/10 p-4 text-[#F5A623] text-xs font-mono">
          <AlertTriangle className="w-5 h-5 flex-shrink-0" />
          <span>API disconnected — displaying cached policy matrix. {error}</span>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <CardSkeleton count={4} variant="policy" />
      ) : policies.length === 0 ? (
        <EmptyState
          icon={Shield}
          title="No risk policies configured"
          description="Define risk policy rules to dictate autonomous action gates."
          action={{
            label: 'Create Policy',
            onClick: () => setShowCreateModal(true),
          }}
          theme="dark"
        />
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {policies.map((pol) => {
            const style = getRiskTierStyle(pol.risk_tier);
            const isHistoryOpen = !!expandedHistory[pol.id];
            const actionTypes = (pol.action_types && pol.action_types.length > 0)
              ? pol.action_types
              : (pol.action_pattern ? [pol.action_pattern] : []);
            const polName = pol.name || pol.id || pol.action_pattern || 'Untitled Policy';
            const polDesc = pol.description || (pol.action_pattern ? `Policy governing ${pol.action_pattern} in ${pol.environment || 'production'}` : 'No description provided.');

            return (
              <div
                key={pol.id}
                data-testid="policy-card"
                className={`rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 border-l-[4px] ${style.border} space-y-4 shadow-md hover:border-[#8B5CF6]/40 transition-all duration-200`}
              >
                {/* Top Row */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-center gap-3 flex-wrap">
                    <h3 className={tx('cardTitle', 'text-[#FAF7F2]')}>{polName}</h3>
                    <span className={`px-2.5 py-0.5 rounded text-xs font-mono font-bold uppercase border ${style.badge}`}>
                      {pol.risk_tier} Risk
                    </span>
                    <span
                      className={`px-2.5 py-0.5 rounded text-xs font-mono font-semibold ${
                        pol.requires_approval
                          ? 'bg-[#F59E0B]/15 text-[#F59E0B] border border-[#F59E0B]/30'
                          : 'bg-[#22C55E]/15 text-[#22C55E] border border-[#22C55E]/30'
                      }`}
                    >
                      {pol.requires_approval ? 'Requires Approval' : 'Auto-Safe'}
                    </span>
                  </div>

                  <span className={tx('cardMeta', 'text-[#6B6560] font-mono')}>
                    v{pol.version} Active
                  </span>
                </div>

                <p className={tx('cardSummary', 'text-[#6B6560]')}>{polDesc}</p>

                {/* Action types chips */}
                {actionTypes.length > 0 && (
                  <div className="flex items-center gap-2 flex-wrap pt-1">
                    <span className={tx('cardMeta', 'text-[#6B6560]')}>Actions:</span>
                    {actionTypes.map((action, i) => (
                      <span
                        key={i}
                        className="rounded border border-[#8B5CF6]/30 bg-[#8B5CF6]/10 px-2 py-0.5 text-xs font-mono text-[#8B5CF6]"
                      >
                        {action}
                      </span>
                    ))}
                  </div>
                )}

                {/* Archived version history collapsible */}
                {pol.version > 1 && (
                  <div className="pt-2 border-t border-[#E8E2D9]/10">
                    <button
                      onClick={() =>
                        setExpandedHistory((prev) => ({ ...prev, [pol.id]: !prev[pol.id] }))
                      }
                      className="inline-flex items-center gap-2 text-xs font-mono text-[#6B6560] hover:text-[#FAF7F2] transition-colors"
                    >
                      {isHistoryOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                      <span>View history ({pol.version - 1} archived versions)</span>
                    </button>

                    {isHistoryOpen && (
                      <div className="mt-3 p-3 rounded-lg border border-[#E8E2D9]/10 bg-[#0E0B14]/60 space-y-2 opacity-50 text-xs font-mono">
                        <div className="flex justify-between text-[#6B6560]">
                          <span>v{pol.version - 1} (Archived)</span>
                          <span>{pol.created_at ? new Date(pol.created_at).toLocaleDateString() : 'Previous'}</span>
                        </div>
                        <p className="text-[#6B6560]">{polDesc}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* New Policy Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl border border-[#E8E2D9]/20 bg-[#151121] p-6 shadow-2xl space-y-6">
            <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
              <h3 className={tx('sectionHeader', 'text-[#FAF7F2] normal-case text-lg font-semibold')}>
                Define New Risk Policy Rule
              </h3>
              <button onClick={() => setShowCreateModal(false)} className="text-[#6B6560] hover:text-[#FAF7F2]">
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className={tx('formLabel', 'text-[#6B6560]')}>Policy Name</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Critical Deployment Restart Rule"
                  className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-sm text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                />
              </div>

              <div className="space-y-1.5">
                <label className={tx('formLabel', 'text-[#6B6560]')}>Action Patterns (Comma-separated)</label>
                <input
                  type="text"
                  required
                  value={actions}
                  onChange={(e) => setActions(e.target.value)}
                  placeholder="e.g. restart_pod, kill_pod, scale_up"
                  className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-xs font-mono text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                />
              </div>

              <div className="space-y-1.5">
                <label className={tx('formLabel', 'text-[#6B6560]')}>Risk Tier</label>
                <select
                  value={riskTier}
                  onChange={(e) => setRiskTier(e.target.value as RiskTier)}
                  className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-sm text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                >
                  <option value="low">Low Risk (Autonomous)</option>
                  <option value="medium">Medium Risk</option>
                  <option value="high">High Risk</option>
                  <option value="critical">Critical Risk (Enforced Gate)</option>
                </select>
              </div>

              {/* Approval Toggle */}
              <div className="space-y-2 rounded-lg border border-[#E8E2D9]/10 bg-[#0E0B14] p-4">
                <div className="flex items-center justify-between">
                  <span className={tx('formLabel', 'text-[#FAF7F2] normal-case')}>Require Human Approval</span>
                  <input
                    type="checkbox"
                    checked={requiresApproval}
                    disabled={riskTier === 'critical'}
                    onChange={(e) => setRequiresApproval(e.target.checked)}
                    className="h-4 w-4 rounded border-[#E8E2D9]/30 text-[#8B5CF6] focus:ring-[#8B5CF6] disabled:opacity-50 cursor-pointer"
                  />
                </div>
                {riskTier === 'critical' && (
                  <p className={tx('cardMeta', 'text-[#F5A623] italic')}>
                    Approval is hardcoded for critical risk — this cannot be disabled.
                  </p>
                )}
              </div>

              <div className="space-y-1.5">
                <label className={tx('formLabel', 'text-[#6B6560]')}>Description</label>
                <textarea
                  rows={3}
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  placeholder="Rationale for this policy constraint..."
                  className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-sm text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-[#E8E2D9]/10">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="rounded-lg border border-[#E8E2D9]/15 px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="rounded-lg bg-[#8B5CF6] px-5 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#8B5CF6]/90 disabled:opacity-50"
                >
                  {creating ? 'Saving Policy...' : 'Save Policy'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}

export default function PoliciesPage() {
  return (
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2]">
      <Navbar />
      <AdminGate>
        <PoliciesContent />
      </AdminGate>
    </div>
  );
}
