'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Navbar } from '../../../components/navbar';
import { PipelineCanvas } from '../../../components/pipeline-canvas';
import { ActionModals } from '../../../components/action-modals';
import { IncidentDetailDTO } from '../../../lib/types';
import { apiClient } from '../../../lib/api-client';
import { useAuth } from '../../../lib/auth-context';
import {
  ArrowLeft,
  ShieldAlert,
  Activity,
  CheckCircle2,
  Clock,
  Lock,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  AlertTriangle,
  FileCode,
  Layers,
  Terminal,
  Cpu,
} from 'lucide-react';

export default function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { session } = useAuth();

  const [incident, setIncident] = useState<IncidentDetailDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Modals state
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [showModifyModal, setShowModifyModal] = useState(false);

  const fetchIncidentDetail = async () => {
    if (!session?.token || !id) return;
    setLoading(true);

    try {
      const data = await apiClient.getIncidentDetail(session.token, id as string);
      setIncident(data);
      setErrorMsg(null);
    } catch (err: any) {
      console.error('Failed fetching incident detail:', err);
      setErrorMsg(err.message || 'Failed to load incident detail');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIncidentDetail();
  }, [session, id]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2] font-hanken">
        <Navbar />
        <div className="max-w-7xl mx-auto px-4 py-24 text-center font-mono">
          <RefreshCw className="w-10 h-10 animate-spin mx-auto text-amber-400 mb-4" />
          <p className="text-gray-300">Fetching incident pipeline telemetry & OPA matrix...</p>
        </div>
      </div>
    );
  }

  if (errorMsg || !incident) {
    return (
      <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2] font-hanken">
        <Navbar />
        <div className="max-w-3xl mx-auto px-4 py-16">
          <div className="glass-panel p-8 rounded-xl border border-red-500/40 text-center">
            <ShieldAlert className="w-12 h-12 text-red-400 mx-auto mb-3" />
            <h2 className="font-fraunces text-2xl font-bold text-white mb-2">Incident Detail Error</h2>
            <p className="text-sm font-mono text-gray-300 mb-6">{errorMsg || 'Incident record not found'}</p>
            <Link
              href="/incidents"
              className="inline-flex items-center space-x-2 bg-amber-500 hover:bg-amber-400 text-black font-bold px-5 py-2.5 rounded-lg font-mono text-xs"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Back to Command Center</span>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const isAwaitingApproval = incident.status === 'awaiting_approval';
  const severityBadgeClass =
    incident.severity === 'SEV1'
      ? 'badge-sev1'
      : incident.severity === 'SEV2'
      ? 'badge-sev2'
      : incident.severity === 'SEV3'
      ? 'badge-sev3'
      : 'badge-sev4';

  return (
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2] font-hanken">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Top Breadcrumb Navigation */}
        <div className="mb-6 flex items-center justify-between">
          <Link
            href="/incidents"
            className="flex items-center space-x-2 text-xs font-mono text-gray-400 hover:text-amber-400 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Return to Live Incidents Feed</span>
          </Link>
          <span className="font-mono text-xs text-purple-300 bg-purple-950/80 border border-purple-500/30 px-3 py-1 rounded">
            ID: {incident.id}
          </span>
        </div>

        {/* Incident Summary Card Header */}
        <div className="glass-panel p-6 rounded-xl border border-white/10 mb-8">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="flex items-center space-x-3 mb-2">
                <span className={`px-3 py-1 rounded text-xs font-mono font-bold ${severityBadgeClass}`}>
                  {incident.severity}
                </span>
                <span className="text-xs font-mono text-gray-400 bg-white/5 px-2.5 py-1 rounded border border-white/5">
                  Service: <strong className="text-white">{incident.affected_service}</strong>
                </span>
                <span className="text-xs font-mono text-emerald-400 flex items-center gap-1">
                  <span className="pulse-dot pulse-dot-green" />
                  <span className="capitalize">{incident.status.replace('_', ' ')}</span>
                </span>
              </div>

              <h1 className="font-fraunces text-2xl sm:text-3xl font-bold text-white mb-2">
                {incident.title}
              </h1>
              <p className="text-sm text-gray-300 max-w-3xl">{incident.description}</p>
            </div>

            {/* Approval CTA Panel */}
            {isAwaitingApproval && (
              <div className="glass-card p-4 rounded-xl border-2 border-amber-500/50 glow-amber flex flex-col items-center justify-center space-y-3 min-w-[240px]">
                <div className="flex items-center space-x-1.5 text-xs font-mono text-amber-300">
                  <Lock className="w-4 h-4 text-amber-400 animate-bounce" />
                  <span className="font-bold uppercase tracking-wider">OPA Approval Required</span>
                </div>
                <div className="flex items-center space-x-2 w-full">
                  <button
                    onClick={() => setShowApproveModal(true)}
                    className="flex-1 bg-amber-500 hover:bg-amber-400 text-black font-bold text-xs py-2 rounded transition-all font-mono"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => setShowModifyModal(true)}
                    className="flex-1 bg-purple-900/80 hover:bg-purple-800 text-purple-200 font-bold text-xs py-2 rounded transition-all font-mono border border-purple-500/40"
                  >
                    Modify
                  </button>
                  <button
                    onClick={() => setShowRejectModal(true)}
                    className="flex-1 bg-red-950/80 hover:bg-red-900 text-red-300 font-bold text-xs py-2 rounded transition-all font-mono border border-red-500/40"
                  >
                    Reject
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 3D Agent Pipeline Canvas Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-3 font-mono text-xs">
            <span className="text-amber-400 font-bold uppercase tracking-wider flex items-center gap-2">
              <Cpu className="w-4 h-4" /> 3D Execution Graph State
            </span>
            <span className="text-gray-400">Step 5/7 Authorized</span>
          </div>
          <PipelineCanvas activeStep={4} interactive={true} />
        </div>

        {/* Multi-Agent Deep Diagnostics Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Left 2 Columns: Evidence, RCA, Action Plan */}
          <div className="lg:col-span-2 space-y-6">
            {/* Root Cause Inference Box */}
            {incident.root_cause && (
              <div className="glass-panel p-6 rounded-xl border border-white/10">
                <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
                  <h3 className="font-fraunces text-lg font-bold text-white flex items-center gap-2">
                    <Activity className="w-5 h-5 text-amber-400" />
                    <span>Root Cause Agent Diagnosis</span>
                  </h3>
                  <span className="font-mono text-xs text-amber-300 bg-amber-950/80 px-2.5 py-1 rounded border border-amber-500/30">
                    Confidence: {(incident.root_cause.confidence * 100).toFixed(0)}%
                  </span>
                </div>

                <p className="text-sm font-semibold text-white mb-2">
                  Primary Cause: <span className="text-amber-300 font-mono">{incident.root_cause.cause}</span>
                </p>
                <p className="text-xs text-gray-300 leading-relaxed mb-4">{incident.root_cause.explanation}</p>

                {incident.root_cause.evidence_refs && incident.root_cause.evidence_refs.length > 0 && (
                  <div>
                    <h4 className="text-xs font-mono text-gray-400 uppercase mb-2">Evidence References:</h4>
                    <div className="space-y-1.5 font-mono text-xs">
                      {incident.root_cause.evidence_refs.map((ref: string, idx: number) => (
                        <div key={idx} className="bg-black/60 p-2 rounded border border-white/5 text-purple-200">
                          <span className="text-amber-400 font-bold">&gt; </span> {ref}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Recommended Action Plan Box */}
            {incident.decision?.recommended_action && (
              <div className="glass-panel p-6 rounded-xl border border-white/10">
                <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
                  <h3 className="font-fraunces text-lg font-bold text-white flex items-center gap-2">
                    <Play className="w-5 h-5 text-emerald-400" />
                    <span>Remediation Action Plan</span>
                  </h3>
                  <span className="font-mono text-xs text-emerald-300 bg-emerald-950/80 px-2.5 py-1 rounded border border-emerald-500/30">
                    Plan ID: {incident.decision.recommended_action.id}
                  </span>
                </div>

                <p className="text-xs text-gray-300 mb-4">{incident.decision.recommended_action.description}</p>

                <div className="space-y-2 mb-4">
                  <h4 className="text-xs font-mono text-gray-400 uppercase">Execution Steps:</h4>
                  {incident.decision.recommended_action.steps.map((step, idx) => (
                    <div key={idx} className="bg-black/80 p-3 rounded font-mono text-xs text-emerald-400 border border-white/10 flex items-start gap-2">
                      <span className="text-gray-500">{idx + 1}.</span>
                      <code className="text-amber-300 flex-1">{step}</code>
                    </div>
                  ))}
                </div>

                {incident.decision.recommended_action.rollback_plan && (
                  <div className="bg-purple-950/40 p-3 rounded border border-purple-500/20 text-xs font-mono">
                    <span className="text-purple-300 font-bold uppercase block mb-1">Automated Rollback Safeguard:</span>
                    <span className="text-gray-300">{incident.decision.recommended_action.rollback_plan}</span>
                  </div>
                )}
              </div>
            )}

            {/* Verification Probes */}
            {incident.verification && (
              <div className="glass-panel p-6 rounded-xl border border-white/10">
                <h3 className="font-fraunces text-lg font-bold text-white mb-3 flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-purple-400" />
                  <span>Post-Remediation Verification Probes</span>
                </h3>
                <div className="space-y-2 font-mono text-xs">
                  {incident.verification.checks.map((chk, idx) => (
                    <div key={idx} className="flex items-center justify-between bg-black/50 p-3 rounded border border-white/5">
                      <span className="text-gray-300">{chk.name}</span>
                      <span className={`px-2 py-0.5 rounded font-bold ${chk.result === 'pass' ? 'bg-emerald-950 text-emerald-300 border border-emerald-500/30' : 'bg-red-950 text-red-300'}`}>
                        {chk.result.toUpperCase()}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right Column: OPA Policy Matrix & Impact Topology */}
          <div className="space-y-6">
            {/* OPA Policy Decision Matrix */}
            {incident.decision && (
              <div className="glass-panel p-6 rounded-xl border border-white/10">
                <h3 className="font-fraunces text-base font-bold text-white mb-4 flex items-center gap-2 pb-2 border-b border-white/10">
                  <Lock className="w-4 h-4 text-amber-400" />
                  <span>OPA Policy Risk Matrix</span>
                </h3>

                <div className="space-y-3 font-mono text-xs">
                  <div className="flex justify-between py-1.5 border-b border-white/5">
                    <span className="text-gray-400">Risk Tier:</span>
                    <span className="text-amber-400 font-bold uppercase">{incident.decision.risk_tier}</span>
                  </div>
                  <div className="flex justify-between py-1.5 border-b border-white/5">
                    <span className="text-gray-400">Requires Approval:</span>
                    <span className={incident.decision.requires_approval ? 'text-amber-400 font-bold' : 'text-emerald-400'}>
                      {incident.decision.requires_approval ? 'YES (Policy Locked)' : 'NO (Auto)'}
                    </span>
                  </div>
                  <div className="flex justify-between py-1.5 border-b border-white/5">
                    <span className="text-gray-400">Policy Rules Evaluated:</span>
                    <span className="text-purple-300">approval_rules.rego</span>
                  </div>
                </div>

                <div className="mt-4 p-3 bg-black/60 rounded border border-white/10 text-[11px] font-mono text-gray-400">
                  <span className="text-amber-400 font-bold block mb-1">OPA Evaluation Log:</span>
                  &quot;action_type=restart_pod on critical service requires approver role&quot;
                </div>
              </div>
            )}

            {/* Impact Topology / Blast Radius */}
            {incident.impact && (
              <div className="glass-panel p-6 rounded-xl border border-white/10">
                <h3 className="font-fraunces text-base font-bold text-white mb-3 flex items-center gap-2 pb-2 border-b border-white/10">
                  <Layers className="w-4 h-4 text-purple-400" />
                  <span>Impact Blast Radius</span>
                </h3>

                <div className="space-y-2 font-mono text-xs">
                  <p className="text-gray-400">Calculated Topology Nodes:</p>
                  {incident.impact.blast_radius.map((srv, idx) => (
                    <div key={idx} className="flex items-center space-x-2 bg-black/50 p-2.5 rounded border border-white/5 text-purple-200">
                      <span className="w-2 h-2 rounded-full bg-purple-400" />
                      <span>{srv}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Action Modals */}
      <ActionModals
        incidentId={incident.id}
        actionId={incident.decision?.recommended_action.id || 'act-001'}
        currentPlan={incident.decision?.recommended_action}
        showApprove={showApproveModal}
        showReject={showRejectModal}
        showModify={showModifyModal}
        onClose={() => {
          setShowApproveModal(false);
          setShowRejectModal(false);
          setShowModifyModal(false);
        }}
        onSuccess={() => {
          setShowApproveModal(false);
          setShowRejectModal(false);
          setShowModifyModal(false);
          fetchIncidentDetail();
        }}
      />
    </div>
  );
}
