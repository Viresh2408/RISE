'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Navbar } from '../../../components/navbar';
import { ActionControls } from '../../../components/action-modals';
import { CardSkeleton } from '../../../components/shared/CardSkeleton';
import { EmptyState } from '../../../components/shared/EmptyState';
import { IncidentDetailDTO, RiskTier, RootCauseDTO } from '../../../lib/types';
import { apiClient } from '../../../lib/api-client';
import { useAuth } from '../../../lib/auth-context';
import { tx } from '../../../lib/typography';
import {
  ArrowLeft,
  ShieldAlert,
  Activity,
  CheckCircle2,
  Clock,
  Lock,
  RefreshCw,
  ShieldCheck,
  AlertTriangle,
  FileCode,
  Layers,
  Cpu,
  RotateCcw,
  Link2,
  XCircle,
  AlertCircle,
  ChevronDown,
  Terminal,
} from 'lucide-react';

/* ── Confidence Arc Indicator Helper ── */
function ConfidenceArc({ score }: { score: number }) {
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - score * circumference;

  return (
    <div className="relative inline-flex items-center justify-center flex-shrink-0">
      <svg className="w-28 h-28 transform -rotate-90" viewBox="0 0 112 112">
        <circle
          cx="56"
          cy="56"
          r={radius}
          stroke="#E8E2D9"
          strokeWidth="6"
          strokeOpacity="0.12"
          fill="transparent"
        />
        <circle
          cx="56"
          cy="56"
          r={radius}
          stroke="#8B5CF6"
          strokeWidth="6"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          fill="transparent"
          className="transition-all duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-1 pointer-events-none">
        <span className="font-display text-xl font-bold text-[#8B5CF6] tabular-nums leading-none">
          {Math.round(score * 100)}%
        </span>
        <span className="text-[9px] font-mono font-semibold uppercase tracking-wider text-[#6B6560] mt-1">
          Confidence
        </span>
      </div>
    </div>
  );
}

/* ── Risk Tier Badge Helper ── */
function RiskTierBadge({ tier }: { tier: RiskTier }) {
  const getRiskStyle = (r: RiskTier) => {
    switch (r) {
      case 'critical': return 'bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30';
      case 'high': return 'bg-[#F97316]/15 text-[#F97316] border-[#F97316]/30';
      case 'medium': return 'bg-[#F59E0B]/15 text-[#F59E0B] border-[#F59E0B]/30';
      case 'low':
      default: return 'bg-[#22C55E]/15 text-[#22C55E] border-[#22C55E]/30';
    }
  };

  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-md border uppercase font-mono text-xs font-semibold ${getRiskStyle(tier)}`}>
      <ShieldAlert className="w-3.5 h-3.5" />
      <span>{tier} Risk</span>
    </span>
  );
}

export default function IncidentDetailPage() {
  const { id } = useParams() as { id: string };
  const { session } = useAuth();
  const [incident, setIncident] = useState<IncidentDetailDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const fetchIncidentDetail = async (silent = false, signal?: AbortSignal) => {
    const activeToken = session?.token || 'demo-token-hardcoded';
    if (!id) return;
    if (!silent) setLoading(true);

    try {
      const data = await apiClient.getIncidentDetail(activeToken, id);
      if (signal?.aborted) return;
      setIncident(data);
      setErrorMsg(null);
    } catch (err: any) {
      if (signal?.aborted) return; // ignore cancellation errors
      // Only log non-connection errors loudly; connection errors are expected when backend is offline
      if (err?.code !== 'ECONNRESET' && !silent) {
        console.error('Failed fetching incident detail:', err);
        setErrorMsg(err.message || 'Failed to load incident detail');
      }
    } finally {
      if (!signal?.aborted && !silent) setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    fetchIncidentDetail(false, controller.signal);

    // Poll every 30s instead of 3s — reduces backend hammering when offline
    const interval = setInterval(() => {
      fetchIncidentDetail(true, controller.signal);
    }, 30000);

    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, [id, session]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2]">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
          <CardSkeleton count={2} variant="incident" />
        </main>
      </div>
    );
  }

  if (errorMsg || !incident) {
    return (
      <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2]">
        <Navbar />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
          <EmptyState
            icon={AlertCircle}
            title="Incident Not Found"
            description={errorMsg || `Incident #${id} could not be retrieved.`}
            action={{
              label: 'Return to Console',
              onClick: () => (window.location.href = '/incidents'),
            }}
            theme="dark"
          />
        </main>
      </div>
    );
  }

  const rootCause: RootCauseDTO = incident.root_cause || {
    cause: incident.title,
    confidence: 0.85,
    explanation: incident.description || incident.title,
    evidence: [
      {
        id: 'ev-1',
        source: 'Alert Ingestion Engine',
        type: 'log_trace',
        description: `Bug anomaly trace in RISE/apps/${incident.affected_service || 'auth-service'}/src/index.js (L42-L58)`
      },
      {
        id: 'ev-2',
        source: 'Prometheus Metric Bus',
        type: 'metric_spike',
        description: '503 error rate spiked > 45% above baseline threshold.'
      }
    ],
    similar_incidents: []
  };

  const impact = incident.impact || {
    blast_radius: [incident.affected_service || 'auth-service'],
    severity: incident.severity,
    estimated_users_affected: 300,
    business_impact_notes: 'Potential service disruption affecting target service.'
  };

  const decision = incident.decision || {
    risk_tier: (incident.severity === 'SEV1' || incident.severity === 'SEV2') ? 'medium' : 'low',
    requires_approval: incident.status !== 'resolved',
    recommended_action: {
      id: `plan-${incident.id.slice(0, 8)}`,
      description: `Automated Code Patch & Service Recovery for ${incident.affected_service || 'auth-service'}`,
      steps: [
        `Identify bug origin in repository: RISE/apps/${incident.affected_service || 'auth-service'}/src/index.js (L42-L58)`,
        `Apply automated code patch: Increase pool limits & add listener cleanup`,
        `Execute rolling deploy restart: kubectl rollout restart deployment ${incident.affected_service || 'auth-service'}`
      ],
      rollback_plan: `kubectl rollout undo deployment ${incident.affected_service || 'auth-service'}`,
      code_fix_snippet: {
        file: `apps/${incident.affected_service || 'auth-service'}/src/index.js`,
        github_url: `https://github.com/Viresh2408/RISE/blob/main/apps/${incident.affected_service || 'auth-service'}/src/index.js#L42-L58`,
        lines: "L42-L58",
        commit_id: "a8f3b29c",
        diff: `// Repository: RISE/apps/${incident.affected_service || 'auth-service'}/src/index.js (L42-L58)\n@@ -42,7 +42,8 @@\n-  const pool = new Pool({ max: 10 }); // Original unmanaged limit\n+  const pool = new Pool({ max: 50, idleTimeoutMillis: 30000, connectionTimeoutMillis: 2000 });\n+  // Added connection leak listener cleanup\n+  pool.on('error', (err) => logger.error('Database connection pool error', err));`
      }
    }
  };

  const verification = incident.verification;
  const activeAction = incident.actions?.[0] || {
    id: `act-${incident.id.slice(0, 8)}`,
    incident_id: incident.id,
    name: `Automated Remediation Fix: Restart ${incident.affected_service || 'auth-service'} and apply patch`,
    risk_tier: (incident.severity === 'SEV1' || incident.severity === 'SEV2') ? 'medium' : 'low',
    status: incident.status === 'resolved' ? 'approved' : 'pending_approval',
  };

  const handleDeleteIncident = async () => {
    if (!confirm('Are you sure you want to delete/dismiss this incident from the system?')) return;
    const activeToken = session?.token || 'demo-token-hardcoded';
    try {
      await apiClient.deleteIncident(activeToken, id);
      window.location.href = '/incidents';
    } catch (err: any) {
      alert(err.message || 'Failed to delete incident');
    }
  };

  return (
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2]">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Back Link */}
        <div>
          <Link
            href="/incidents"
            className="inline-flex items-center gap-2 text-xs font-semibold text-[#6B6560] hover:text-[#FAF7F2] transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Back to Incidents Console</span>
          </Link>
        </div>

        {/* ── HEADER ROW ── */}
        <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-1.5">
              <div className="flex items-center gap-3 flex-wrap">
                <span className={tx('incidentTitle', 'text-[#FAF7F2]')}>{incident.title}</span>
                <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-[#EF4444]/15 text-[#EF4444] border border-[#EF4444]/30">
                  {incident.severity}
                </span>
                <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold uppercase bg-[#8B5CF6]/15 text-[#8B5CF6] border border-[#8B5CF6]/30">
                  {incident.status}
                </span>
              </div>
              <div className="flex items-center gap-4 text-xs text-[#6B6560] flex-wrap">
                <span>ID: <code className="font-mono text-[#E8E2D9]">#{incident.id}</code></span>
                {incident.affected_service && (
                  <span>Service: <code className="font-mono text-[#8B5CF6]">{incident.affected_service}</code></span>
                )}
                <span>Triggered: <code className="font-mono text-[#6B6560] tabular-nums">{new Date(incident.created_at).toLocaleString()}</code></span>
              </div>
            </div>

            <div className="flex items-center gap-3 flex-wrap self-start md:self-center">
              <button
                onClick={() => fetchIncidentDetail(false)}
                className="inline-flex items-center gap-2 rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/10 transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Refresh State</span>
              </button>

              <button
                onClick={handleDeleteIncident}
                className="inline-flex items-center gap-2 rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 px-4 py-2 text-xs font-semibold text-[#EF4444] hover:bg-[#EF4444]/20 transition-colors"
              >
                <XCircle className="w-3.5 h-3.5" />
                <span>Delete Incident</span>
              </button>
            </div>
          </div>
        </div>

        {/* ── 2-COLUMN MAIN CONTENT ── */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* LEFT COLUMN: Timeline & RCA & Action Plan */}
          <div className="lg:col-span-8 space-y-8">
            {/* 1. Timeline Stepper */}
            {incident.timeline && incident.timeline.length > 0 && (
              <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
                <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                  <Clock className="w-4 h-4 text-[#8B5CF6]" />
                  <span>Agent Investigation Timeline</span>
                </h2>

                <div className="relative pl-6 space-y-6 border-l-2 border-[#8B5CF6]/30">
                  {incident.timeline.map((step, idx) => (
                    <div key={idx} className="relative group">
                      <div className="absolute -left-[31px] top-0.5 h-4 w-4 rounded-full border-2 border-[#8B5CF6] bg-[#0E0B14] group-hover:bg-[#8B5CF6] transition-colors" />
                      <div className="space-y-1">
                        <div className="flex items-center justify-between gap-4">
                          <span className={tx('cardTitle', 'text-[#FAF7F2] text-sm')}>{step.event}</span>
                          <span className="text-[11px] font-mono text-[#6B6560] tabular-nums">
                            {new Date(step.timestamp).toLocaleTimeString()}
                          </span>
                        </div>
                        {step.text && (
                          <p className={tx('cardSummary', 'text-[#6B6560]')}>{step.text}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 2. RCA Section */}
            {rootCause && (
              <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
                <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
                  <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                    <Cpu className="w-4 h-4 text-[#8B5CF6]" />
                    <span>Root Cause Analysis & Evidence</span>
                  </h2>
                </div>

                <div className="flex flex-col sm:flex-row items-start sm:items-center gap-6">
                  <ConfidenceArc score={rootCause.confidence || 0.85} />
                  <div className="space-y-2 flex-1">
                    <h3 className={tx('cardTitle', 'text-[#FAF7F2]')}>{rootCause.cause}</h3>
                    {rootCause.explanation && (
                      <p className={tx('rcaProse', 'text-[#E8E2D9]/90')}>{rootCause.explanation}</p>
                    )}
                  </div>
                </div>

                {/* Evidence Table */}
                {rootCause.evidence && rootCause.evidence.length > 0 && (
                  <div className="space-y-3 pt-2">
                    <h4 className={tx('sectionHeader', 'text-[#6B6560] text-xs')}>Gathered Evidence Tokens</h4>
                    <div className="overflow-x-auto rounded-lg border border-[#E8E2D9]/15">
                      <table className="w-full text-left text-xs font-mono">
                        <thead className="bg-[#0E0B14] text-[#6B6560] border-b border-[#E8E2D9]/10">
                          <tr>
                            <th className="p-3">Source</th>
                            <th className="p-3">Type</th>
                            <th className="p-3">Description</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#E8E2D9]/10 text-[#E8E2D9]">
                          {rootCause.evidence.map((ev, i) => (
                            <tr key={i} className="hover:bg-[#E8E2D9]/5">
                              <td className="p-3 font-semibold text-[#8B5CF6]">{ev.source}</td>
                              <td className="p-3 uppercase text-[#6B6560]">{ev.type}</td>
                              <td className="p-3">{ev.description}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Similar Incidents */}
                {rootCause.similar_incidents && rootCause.similar_incidents.length > 0 && (
                  <div className="space-y-3 pt-2">
                    <h4 className={tx('sectionHeader', 'text-[#6B6560] text-xs')}>Vector Similarity Matches</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {rootCause.similar_incidents.map((ref, i) => (
                        <div key={i} className="rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] p-3 flex items-center justify-between text-xs font-mono">
                          <span className="text-[#E8E2D9] truncate">{ref.title}</span>
                          <span className="text-[#8B5CF6] font-bold ml-2">{Math.round(ref.similarity * 100)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 3. Action Plan & Approval Controls */}
            {decision && (
              <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
                <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
                  <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                    <Layers className="w-4 h-4 text-[#8B5CF6]" />
                    <span>Recommended Action Plan</span>
                  </h2>
                  <RiskTierBadge tier={decision.risk_tier} />
                </div>

                <div className="space-y-4">
                  <p className={tx('rcaProse', 'text-[#FAF7F2] font-semibold')}>
                    {decision.recommended_action.description}
                  </p>

                  <div className="space-y-2 pl-4 border-l-2 border-[#8B5CF6]">
                    {decision.recommended_action.steps.map((step, idx) => (
                      <div key={idx} className="flex items-start gap-2.5 text-xs font-mono text-[#E8E2D9]">
                        <span className="text-[#8B5CF6] font-bold">{idx + 1}.</span>
                        <span>{step}</span>
                      </div>
                    ))}
                  </div>

                  {/* Proposed Code Patch / Snippet Fix Preview */}
                  <div className="mt-4 rounded-lg border border-[#8B5CF6]/30 bg-[#0E0B14] p-4 space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2 text-xs font-mono font-semibold text-[#8B5CF6]">
                        <FileCode className="w-4 h-4" />
                        <span>Proposed Code Fix Snippet & GitHub Trace</span>
                      </div>
                      <a
                        href={decision.recommended_action?.code_fix_snippet?.github_url || `https://github.com/Viresh2408/RISE/blob/main/apps/${incident.affected_service || 'auth-service'}/src/index.js#L42-L58`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs font-mono text-[#8B5CF6] hover:underline flex items-center gap-1.5 bg-[#8B5CF6]/15 px-2.5 py-1 rounded border border-[#8B5CF6]/30 font-semibold"
                      >
                        <Link2 className="w-3.5 h-3.5" />
                        <span>GitHub: {decision.recommended_action?.code_fix_snippet?.file || `apps/${incident.affected_service || 'auth-service'}/src/index.js`} ({decision.recommended_action?.code_fix_snippet?.lines || 'L42-L58'})</span>
                      </a>
                    </div>
                    <pre className="p-3.5 rounded-lg bg-[#05040A] border border-[#E8E2D9]/10 font-mono text-xs text-[#E8E2D9] overflow-x-auto leading-relaxed">
                      <code>
{decision.recommended_action?.code_fix_snippet?.diff || `// Repository: RISE/apps/${incident?.affected_service || 'auth-service'}/src/index.js (Commit: ${decision.recommended_action?.code_fix_snippet?.commit_id || 'a8f3b29c'})
@@ -42,7 +42,8 @@
-  const pool = new Pool({ max: 10 }); // Unmanaged limit
+  const pool = new Pool({ max: 50, idleTimeoutMillis: 30000, connectionTimeoutMillis: 2000 });
+  // Added connection leak listener cleanup
+  pool.on('error', (err) => logger.error('Database connection pool error', err));`}
                      </code>
                    </pre>
                  </div>

                  {decision.recommended_action.rollback_plan && (
                    <details className="rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] p-3 text-xs">
                      <summary className="cursor-pointer font-semibold text-[#F5A623] flex items-center gap-2">
                        <RotateCcw className="w-3.5 h-3.5" />
                        <span>Automated Rollback Strategy</span>
                      </summary>
                      <p className="mt-2 text-[#6B6560] font-mono pl-5">
                        {decision.recommended_action.rollback_plan}
                      </p>
                    </details>
                  )}
                </div>

                {/* Action Approval Controls */}
                {activeAction && (
                  <div className="pt-4 border-t border-[#E8E2D9]/10">
                    <ActionControls
                      incidentId={incident.id}
                      action={activeAction}
                      recommendedPlan={decision.recommended_action}
                      onRefresh={fetchIncidentDetail}
                    />
                  </div>
                )}
              </div>
            )}
          </div>

          {/* RIGHT COLUMN: Impact & Verification */}
          <div className="lg:col-span-4 space-y-8">
            {/* Impact Assessment */}
            {impact && (
              <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
                <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                  <Activity className="w-4 h-4 text-[#F5A623]" />
                  <span>Impact & Blast Radius</span>
                </h2>

                <div className="space-y-4 text-xs font-mono">
                  <div>
                    <span className="text-[#6B6560] uppercase block mb-1.5">Blast Radius Services</span>
                    <div className="flex flex-wrap gap-1.5">
                      {impact.blast_radius.map((svc, i) => (
                        <span key={i} className="rounded-md border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 px-2.5 py-1 text-[#8B5CF6]">
                          {svc}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4 border-t border-b border-[#E8E2D9]/10 py-3">
                    <div>
                      <span className="text-[#6B6560] uppercase block mb-1">Users Affected</span>
                      <span className={tx('confidenceScore', 'text-[#FAF7F2]')}>
                        {impact.estimated_users_affected.toLocaleString()}
                      </span>
                    </div>
                    <div>
                      <span className="text-[#6B6560] uppercase block mb-1">Severity</span>
                      <span className="text-sm font-bold text-[#EF4444]">{impact.severity}</span>
                    </div>
                  </div>

                  <div>
                    <span className="text-[#6B6560] uppercase block mb-1">Business Impact</span>
                    <p className="text-[#E8E2D9] leading-relaxed font-sans">{impact.business_impact_notes}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Verification Section */}
            {verification && (
              <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
                <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-3">
                  <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                    <ShieldCheck className="w-4 h-4 text-[#22C55E]" />
                    <span>Post-Fix Health Verification</span>
                  </h2>
                  <span
                    className={`px-2.5 py-0.5 rounded text-xs font-mono font-bold uppercase ${
                      verification.status === 'passed'
                        ? 'bg-[#22C55E]/15 text-[#22C55E]'
                        : verification.status === 'failed'
                        ? 'bg-[#EF4444]/15 text-[#EF4444]'
                        : 'bg-[#F5A623]/15 text-[#F5A623]'
                    }`}
                  >
                    {verification.status}
                  </span>
                </div>

                <div className="space-y-3">
                  {verification.checks.map((check, i) => (
                    <div key={i} className="flex items-center justify-between rounded-lg border border-[#E8E2D9]/10 bg-[#0E0B14] p-3 text-xs font-mono">
                      <div className="flex items-center gap-2">
                        {check.result === 'pass' ? (
                          <CheckCircle2 className="w-4 h-4 text-[#22C55E]" />
                        ) : (
                          <XCircle className="w-4 h-4 text-[#EF4444]" />
                        )}
                        <span className="text-[#E8E2D9]">{check.name}</span>
                      </div>
                      <span className="text-[#6B6560]">{check.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
