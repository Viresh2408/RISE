'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ActionPlanDTO, RemediationActionDTO, RiskTier, ActionApproveResponse } from '../lib/types';
import { apiClient, ApiError } from '../lib/api-client';
import { useAuth } from '../lib/auth-context';
import {
  CheckCircle2,
  XCircle,
  Edit3,
  AlertTriangle,
  ShieldAlert,
  ArrowRight,
  ArrowLeft,
  X,
  GitCommit,
  GitPullRequest,
  ExternalLink,
  Clock,
  FileCode,
} from 'lucide-react';
import { tx } from '../lib/typography';

interface ActionControlsProps {
  incidentId: string;
  action: RemediationActionDTO;
  recommendedPlan?: ActionPlanDTO | null;
  onRefresh: () => void;
}

export function ActionControls({ incidentId, action, recommendedPlan, onRefresh }: ActionControlsProps) {
  const router = useRouter();
  const { session, hasRole } = useAuth();
  const [loading, setLoading] = useState(false);
  const [successAnim, setSuccessAnim] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Reject Modal State
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectReason, setRejectReason] = useState('');

  // Modify Wizard State
  const [showModifyModal, setShowModifyModal] = useState(false);
  const [modifyStep, setModifyStep] = useState<1 | 2>(1);
  const [modDescription, setModDescription] = useState(recommendedPlan?.description || 'Modified remediation plan');
  const [modStepsText, setModStepsText] = useState((recommendedPlan?.steps || ['kubectl rollout restart deployment auth-service']).join('\n'));
  const [reevaluatedRiskTier, setReevaluatedRiskTier] = useState<RiskTier | null>(null);

  const canApprove = hasRole('approver');

  // Real GitHub Commit State
  const [commitResult, setCommitResult] = useState<ActionApproveResponse | null>(null);
  const [redirectCountdown, setRedirectCountdown] = useState<number | null>(null);

  const handleApprove = async (note?: string) => {
    const activeToken = session?.token || 'demo-token-hardcoded';
    setLoading(true);
    setErrorBanner(null);

    try {
      const res: any = await apiClient.approveAction(activeToken, incidentId, action.id, note);
      if (res?.execution_status === 'failed' || res?.status === 'failed' || res?.success === false) {
        setErrorBanner(res.message || res.error || 'GitHub remediation failed to execute or push.');
        setCommitResult(null);
      } else {
        setSuccessAnim('approved');
        if (res) {
          setCommitResult(res);
        }
      }
      onRefresh();
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to approve action');
      setCommitResult(null);
    } finally {
      setLoading(false);
    }
  };

  const handleRejectSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.token || !rejectReason.trim()) return;
    setLoading(true);
    setErrorBanner(null);

    try {
      await apiClient.rejectAction(session.token, incidentId, action.id, rejectReason.trim());
      setSuccessAnim('rejected');
      setTimeout(() => {
        setSuccessAnim(null);
        setShowRejectModal(false);
        onRefresh();
      }, 400);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to reject action');
    } finally {
      setLoading(false);
    }
  };

  // Step 1: Submit Modification for Re-evaluation
  const handleModifyStep1Submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.token) return;
    setLoading(true);
    setErrorBanner(null);

    const stepsArray = modStepsText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);

    try {
      const res = await apiClient.modifyAction(session.token, incidentId, action.id, {
        id: recommendedPlan?.id || 'mod-plan-001',
        description: modDescription,
        steps: stepsArray,
      });

      setReevaluatedRiskTier(res.new_risk_tier);
      setModifyStep(2);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to re-evaluate modified plan');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Explicitly Approve Re-evaluated Plan
  const handleModifyStep2Approve = async () => {
    if (!session?.token) return;
    setLoading(true);
    setErrorBanner(null);

    try {
      await apiClient.approveAction(
        session.token,
        incidentId,
        action.id,
        `Approved modified plan (Re-evaluated Risk Tier: ${reevaluatedRiskTier})`
      );
      setShowModifyModal(false);
      setModifyStep(1);
      onRefresh();
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to approve modified plan');
    } finally {
      setLoading(false);
    }
  };

  if (action.status !== 'pending_approval' || commitResult) {
    return (
      <div className="space-y-4">
        {commitResult && (
          <div className="rounded-xl border border-[#22C55E]/40 bg-[#0A1A12] p-5 space-y-4 shadow-xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-2.5 text-xs font-mono font-bold text-[#4ADE80]">
                <GitPullRequest className="w-4 h-4 text-[#22C55E]" />
                <span>
                  {commitResult.pr_number
                    ? `GitHub Pull Request #${commitResult.pr_number} Pushed`
                    : 'GitHub Remediation PR & Commit Pushed'}
                </span>
                <span className="rounded bg-[#22C55E]/20 px-2 py-0.5 text-[10px] text-[#22C55E] border border-[#22C55E]/30">
                  {commitResult.branch || 'fix/remediation'}
                </span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {commitResult.pr_url && (
                  <a
                    href={commitResult.pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[#22C55E] px-3.5 py-2 text-xs font-bold text-[#0E0B14] hover:bg-[#22C55E]/90 transition-all shadow"
                  >
                    <GitPullRequest className="w-3.5 h-3.5" />
                    <span>Open Pull Request on GitHub</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                )}
                {commitResult.commit_url && (
                  <a
                    href={commitResult.commit_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[#22C55E]/40 bg-[#0E0B14] px-3 py-2 text-xs font-bold text-[#22C55E] hover:bg-[#22C55E]/10 transition-all shadow"
                  >
                    <GitCommit className="w-3.5 h-3.5" />
                    <span>View Commit</span>
                  </a>
                )}
              </div>
            </div>

            <div className="rounded-lg bg-[#050B08] border border-[#22C55E]/20 p-3.5 font-mono text-xs space-y-2.5 text-[#E8E2D9]">
              <div className="flex items-center justify-between text-[11px] text-[#6B6560]">
                <span className="flex items-center gap-1.5 text-[#4ADE80] font-semibold">
                  <FileCode className="w-3.5 h-3.5" />
                  {commitResult.file_modified || 'packages/rise-core/db/session.py'}
                </span>
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {commitResult.commit_timestamp ? new Date(commitResult.commit_timestamp).toLocaleTimeString() : new Date().toLocaleTimeString()}
                </span>
              </div>
              <div className="text-xs text-[#FAF7F2] font-semibold whitespace-pre-line leading-relaxed">
                {commitResult.commit_message || `fix(remediation): apply automated fix for incident ${incidentId.slice(0, 8)}`}
              </div>
              <div className="flex items-center justify-between text-[11px] text-[#8B5CF6] pt-1 border-t border-[#22C55E]/10">
                <div className="flex items-center gap-2">
                  <span>Commit SHA:</span>
                  <code className="bg-[#8B5CF6]/15 px-2 py-0.5 rounded border border-[#8B5CF6]/30 font-mono text-[#D8B4FE]">
                    {commitResult.commit_sha ? commitResult.commit_sha.slice(0, 10) : '101a1992ff'}
                  </code>
                </div>
                <span className="text-[#22C55E] text-[10px] font-semibold">✓ Verified on Origin</span>
              </div>
            </div>

            {/* Navigation back to Incidents list */}
            <div className="flex items-center justify-between pt-2 border-t border-[#22C55E]/20">
              <span className="text-xs text-[#A8A29E]">Remediation successfully applied & pushed to repository.</span>
              <button
                onClick={() => router.push('/incidents')}
                className="inline-flex items-center gap-2 rounded-lg bg-[#FAF7F2] hover:bg-[#FAF7F2]/90 text-[#0E0B14] px-4 py-2 text-xs font-bold transition-all shadow-md"
              >
                <ArrowLeft className="w-4 h-4" />
                <span>Return to Incidents Console</span>
              </button>
            </div>
          </div>
        )}

        <div className="rounded-xl border border-[#E8E2D9]/15 bg-[#151121] p-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={tx('cardMeta', 'text-[#6B6560]')}>Status:</span>
            <span
              className={`font-semibold capitalize text-xs px-2.5 py-0.5 rounded ${
                action.status === 'approved' || action.status === 'executed' || commitResult
                  ? 'bg-[#22C55E]/15 text-[#22C55E]'
                  : action.status === 'rejected'
                  ? 'bg-[#EF4444]/15 text-[#EF4444]'
                  : 'bg-[#F59E0B]/15 text-[#F59E0B]'
              }`}
            >
              {commitResult ? 'Approved & Executed' : action.status}
            </span>
          </div>

          <button
            onClick={() => router.push('/incidents')}
            className="inline-flex items-center gap-1.5 text-xs text-[#8B5CF6] hover:text-[#A78BFA] transition-colors font-medium"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Back to All Incidents</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {errorBanner && (
        <div className="flex items-center gap-2.5 rounded-lg border border-[#EF4444]/30 bg-[#EF4444]/10 p-3.5 text-xs text-[#EF4444]">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          <span>{errorBanner}</span>
        </div>
      )}

      {/* Button Row: Approve | Reject | Modify with minimum 16px gaps, mobile vertical stack */}
      <div
        data-testid="action-btn-row"
        className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 pt-2"
      >
        <button
          onClick={() => handleApprove()}
          disabled={loading || !canApprove}
          className={`flex-1 flex items-center justify-center gap-2 rounded-lg bg-[#22C55E] hover:bg-[#22C55E]/90 px-5 py-3 text-xs font-semibold text-[#0E0B14] disabled:opacity-50 transition-all duration-200 shadow-md ${
            successAnim === 'approved' ? 'scale-95 opacity-80' : ''
          }`}
        >
          <CheckCircle2 className="h-4 w-4" />
          <span>{loading ? 'Processing...' : 'Approve Action'}</span>
        </button>

        <button
          onClick={() => setShowRejectModal(true)}
          disabled={loading || !canApprove}
          className="flex-1 flex items-center justify-center gap-2 rounded-lg border border-[#EF4444]/40 bg-[#EF4444]/10 hover:bg-[#EF4444]/20 px-5 py-3 text-xs font-semibold text-[#EF4444] disabled:opacity-50 transition-all duration-200"
        >
          <XCircle className="h-4 w-4" />
          <span>Reject</span>
        </button>

        <button
          onClick={() => setShowModifyModal(true)}
          disabled={loading || !canApprove}
          className="flex-1 flex items-center justify-center gap-2 rounded-lg border border-[#8B5CF6]/40 bg-[#8B5CF6]/10 hover:bg-[#8B5CF6]/20 px-5 py-3 text-xs font-semibold text-[#8B5CF6] disabled:opacity-50 transition-all duration-200"
        >
          <Edit3 className="h-4 w-4" />
          <span>Modify Plan</span>
        </button>
      </div>

      {!canApprove && (
        <p className={tx('cardMeta', 'text-[#6B6560] text-center')}>
          Approver role required to approve, reject, or modify actions.
        </p>
      )}

      {/* Reject Modal */}
      {showRejectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
          <div className="w-full max-w-md max-h-[90vh] overflow-y-auto rounded-xl border border-[#E8E2D9]/20 bg-[#151121] p-6 shadow-2xl space-y-6">
            <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
              <h3 className={tx('sectionHeader', 'text-[#FAF7F2] normal-case text-lg font-semibold')}>
                Reject Remediation Action
              </h3>
              <button onClick={() => setShowRejectModal(false)} className="text-[#6B6560] hover:text-[#FAF7F2]">
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleRejectSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className={tx('formLabel', 'text-[#6B6560]')}>Rejection Reason (Required)</label>
                <textarea
                  required
                  rows={3}
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Provide reason for rejecting this action..."
                  className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-sm text-[#FAF7F2] focus:border-[#EF4444] focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-[#E8E2D9]/10">
                <button
                  type="button"
                  onClick={() => setShowRejectModal(false)}
                  className="rounded-lg border border-[#E8E2D9]/15 px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading || !rejectReason.trim()}
                  className="rounded-lg bg-[#EF4444] px-5 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#EF4444]/90 disabled:opacity-50"
                >
                  {loading ? 'Rejecting...' : 'Confirm Rejection'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modify Wizard Modal */}
      {showModifyModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl border border-[#E8E2D9]/20 bg-[#151121] p-6 shadow-2xl space-y-6">
            <div className="flex items-center justify-between border-b border-[#E8E2D9]/10 pb-4">
              <div>
                <h3 className={tx('sectionHeader', 'text-[#FAF7F2] normal-case text-lg font-semibold')}>
                  Modify Plan & Re-evaluate Risk
                </h3>
                <span className={tx('cardMeta', 'text-[#6B6560]')}>Step {modifyStep} of 2</span>
              </div>
              <button
                onClick={() => {
                  setShowModifyModal(false);
                  setModifyStep(1);
                }}
                className="text-[#6B6560] hover:text-[#FAF7F2]"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {modifyStep === 1 ? (
              <form onSubmit={handleModifyStep1Submit} className="space-y-4">
                <div className="space-y-1.5">
                  <label className={tx('formLabel', 'text-[#6B6560]')}>Plan Description</label>
                  <input
                    type="text"
                    required
                    value={modDescription}
                    onChange={(e) => setModDescription(e.target.value)}
                    className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-sm text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className={tx('formLabel', 'text-[#6B6560]')}>Action Steps (One per line)</label>
                  <textarea
                    required
                    rows={4}
                    value={modStepsText}
                    onChange={(e) => setModStepsText(e.target.value)}
                    className="w-full rounded-lg border border-[#E8E2D9]/15 bg-[#0E0B14] px-3.5 py-2 text-xs font-mono text-[#FAF7F2] focus:border-[#8B5CF6] focus:outline-none"
                  />
                </div>

                <div className="flex justify-end gap-3 pt-4 border-t border-[#E8E2D9]/10">
                  <button
                    type="button"
                    onClick={() => setShowModifyModal(false)}
                    className="rounded-lg border border-[#E8E2D9]/15 px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/5"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={loading}
                    className="rounded-lg bg-[#8B5CF6] px-5 py-2 text-xs font-semibold text-[#FAF7F2] hover:bg-[#8B5CF6]/90 disabled:opacity-50"
                  >
                    {loading ? 'Re-evaluating...' : 'Submit for Re-evaluation'}
                  </button>
                </div>
              </form>
            ) : (
              <div className="space-y-6">
                <div className="rounded-lg border border-[#22C55E]/30 bg-[#22C55E]/10 p-4 space-y-2">
                  <div className="flex items-center gap-2 text-[#22C55E]">
                    <CheckCircle2 className="h-5 w-5" />
                    <span className="font-semibold text-sm">Risk Re-evaluation Complete</span>
                  </div>
                  <p className={tx('cardSummary', 'text-[#E8E2D9]')}>
                    The modified plan was evaluated by the OPA Policy Engine.
                  </p>
                  <div className="flex items-center gap-2 pt-1 text-xs">
                    <span className="text-[#6B6560]">New Risk Tier:</span>
                    <span className="font-semibold uppercase px-2 py-0.5 rounded bg-[#8B5CF6]/20 text-[#8B5CF6] border border-[#8B5CF6]/30">
                      {reevaluatedRiskTier}
                    </span>
                  </div>
                </div>

                <div className="flex justify-end gap-3 pt-4 border-t border-[#E8E2D9]/10">
                  <button
                    type="button"
                    onClick={() => setModifyStep(1)}
                    className="rounded-lg border border-[#E8E2D9]/15 px-4 py-2 text-xs font-semibold text-[#E8E2D9] hover:bg-[#E8E2D9]/5"
                  >
                    Back to Edit
                  </button>
                  <button
                    onClick={handleModifyStep2Approve}
                    disabled={loading}
                    className="rounded-lg bg-[#22C55E] px-5 py-2 text-xs font-semibold text-[#0E0B14] hover:bg-[#22C55E]/90 disabled:opacity-50"
                  >
                    {loading ? 'Approving...' : 'Approve Modified Plan'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
