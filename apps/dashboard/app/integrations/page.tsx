'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Navbar } from '../../components/navbar';
import { AdminGate } from '../../components/shared/AdminGate';
import { CardSkeleton } from '../../components/shared/CardSkeleton';
import { EmptyState } from '../../components/shared/EmptyState';
import { IntegrationDTO } from '../../lib/types';
import { apiClient } from '../../lib/api-client';
import { useAuth } from '../../lib/auth-context';
import { tx } from '../../lib/typography';
import {
  Plug,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
  Trash2,
  Github,
  Bell,
  MessageSquare,
  Cloud,
  Activity,
  Radio,
  X,
} from 'lucide-react';

const INTEGRATION_CATALOG: Omit<IntegrationDTO, 'status' | 'connected_at'>[] = [
  {
    type: 'github',
    name: 'GitHub Repository & App',
    description: 'Pull request creation, automated code diff analysis, and commit context ingestion.',
    icon: 'github',
  },
  {
    type: 'slack',
    name: 'Slack Workspace ChatOps',
    description: 'Real-time alert notifications, interactive approval cards, and operator slash commands.',
    icon: 'slack',
  },
  {
    type: 'cloudwatch',
    name: 'AWS CloudWatch Metrics & Logs',
    description: 'Inbound alarm webhooks, CloudWatch logs correlation, and EC2/Lambda execution telemetry.',
    icon: 'cloudwatch',
  },
  {
    type: 'alertmanager',
    name: 'Prometheus Alertmanager',
    description: 'Prometheus metric stream alerts, firing rule webhook receiver, and target health state.',
    icon: 'alertmanager',
  },
];

function getIntegrationIcon(type: string) {
  // Spec requirement: Monochrome Lucide icons only (warm-grey-600) — never colored brand logos
  switch (type) {
    case 'github': return <Github className="h-6 w-6 text-[#6B6560]" />;
    case 'slack': return <MessageSquare className="h-6 w-6 text-[#6B6560]" />;
    case 'cloudwatch': return <Cloud className="h-6 w-6 text-[#6B6560]" />;
    case 'alertmanager': return <Bell className="h-6 w-6 text-[#6B6560]" />;
    default: return <Activity className="h-6 w-6 text-[#6B6560]" />;
  }
}

function IntegrationsContent() {
  const { session } = useAuth();
  const [integrations, setIntegrations] = useState<IntegrationDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Connect modal state
  const [connectTarget, setConnectTarget] = useState<{ type: string; name: string } | null>(null);
  const [connectingType, setConnectingType] = useState<string | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);

  // Disconnect modal state
  const [disconnectTarget, setDisconnectTarget] = useState<{ type: string; name: string } | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);

  const showSuccess = (msg: string) => {
    setSuccessMsg(msg);
    setTimeout(() => setSuccessMsg(null), 5000);
  };

  const fetchIntegrations = useCallback(async () => {
    if (!session?.token) return;
    setLoading(true);
    try {
      const data = await apiClient.listIntegrations(session.token);
      setIntegrations(data || []);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load integrations');
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    fetchIntegrations();
  }, [fetchIntegrations]);

  const openConnectModal = (type: string, name: string) => {
    setConnectError(null);
    setConnectTarget({ type, name });
  };

  const handleConfirmConnect = async () => {
    if (!session?.token || !connectTarget) return;
    setConnectingType(connectTarget.type);
    setConnectError(null);
    try {
      const res = await apiClient.connectIntegration(session.token, connectTarget.type);
      // The connect endpoint returns a provider authorization URL (OAuth-style
      // handoff). Hand the browser off to complete the grant. The integration
      // is NOT connected until the operator finishes authorization and returns,
      // so we must not report success here.
      if (res?.redirect_url) {
        window.location.href = res.redirect_url;
        return;
      }
      // No authorization URL was returned — surface that honestly instead of
      // reporting a fabricated "connected successfully".
      setConnectError(
        'The backend did not return an authorization URL for this integration, so the connection could not be started.'
      );
    } catch (err: any) {
      setConnectError(err.message || 'Failed to start connection');
    } finally {
      setConnectingType(null);
    }
  };

  const handleConfirmDisconnect = async () => {
    if (!session?.token || !disconnectTarget) return;
    setDisconnecting(true);
    setDisconnectError(null);
    try {
      await apiClient.disconnectIntegration(session.token, disconnectTarget.type);
      setDisconnectTarget(null);
      await fetchIntegrations();
      showSuccess(`${disconnectTarget.name} disconnected.`);
    } catch (err: any) {
      setDisconnectError(err.message || 'Failed to disconnect');
    } finally {
      setDisconnecting(false);
    }
  };

  const getStatus = (type: string) => {
    const found = integrations.find((i) => i.type === type);
    return found?.status || 'disconnected';
  };

  const getConnectedAt = (type: string) => {
    const found = integrations.find((i) => i.type === type);
    return found?.connected_at || null;
  };

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className={tx('incidentTitle', 'text-[#FAF7F2] flex items-center gap-3')}>
            <Plug className="w-7 h-7 text-[#8B5CF6]" />
            <span>Infrastructure &amp; SaaS Integrations</span>
          </h1>
          <p className={tx('cardMeta', 'text-[#6B6560] mt-1 font-mono')}>
            OAuth app connections, webhook stream receivers, and cloud tool credentials
          </p>
        </div>

        <button
          onClick={fetchIntegrations}
          className="inline-flex items-center gap-2 rounded-lg border border-[#E8E2D9]/15 bg-[#151121] px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/10 transition-colors self-start sm:self-center"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-xl border border-[#EF4444]/30 bg-[#EF4444]/10 p-4 text-[#EF4444] text-xs font-mono">
          <AlertTriangle className="w-5 h-5 flex-shrink-0" />
          <span>Failed to load integrations — {error}</span>
        </div>
      )}

      {successMsg && (
        <div className="flex items-center gap-3 rounded-xl border border-[#22C55E]/30 bg-[#22C55E]/10 p-4 text-[#22C55E] text-xs font-mono">
          <CheckCircle2 className="w-5 h-5 flex-shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Integration Cards Grid */}
      {loading ? (
        <CardSkeleton count={4} variant="integration" />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {INTEGRATION_CATALOG.map((cat) => {
            const intStatus = getStatus(cat.type);
            const isConnected = intStatus === 'connected';
            const connectedAt = getConnectedAt(cat.type);

            return (
              <div
                key={cat.type}
                data-testid="integration-card"
                className={`rounded-xl border ${
                  isConnected ? 'border-[#8B5CF6]/30 bg-[#151121]' : 'border-[#E8E2D9]/15 bg-[#151121]'
                } p-6 shadow-md hover:border-[#8B5CF6]/40 transition-all duration-200 flex flex-col justify-between space-y-6`}
              >
                <div className="space-y-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <div className={`flex h-12 w-12 items-center justify-center rounded-xl border ${
                        isConnected ? 'border-[#8B5CF6]/40 bg-[#8B5CF6]/10' : 'border-[#E8E2D9]/15 bg-[#0E0B14]'
                      }`}>
                        {getIntegrationIcon(cat.type)}
                      </div>
                      <div>
                        <h3 className={tx('cardTitle', 'text-[#FAF7F2]')}>{cat.name}</h3>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className={`h-2 w-2 rounded-full ${isConnected ? 'bg-[#22C55E] shadow-[0_0_6px_#22C55E]' : 'bg-[#6B6560]'}`} />
                          <span className={tx('badge', isConnected ? 'text-[#22C55E]' : 'text-[#6B6560]')}>
                            {isConnected ? 'CONNECTED' : 'NOT CONNECTED'}
                          </span>
                        </div>
                        {isConnected && connectedAt && (
                          <p className="text-[10px] text-[#6B6560] mt-0.5 font-mono">
                            Since {new Date(connectedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>

                  <p className={tx('cardSummary', 'text-[#6B6560]')}>{cat.description}</p>
                </div>

                {/* Actions */}
                <div className="pt-4 border-t border-[#E8E2D9]/10 flex items-center justify-end gap-3">
                  {isConnected ? (
                    <button
                      onClick={() => { setDisconnectError(null); setDisconnectTarget({ type: cat.type, name: cat.name }); }}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[#EF4444]/40 bg-[#EF4444]/10 px-4 py-2 text-xs font-semibold text-[#EF4444] hover:bg-[#EF4444]/20 transition-colors"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      <span>Disconnect</span>
                    </button>
                  ) : (
                    <button
                      onClick={() => openConnectModal(cat.type, cat.name)}
                      disabled={connectingType === cat.type}
                      className="inline-flex items-center gap-2 rounded-lg bg-[#8B5CF6] px-5 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#7C3AED] disabled:opacity-50 transition-colors shadow-md"
                    >
                      {connectingType === cat.type ? (
                        <><RefreshCw className="h-3.5 w-3.5 animate-spin" /><span>Connecting...</span></>
                      ) : (
                        <span>Connect</span>
                      )}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Connect Credential Modal ─────────────────────────────────────── */}
      {connectTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-xl border border-[#8B5CF6]/30 bg-[#151121] p-6 shadow-2xl space-y-5">
            <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#8B5CF6]/40 bg-[#8B5CF6]/10">
                  {getIntegrationIcon(connectTarget.type)}
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[#FAF7F2]">Connect {connectTarget.name}</h3>
                  <p className="text-[10px] text-[#6B6560] font-mono mt-0.5">Backend-initiated authorization flow</p>
                </div>
              </div>
              <button onClick={() => { setConnectError(null); setConnectTarget(null); }} className="text-[#6B6560] hover:text-[#FAF7F2] transition-colors">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <p className={tx('cardSummary', 'text-[#E8E2D9]')}>
                Connecting starts an authorization flow handled by the RISE backend.
                You will be redirected to {connectTarget.name} to grant access — RISE
                does not collect or store provider credentials on this screen.
              </p>
              <div className="flex items-start gap-2 rounded-lg border border-[#8B5CF6]/20 bg-[#8B5CF6]/5 p-3">
                <ExternalLink className="h-4 w-4 text-[#8B5CF6] flex-shrink-0 mt-0.5" />
                <p className="text-[11px] text-[#6B6560] font-mono leading-relaxed">
                  On continue, the backend returns a provider authorization URL and
                  your browser is handed off to complete the grant. The integration is
                  not marked connected until you finish authorization and return.
                </p>
              </div>

              {connectError && (
                <div className="flex items-start gap-2 rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 p-3 text-xs font-mono text-[#EF4444]">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <span>{connectError}</span>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 pt-4 border-t border-[#E8E2D9]/10">
              <button
                type="button"
                onClick={() => { setConnectError(null); setConnectTarget(null); }}
                className="rounded-lg border border-[#E8E2D9]/15 px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/5 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmConnect}
                disabled={!!connectingType}
                className="rounded-lg bg-[#8B5CF6] px-5 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#7C3AED] disabled:opacity-50 transition-colors inline-flex items-center gap-2"
              >
                {connectingType ? (
                  <><RefreshCw className="h-3.5 w-3.5 animate-spin" /><span>Starting...</span></>
                ) : (
                  <span>Continue</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Disconnect Confirm Modal ─────────────────────────────────────── */}
      {disconnectTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-xl border border-[#E8E2D9]/20 bg-[#151121] p-6 shadow-2xl space-y-6">
            <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
              <h3 className="text-sm font-semibold text-[#FAF7F2]">Disconnect {disconnectTarget.name}?</h3>
              <button onClick={() => { setDisconnectError(null); setDisconnectTarget(null); }} className="text-[#6B6560] hover:text-[#FAF7F2] transition-colors">
                <X className="h-5 w-5" />
              </button>
            </div>

            <p className={tx('cardSummary', 'text-[#E8E2D9]')}>
              This will revoke RISE&apos;s API access to {disconnectTarget.name}. Active incident investigations using this connector will lose live context.
            </p>

            {disconnectError && (
              <div className="flex items-start gap-2 rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 p-3 text-xs font-mono text-[#EF4444]">
                <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>{disconnectError}</span>
              </div>
            )}

            <div className="flex justify-end gap-3 pt-4 border-t border-[#E8E2D9]/10">
              <button
                type="button"
                onClick={() => { setDisconnectError(null); setDisconnectTarget(null); }}
                className="rounded-lg border border-[#E8E2D9]/15 px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/5 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDisconnect}
                disabled={disconnecting}
                className="rounded-lg bg-[#EF4444] px-5 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#EF4444]/90 disabled:opacity-50 transition-colors"
              >
                {disconnecting ? 'Disconnecting...' : 'Confirm Disconnect'}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

export default function IntegrationsPage() {
  return (
    <div className="min-h-screen bg-[#0E0B14] text-[#FAF7F2]">
      <Navbar />
      <AdminGate>
        <IntegrationsContent />
      </AdminGate>
    </div>
  );
}
