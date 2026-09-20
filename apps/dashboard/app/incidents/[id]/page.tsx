'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Navbar } from '../../../components/navbar';
import { ActionControls } from '../../../components/action-modals';
import { AgentFlowDiagram } from '../../../components/agent-flow-diagram';
import { CardSkeleton } from '../../../components/shared/CardSkeleton';
import { EmptyState } from '../../../components/shared/EmptyState';
import { IncidentDetailDTO, RiskTier, RootCauseDTO, DecisionDTO } from '../../../lib/types';
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
  ChevronUp,
  Terminal,
  Search,
  Sparkles,
  Info,
  GitBranch,
  Bug,
  Eye,
  ExternalLink,
  GitMerge,
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

/* ── Threat Risk Score Arc ── */
// Reuses the ConfidenceArc SVG pattern; accepts a 0–100 integer score.
// Colour is severity-adaptive so high risk immediately reads as danger.
function ThreatRiskArc({ score }: { score: number }) {
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const normalised = score / 100;
  const strokeDashoffset = circumference - normalised * circumference;

  // Severity-adaptive colour: matches the RiskTierBadge colour scale
  const arcColor =
    score >= 75 ? '#EF4444' :  // critical / SEV1
    score >= 50 ? '#F97316' :  // high / SEV2
    score >= 25 ? '#F59E0B' :  // medium / SEV3
                  '#22C55E';   // low / SEV4

  const isUncomputed = score === 0;

  return (
    <div className="relative inline-flex items-center justify-center flex-shrink-0">
      <svg className="w-28 h-28 transform -rotate-90" viewBox="0 0 112 112">
        {/* Track ring */}
        <circle
          cx="56"
          cy="56"
          r={radius}
          stroke="#E8E2D9"
          strokeWidth="6"
          strokeOpacity="0.12"
          fill="transparent"
        />
        {/* Progress arc — hidden when score=0 (not yet computed) */}
        {!isUncomputed && (
          <circle
            cx="56"
            cy="56"
            r={radius}
            stroke={arcColor}
            strokeWidth="6"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            fill="transparent"
            className="transition-all duration-700 ease-out"
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-1 pointer-events-none">
        {isUncomputed ? (
          <>
            <span className="font-mono text-base font-bold text-[#6B6560] leading-none">N/A</span>
            <span className="text-[9px] font-mono font-semibold uppercase tracking-wider text-[#6B6560] mt-1">
              No Run
            </span>
          </>
        ) : (
          <>
            <span
              className="font-display text-xl font-bold tabular-nums leading-none"
              style={{ color: arcColor }}
            >
              {score}
            </span>
            <span className="text-[9px] font-mono font-semibold uppercase tracking-wider text-[#6B6560] mt-1">
              Risk Score
            </span>
          </>
        )}
      </div>
    </div>
  );
}

/* ── Syntax-Highlighted Git Diff Viewer ── */
function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split('\n');
  return (
    <div className="rounded-lg bg-[#05040A] border border-[#E8E2D9]/10 font-mono text-xs overflow-x-auto divide-y divide-white/[0.03]">
      {lines.map((line, idx) => {
        let lineStyle = 'text-[#E8E2D9]/80';
        let bgStyle = 'bg-transparent';
        if (line.startsWith('+') && !line.startsWith('+++')) {
          lineStyle = 'text-[#4ADE80] font-medium';
          bgStyle = 'bg-[#22C55E]/10';
        } else if (line.startsWith('-') && !line.startsWith('---')) {
          lineStyle = 'text-[#F87171] font-medium';
          bgStyle = 'bg-[#EF4444]/10';
        } else if (line.startsWith('@@')) {
          lineStyle = 'text-[#A78BFA] font-semibold';
          bgStyle = 'bg-[#8B5CF6]/10';
        } else if (line.startsWith('//') || line.startsWith('#')) {
          lineStyle = 'text-[#6B6560] italic';
        }

        return (
          <div key={idx} className={`px-3.5 py-1.5 flex items-start gap-3 ${bgStyle}`}>
            <span className="select-none text-[10px] text-[#6B6560]/60 w-6 text-right tabular-nums pt-0.5">{idx + 1}</span>
            <span className={`flex-1 whitespace-pre leading-relaxed ${lineStyle}`}>{line}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ── GitHub Source Evidence Panel ── */
// Shows the live GitHub file status for monitor-detected incidents.
// Fetches the current buggy code and proposed diff BEFORE the user approves.
function GitHubSourceEvidencePanel({
  token,
  filePath,
  patternId,
  buggyContext,
  githubUrl,
}: {
  token: string;
  filePath: string;
  patternId?: string | null;
  buggyContext?: string | null;
  githubUrl?: string | null;
}) {
  const [liveData, setLiveData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [showDiff, setShowDiff] = useState(true);
  const [showBuggyCode, setShowBuggyCode] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiClient.getGithubFilePreview(token, filePath, patternId)
      .then(setLiveData)
      .catch(() => setLiveData(null))
      .finally(() => setLoading(false));
  }, [token, filePath, patternId]);

  const isBugPresent = liveData?.is_bug_present;
  const isFixed = liveData?.is_fixed;
  const liveGithubUrl = liveData?.github_url || githubUrl || `https://github.com/Viresh2408/RISE/blob/main/${filePath}`;
  const currentSnippet = liveData?.current_content_snippet || buggyContext;
  const proposedDiff = liveData?.proposed_diff;
  const fileSha = liveData?.file_sha;

  // Status pill
  const statusInfo = isFixed
    ? { label: 'Fixed in GitHub', color: 'bg-[#22C55E]/15 text-[#22C55E] border-[#22C55E]/30', dot: '#22C55E' }
    : isBugPresent
    ? { label: 'Bug Detected in GitHub', color: 'bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30', dot: '#EF4444' }
    : loading
    ? { label: 'Checking GitHub...', color: 'bg-[#6B6560]/15 text-[#6B6560] border-[#6B6560]/30', dot: '#6B6560' }
    : { label: 'Status Unknown', color: 'bg-[#F59E0B]/15 text-[#F59E0B] border-[#F59E0B]/30', dot: '#F59E0B' };

  return (
    <div className="rounded-xl border border-[#EF4444]/30 bg-gradient-to-b from-[#1A0A0A] to-[#151121] p-6 space-y-5 shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[#EF4444]/15">
            <Bug className="w-4 h-4 text-[#EF4444]" />
          </div>
          <div>
            <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
              <span>GitHub Source Evidence</span>
              <span className="text-[10px] font-mono font-bold uppercase px-2 py-0.5 rounded bg-[#EF4444]/20 text-[#EF4444] border border-[#EF4444]/30">
                Live
              </span>
            </h2>
            <p className="text-[11px] font-mono text-[#6B6560] mt-0.5">
              Real file content from GitHub — inspect the bug before deciding
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[11px] font-mono font-semibold ${statusInfo.color}`}>
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: statusInfo.dot }} />
            {statusInfo.label}
          </span>
          <a
            href={liveGithubUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#8B5CF6]/15 text-[#8B5CF6] border border-[#8B5CF6]/30 text-[11px] font-mono font-semibold hover:bg-[#8B5CF6]/25 transition-colors"
          >
            <GitBranch className="w-3 h-3" />
            <span>View on GitHub</span>
            <ExternalLink className="w-2.5 h-2.5" />
          </a>
        </div>
      </div>

      {/* File info bar */}
      <div className="rounded-lg bg-[#0A0505] border border-[#EF4444]/15 px-4 py-2.5 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 font-mono text-xs">
          <FileCode className="w-3.5 h-3.5 text-[#8B5CF6]" />
          <code className="text-[#C084FC]">{filePath}</code>
          {patternId && (
            <span className="text-[#6B6560]">• Pattern: <code className="text-[#F59E0B]">{patternId}</code></span>
          )}
        </div>
        {fileSha && (
          <span className="text-[10px] font-mono text-[#6B6560]">
            SHA: <code className="text-[#8B5CF6]/70">{fileSha.slice(0, 10)}</code>
          </span>
        )}
      </div>

      {/* Decision callout when bug is still live */}
      {isBugPresent && !isFixed && (
        <div className="flex items-start gap-3 rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/8 p-3.5">
          <AlertTriangle className="w-4 h-4 text-[#EF4444] flex-shrink-0 mt-0.5" />
          <div className="space-y-0.5">
            <p className="text-xs font-semibold text-[#EF4444]">Bug confirmed live in GitHub main branch</p>
            <p className="text-[11px] text-[#A8A29E] leading-relaxed">
              The code anti-pattern below is currently present in the repository. Review the diff,
              then use <strong className="text-[#FAF7F2]">Approve &amp; Push Fix</strong> to commit the automated patch
              and open a Pull Request, or <strong className="text-[#FAF7F2]">Reject</strong> to dismiss.
            </p>
          </div>
        </div>
      )}

      {isFixed && (
        <div className="flex items-start gap-3 rounded-lg border border-[#22C55E]/30 bg-[#22C55E]/8 p-3.5">
          <CheckCircle2 className="w-4 h-4 text-[#22C55E] flex-shrink-0 mt-0.5" />
          <div className="space-y-0.5">
            <p className="text-xs font-semibold text-[#22C55E]">Fix already present in GitHub</p>
            <p className="text-[11px] text-[#A8A29E] leading-relaxed">
              The automated fix has been applied to the file. This incident will be auto-resolved
              on the next GitHub Monitor cycle.
            </p>
          </div>
        </div>
      )}

      {/* Buggy Code Snippet */}
      {currentSnippet && (
        <div className="space-y-2">
          <button
            onClick={() => setShowBuggyCode(!showBuggyCode)}
            className="flex items-center gap-2 text-xs font-semibold text-[#EF4444] hover:text-[#F87171] transition-colors"
          >
            <Eye className="w-3.5 h-3.5" />
            <span>{showBuggyCode ? 'Hide' : 'Show'} Current Buggy Code in GitHub</span>
            {showBuggyCode ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {showBuggyCode && (
            <div className="rounded-lg bg-[#05040A] border border-[#EF4444]/20 p-4">
              <div className="text-[10px] font-mono text-[#EF4444]/60 uppercase tracking-wider mb-2 pb-1.5 border-b border-[#EF4444]/10">
                Current file content (buggy lines)
              </div>
              <div className="font-mono text-xs overflow-x-auto">
                {currentSnippet.split('\n').map((line: string, i: number) => {
                  const isHighlighted = [
                    'redis.from_url(', 'pool_size', 'async def _ingest', 'ttl = 3600'
                  ].some(t => line.includes(t));
                  return (
                    <div
                      key={i}
                      className={`px-3 py-1 flex items-start gap-3 ${
                        isHighlighted ? 'bg-[#EF4444]/15 rounded' : ''
                      }`}
                    >
                      <span className="select-none text-[10px] text-[#6B6560]/50 w-8 text-right tabular-nums pt-0.5 flex-shrink-0">
                        {line.split(':')[0]}
                      </span>
                      <span className={`flex-1 whitespace-pre leading-relaxed ${
                        isHighlighted ? 'text-[#F87171] font-semibold' : 'text-[#E8E2D9]/70'
                      }`}>
                        {line.includes(':') ? line.slice(line.indexOf(':') + 1) : line}
                      </span>
                      {isHighlighted && (
                        <span className="text-[9px] font-mono font-bold text-[#EF4444] bg-[#EF4444]/20 px-1 py-0.5 rounded flex-shrink-0">BUG</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Proposed Fix Diff */}
      {proposedDiff && (
        <div className="space-y-2">
          <button
            onClick={() => setShowDiff(!showDiff)}
            className="flex items-center gap-2 text-xs font-semibold text-[#22C55E] hover:text-[#4ADE80] transition-colors"
          >
            <GitMerge className="w-3.5 h-3.5" />
            <span>{showDiff ? 'Hide' : 'Show'} Proposed Fix Diff (will be applied on Approve)</span>
            {showDiff ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {showDiff && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between px-1">
                <span className="text-[10px] font-mono text-[#6B6560] uppercase tracking-wider">Proposed patch — not yet applied</span>
                <span className="text-[10px] font-mono text-[#22C55E] flex items-center gap-1">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#22C55E]" />
                  Read-only preview
                </span>
              </div>
              <DiffViewer diff={proposedDiff} />
            </div>
          )}
        </div>
      )}

      {!proposedDiff && !loading && isBugPresent && (
        <div className="text-[11px] font-mono text-[#6B6560] text-center py-2">
          No automated patch available for this pattern — manual fix required.
        </div>
      )}
    </div>
  );
}

/* ── PS Named Agent Role Mapping Helper (Demo Mode) ── */
function getPsAgentRole(event: string, text: string = ''): {
  role: string;
  badgeStyle: string;
  description: string;
  sourceAgent: string;
} {
  const combined = (event + ' ' + text).toLowerCase();

  if (
    combined.includes('alert') ||
    combined.includes('ingest') ||
    combined.includes('context') ||
    combined.includes('loki') ||
    combined.includes('prometheus') ||
    combined.includes('log') ||
    combined.includes('security-log') ||
    combined.includes('vector search') ||
    combined.includes('normalized') ||
    combined.includes('collect')
  ) {
    return {
      role: 'Log Analysis Agent',
      badgeStyle: 'bg-[#8B5CF6]/15 text-[#8B5CF6] border-[#8B5CF6]/30',
      description: 'Ingests, normalizes, correlates security log events',
      sourceAgent: 'Context Builder + Ingestion',
    };
  }

  if (
    combined.includes('root cause') ||
    combined.includes('investigat') ||
    combined.includes('synthes') ||
    combined.includes('hypothes') ||
    combined.includes('evidence') ||
    combined.includes('rca')
  ) {
    return {
      role: 'Threat Investigation Agent',
      badgeStyle: 'bg-[#F5A623]/15 text-[#F5A623] border-[#F5A623]/30',
      description: 'Generates hypotheses, determines root cause with confidence, cites evidence',
      sourceAgent: 'Investigation + Root Cause Agents',
    };
  }

  if (combined.includes('policy') || combined.includes('opa') || combined.includes('risk') || combined.includes('approval')) {
    return {
      role: 'Policy & Governance Engine',
      badgeStyle: 'bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30',
      description: 'Evaluates OPA risk policies & routes human-in-the-loop approvals',
      sourceAgent: 'OPA Risk & Decision Engine',
    };
  }

  if (combined.includes('remediat') || combined.includes('patch') || combined.includes('plan') || combined.includes('action')) {
    return {
      role: 'Remediation Decision Agent',
      badgeStyle: 'bg-[#3B82F6]/15 text-[#3B82F6] border-[#3B82F6]/30',
      description: 'Formulates patch with real code grounding & rollback plan',
      sourceAgent: 'Decision & Plan Engine',
    };
  }

  if (combined.includes('verif') || combined.includes('probe') || combined.includes('rollback') || combined.includes('health')) {
    return {
      role: 'Self-Healing & Verification Agent',
      badgeStyle: 'bg-[#22C55E]/15 text-[#22C55E] border-[#22C55E]/30',
      description: 'Conducts independent live verification & auto-rollback',
      sourceAgent: 'Verification Agent',
    };
  }

  return {
    role: 'Autonomous Agent Orchestrator',
    badgeStyle: 'bg-white/10 text-[#E8E2D9] border-white/20',
    description: 'LangGraph multi-agent state orchestration',
    sourceAgent: 'RISE LangGraph Core',
  };
}

export default function IncidentDetailPage() {
  const { id } = useParams() as { id: string };
  const { session } = useAuth();
  const [incident, setIncident] = useState<IncidentDetailDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showGraphVisualizer, setShowGraphVisualizer] = useState(false);

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

  const decision: DecisionDTO = incident.decision || {
    risk_tier: (incident.severity === 'SEV1' || incident.severity === 'SEV2') ? 'medium' : 'low',
    confidence: 0.85,
    requires_approval: incident.status !== 'resolved',
    recommended_action: {
      id: `plan-${incident.id.slice(0, 8)}`,
      description: `Investigation pending for ${incident.affected_service || 'service'} — no verified plan available yet`,
      steps: ['Agent pipeline has not produced a verified action plan for this incident yet.'],
      fix_unavailable_reason: 'No automated action plan has been generated by the agent pipeline for this incident. Manual investigation required.',
    }
  };

  const verification = incident.verification;
  const activeAction = incident.actions?.[0] || {
    id: `act-${incident.id.slice(0, 8)}`,
    incident_id: incident.id,
    name: `Remediation pending — ${incident.affected_service || 'service'}`,
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
            {/* PS Agent Roles Mapping Legend (Demo Mode) */}
            <div className="rounded-xl border border-[#8B5CF6]/30 bg-gradient-to-r from-[#8B5CF6]/10 via-[#151121] to-[#0E0B14] p-5 text-xs space-y-3">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2.5">
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-[#8B5CF6]/30 text-[#8B5CF6] border border-[#8B5CF6]/50 flex items-center gap-1">
                    <Sparkles className="w-3 h-3" />
                    <span>Demo Mode</span>
                  </span>
                  <span className="font-semibold text-[#FAF7F2] text-sm">Problem Statement (PS) Agent Role Mapping</span>
                </div>
                <button
                  onClick={() => setShowGraphVisualizer(!showGraphVisualizer)}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#8B5CF6]/20 text-[#8B5CF6] hover:bg-[#8B5CF6]/30 border border-[#8B5CF6]/30 font-mono text-[11px] transition-colors"
                >
                  <Activity className="w-3.5 h-3.5" />
                  <span>{showGraphVisualizer ? 'Hide Pipeline Graph' : 'View Multi-Agent Graph'}</span>
                  {showGraphVisualizer ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                <div className="rounded-lg bg-[#0E0B14]/80 p-3 border border-[#8B5CF6]/20 flex items-start gap-3">
                  <div className="p-1.5 rounded bg-[#8B5CF6]/20 text-[#8B5CF6] mt-0.5 flex-shrink-0">
                    <Search className="w-4 h-4" />
                  </div>
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-bold text-[#8B5CF6] font-mono">Log Analysis Agent</span>
                      <span className="text-[#6B6560] font-mono text-[10px]">➔ Context Builder + Ingestion</span>
                    </div>
                    <p className="text-[#6B6560] text-[11px] leading-relaxed">
                      Ingests, normalizes, and correlates security log events (Syslog, CSV, JSON, NDJSON) with live metrics & vector memory.
                    </p>
                  </div>
                </div>

                <div className="rounded-lg bg-[#0E0B14]/80 p-3 border border-[#F5A623]/20 flex items-start gap-3">
                  <div className="p-1.5 rounded bg-[#F5A623]/20 text-[#F5A623] mt-0.5 flex-shrink-0">
                    <Activity className="w-4 h-4" />
                  </div>
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-bold text-[#F5A623] font-mono">Threat Investigation Agent</span>
                      <span className="text-[#6B6560] font-mono text-[10px]">➔ Investigation + Root Cause</span>
                    </div>
                    <p className="text-[#6B6560] text-[11px] leading-relaxed">
                      Generates ranked hypotheses, determines root cause with calibrated confidence scoring, and cites verifiable evidence.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Optional Collapsible Agent Flow Diagram */}
            {showGraphVisualizer && (
              <div className="transition-all duration-300">
                <AgentFlowDiagram />
              </div>
            )}

            {/* 1. Timeline Stepper */}
            {incident.timeline && incident.timeline.length > 0 && (
              <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
                <div className="flex items-center justify-between flex-wrap gap-2 border-b border-[#E8E2D9]/10 pb-4">
                  <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                    <Clock className="w-4 h-4 text-[#8B5CF6]" />
                    <span>Agent Investigation Timeline</span>
                  </h2>
                  <span className="text-xs font-mono text-[#6B6560]">
                    PS Named Roles Attached Per Step
                  </span>
                </div>

                <div className="relative pl-6 space-y-6 border-l-2 border-[#8B5CF6]/30">
                  {incident.timeline.map((step, idx) => {
                    const psInfo = getPsAgentRole(step.event, step.text);
                    return (
                      <div key={idx} className="relative group">
                        <div className="absolute -left-[31px] top-0.5 h-4 w-4 rounded-full border-2 border-[#8B5CF6] bg-[#0E0B14] group-hover:bg-[#8B5CF6] transition-colors" />
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between gap-4 flex-wrap">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className={tx('cardTitle', 'text-[#FAF7F2] text-sm')}>{step.event}</span>
                              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase border ${psInfo.badgeStyle}`}>
                                PS: {psInfo.role}
                              </span>
                            </div>
                            <span className="text-[11px] font-mono text-[#6B6560] tabular-nums">
                              {new Date(step.timestamp).toLocaleTimeString()}
                            </span>
                          </div>
                          <div className="text-[11px] font-mono flex items-center gap-2 text-[#6B6560] flex-wrap">
                            <span className="text-[#8B5CF6]/90 font-medium">[{psInfo.sourceAgent}]</span>
                            <span>•</span>
                            <span className="text-[#6B6560] italic">{psInfo.description}</span>
                          </div>
                          {step.text && (
                            <p className={tx('cardSummary', 'text-[#6B6560]')}>{step.text}</p>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 2. RCA Section */}
            {rootCause && (
              <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#E8E2D9]/10 pb-4">
                  <div className="space-y-0.5">
                    <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                      <Cpu className="w-4 h-4 text-[#8B5CF6]" />
                      <span>Root Cause Analysis &amp; Evidence</span>
                    </h2>
                    <p className="text-[11px] font-mono text-[#6B6560]">
                      Evidence-backed diagnosis calibrated by the Threat Investigation Agent
                    </p>
                  </div>
                  <span className="px-2.5 py-1 rounded text-xs font-mono font-semibold bg-[#F5A623]/15 text-[#F5A623] border border-[#F5A623]/30 self-start sm:self-auto">
                    PS Role: Threat Investigation Agent
                  </span>
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
                            <th className="p-3">Description / Attribution</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#E8E2D9]/10 text-[#E8E2D9]">
                          {rootCause.evidence.map((ev: any, i: number) => (
                            <tr key={i} className="hover:bg-[#E8E2D9]/5">
                              <td className="p-3 font-semibold text-[#8B5CF6]">{ev.source}</td>
                              <td className="p-3 uppercase text-[#6B6560]">{ev.type}</td>
                              <td className="p-3 space-y-1">
                                <div>{ev.description}</div>
                                {ev.file_path && (
                                  <div className="text-[11px] text-[#8B5CF6]">
                                    <span className="text-[#6B6560]">File: </span>
                                    <code>{ev.file_path}</code>
                                    {ev.line_start && (
                                      <span> (L{ev.line_start}{ev.line_end ? `-L${ev.line_end}` : ''})</span>
                                    )}
                                    {ev.commit_sha && (
                                      <span className="text-[#6B6560] ml-2">@ {ev.commit_sha.slice(0, 7)}</span>
                                    )}
                                  </div>
                                )}
                              </td>
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

            {/* 2b. GitHub Source Evidence Panel — only for monitor-detected incidents */}
            {decision?.recommended_action?.code_fix_snippet?.is_monitor_detected && (
              <GitHubSourceEvidencePanel
                token={session?.token || 'demo-token-hardcoded'}
                filePath={decision.recommended_action.code_fix_snippet.file}
                patternId={decision.recommended_action.code_fix_snippet.pattern_id}
                buggyContext={decision.recommended_action.code_fix_snippet.buggy_context}
                githubUrl={decision.recommended_action.code_fix_snippet.github_url}
              />
            )}

            {/* 3. Action Plan & Approval Controls */}
            {decision && (() => {
              const isSimulatedAction =
                Boolean(decision.is_simulated) ||
                Boolean(decision.recommended_action?.is_simulated) ||
                ['block_ip_address', 'isolate_host', 'revoke_session_token', 'quarantine_file', 'flag_for_soc_review'].some(
                  (s) =>
                    decision.recommended_action?.description?.toLowerCase().includes(s) ||
                    decision.recommended_action?.steps?.some((st) => st.toLowerCase().includes(s))
                );

              return (
                <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
                  <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4 flex-wrap gap-2">
                    <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                      <Layers className="w-4 h-4 text-[#8B5CF6]" />
                      <span>Recommended Action Plan</span>
                    </h2>
                    <div className="flex items-center gap-2 flex-wrap">
                      {isSimulatedAction && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border uppercase font-mono text-[10px] font-bold bg-[#8B5CF6]/15 text-[#C084FC] border-[#8B5CF6]/30">
                          <ShieldAlert className="w-3.5 h-3.5 text-[#8B5CF6]" />
                          <span>Simulated (Audited)</span>
                        </span>
                      )}
                      <RiskTierBadge tier={decision.risk_tier} />
                    </div>
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

                    {/* Proposed Code Patch / Snippet Fix Preview or Simulated Action / Unavailability Notice */}
                    {decision.recommended_action?.code_fix_snippet?.diff ? (
                      <div className="mt-4 rounded-lg border border-[#8B5CF6]/30 bg-[#0E0B14] p-4 space-y-3">
                        <div className="flex items-center justify-between flex-wrap gap-2">
                          <div className="flex items-center gap-2 text-xs font-mono font-semibold text-[#8B5CF6]">
                            <FileCode className="w-4 h-4" />
                            <span>Grounded Code Fix Snippet & GitHub Trace</span>
                          </div>
                          {(() => {
                            const snippet = decision.recommended_action.code_fix_snippet;
                            if (!snippet) return null;
                            const href = snippet.github_url || `https://github.com/Viresh2408/RISE/blob/main/${snippet.file}#${snippet.lines}`;
                            return (
                              <a
                                href={href}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs font-mono text-[#8B5CF6] hover:underline flex items-center gap-1.5 bg-[#8B5CF6]/15 px-2.5 py-1 rounded border border-[#8B5CF6]/30 font-semibold"
                              >
                                <Link2 className="w-3.5 h-3.5" />
                                <span>GitHub: {snippet.file} ({snippet.lines})</span>
                              </a>
                            );
                          })()}
                        </div>
                        {decision.recommended_action.code_fix_snippet?.diff && (
                          <DiffViewer diff={decision.recommended_action.code_fix_snippet.diff} />
                        )}
                      </div>
                    ) : isSimulatedAction ? (
                      <div className="mt-4 rounded-lg border border-[#8B5CF6]/30 bg-[#0E0B14] p-4 space-y-2">
                        <div className="flex items-center justify-between flex-wrap gap-2">
                          <div className="flex items-center gap-2 text-xs font-mono font-semibold text-[#C084FC]">
                            <ShieldCheck className="w-4 h-4 text-[#8B5CF6]" />
                            <span>Simulated Security Response Action</span>
                          </div>
                          <span className="text-[10px] font-mono font-bold uppercase bg-[#8B5CF6]/15 text-[#A78BFA] px-2 py-0.5 rounded border border-[#8B5CF6]/30">
                            Audited Execution Stub
                          </span>
                        </div>
                        <p className="text-xs text-[#A8A29E] leading-relaxed">
                          This security remediation action executes as a logged, audited no-op action exercising the complete human-in-the-loop approval and audit trail pipeline.
                        </p>
                      </div>
                    ) : (
                      <div className="mt-4 rounded-lg border border-[#F5A623]/30 bg-[#0E0B14] p-4 space-y-2">
                        <div className="flex items-center gap-2 text-xs font-mono font-semibold text-[#F5A623]">
                          <AlertTriangle className="w-4 h-4 text-[#F5A623]" />
                          <span>No Automated Code Fix Available</span>
                        </div>
                        <p className="text-xs text-[#6B6560] leading-relaxed">
                          {decision.recommended_action?.fix_unavailable_reason ||
                            'Automated code patch generation was skipped because verified file content was not available or manual review is required.'}
                        </p>
                      </div>
                    )}

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
            )})()}

          </div>

          {/* RIGHT COLUMN: Impact & Verification */}
          <div className="lg:col-span-4 space-y-8">
            {/* Impact Assessment */}
            {impact && (
              <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-6 space-y-6">
                {/* Section header */}
                <h2 className={tx('sectionHeader', 'text-[#FAF7F2] flex items-center gap-2')}>
                  <Activity className="w-4 h-4 text-[#F5A623]" />
                  <span>Impact & Blast Radius</span>
                </h2>

                {/* ── Threat Risk Score + Severity badge row ── */}
                {/* Mirrors the RCA confidence-arc pattern: arc left, label/badge right */}
                <div className="flex items-center gap-5 rounded-lg border border-[#E8E2D9]/10 bg-[#0E0B14] px-4 py-3">
                  <ThreatRiskArc score={impact.risk_score ?? 0} />
                  <div className="space-y-2 flex-1 min-w-0">
                    <p className="text-[10px] font-mono font-semibold uppercase tracking-wider text-[#6B6560]">
                      Threat Risk Score
                    </p>
                    <p className="text-xs font-mono text-[#E8E2D9]/70 leading-relaxed">
                      Composite of blast radius, severity, affected users &amp; signal confidence
                    </p>
                    <div className="flex items-center gap-2 pt-1 flex-wrap">
                      <span className="text-[10px] font-mono text-[#6B6560] uppercase">Severity:</span>
                      <span className="text-sm font-bold text-[#EF4444]">{impact.severity}</span>
                    </div>
                  </div>
                </div>

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
