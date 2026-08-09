'use client';

import React, { useState } from 'react';
import { ActionPlanDTO, RemediationActionDTO, RiskTier } from '../lib/types';
import { apiClient, ApiError } from '../lib/api-client';
import { useAuth } from '../lib/auth-context';
import { CheckCircle2, XCircle, Edit3, AlertTriangle, ShieldAlert, ArrowRight } from 'lucide-react';

interface ActionControlsProps {
  incidentId: string;
  action: RemediationActionDTO;
  recommendedPlan?: ActionPlanDTO | null;
  onRefresh: () => void;
}

export function ActionControls({ incidentId, action, recommendedPlan, onRefresh }: ActionControlsProps) {
  const { session, hasRole } = useAuth();
  const [loading, setLoading] = useState(false);
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

  const handleApprove = async (note?: string) => {
    if (!session?.token) return;
    setLoading(true);
    setErrorBanner(null);

    try {
      await apiClient.approveAction(session.token, incidentId, action.id, note);
      onRefresh();
    } catch (err: any) {
      if (err instanceof ApiError && (err.code === 'ACTION_PLAN_CHANGED' || err.status === 409)) {
        setErrorBanner(
          'Action plan hash changed since approval was requested. Please review the updated plan below and re-approve.'
        );
      } else {
        setErrorBanner(err.message || 'Failed to approve action');
      }
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
      setShowRejectModal(false);
      onRefresh();
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
      setModifyStep(2); // Advance to Step 2 Review & Approve
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
    try {
      await apiClient.approveAction(session.token, incidentId, action.id, `Approved modified plan with risk tier: ${reevaluatedRiskTier}`);
      setShowModifyModal(false);
      setModifyStep(1);
      onRefresh();
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to approve modified plan');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* HTTP 409 ACTION_PLAN_CHANGED Alert Banner */}
      {errorBanner && (
        <div className="flex items-start space-x-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-amber-300">
          <ShieldAlert className="h-5 w-5 flex-shrink-0 text-amber-400 mt-0.5" />
          <div className="flex-1 text-xs">
            <h4 className="font-bold text-amber-200">Action Plan Warning</h4>
            <p>{errorBanner}</p>
          </div>
          <button onClick={() => setErrorBanner(null)} className="text-xs text-amber-400 hover:underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Decision Buttons Container */}
      <div className="flex items-center space-x-3 flex-wrap gap-y-2">
        {action.status === 'pending_approval' && (
          <>
            <button
              disabled={loading || !canApprove}
              onClick={() => handleApprove('Approved via RISE Dashboard')}
              className="flex items-center space-x-2 rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50 transition-all shadow-md shadow-emerald-950/50"
            >
              <CheckCircle2 className="h-4 w-4" />
              <span>Approve Action</span>
            </button>

            <button
              disabled={loading || !canApprove}
              onClick={() => {
                setShowModifyModal(true);
                setModifyStep(1);
              }}
              className="flex items-center space-x-2 rounded-lg border border-blue-500/40 bg-blue-500/10 px-4 py-2 text-xs font-semibold text-blue-300 hover:bg-blue-500/20 disabled:opacity-50 transition-all"
            >
              <Edit3 className="h-4 w-4" />
              <span>Modify Plan</span>
            </button>

            <button
              disabled={loading || !canApprove}
              onClick={() => setShowRejectModal(true)}
              className="flex items-center space-x-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-xs font-semibold text-red-300 hover:bg-red-500/20 disabled:opacity-50 transition-all"
            >
              <XCircle className="h-4 w-4" />
              <span>Reject Action</span>
            </button>
          </>
        )}

        {action.status === 'approved' && (
          <div className="flex items-center space-x-2 text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-3 py-1.5 rounded-lg border border-emerald-500/30">
            <CheckCircle2 className="h-4 w-4" />
            <span>Action Approved — Graph Resumed & Execution Queued</span>
          </div>
        )}

        {action.status === 'rejected' && (
          <div className="flex items-center space-x-2 text-xs font-semibold text-red-400 bg-red-500/10 px-3 py-1.5 rounded-lg border border-red-500/30">
            <XCircle className="h-4 w-4" />
            <span>Action Rejected</span>
          </div>
        )}

        {!canApprove && action.status === 'pending_approval' && (
          <p className="text-xs text-amber-400 italic">
            * 'approver' or 'admin' role required to take decision actions.
          </p>
        )}
      </div>

      {/* Reject Modal */}
      {showRejectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-xl border border-[#232d3f] bg-[#121824] p-6 space-y-4 shadow-2xl">
            <div className="flex items-center space-x-2 text-red-400">
              <AlertTriangle className="h-5 w-5" />
              <h3 className="text-base font-bold text-white">Reject Action Plan</h3>
            </div>
            <p className="text-xs text-gray-400">
              Provide an explicit rejection reason for the audit trail.
            </p>
            <form onSubmit={handleRejectSubmit} className="space-y-4">
              <textarea
                required
                rows={3}
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="e.g. Risk too high during peak traffic window"
                className="w-full rounded-lg border border-gray-800 bg-[#0a0d14] p-3 text-xs text-gray-200 focus:border-red-500 focus:outline-none"
              />
              <div className="flex justify-end space-x-3">
                <button
                  type="button"
                  onClick={() => setShowRejectModal(false)}
                  className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-2 text-xs text-gray-300 hover:bg-gray-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading || !rejectReason.trim()}
                  className="rounded-lg bg-red-600 px-4 py-2 text-xs font-semibold text-white hover:bg-red-500 disabled:opacity-50"
                >
                  Submit Rejection
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Two-Step Modify Modal */}
      {showModifyModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-xl border border-[#232d3f] bg-[#121824] p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-800 pb-3">
              <div className="flex items-center space-x-2 text-blue-400">
                <Edit3 className="h-5 w-5" />
                <h3 className="text-base font-bold text-white">
                  Modify Action Plan — Step {modifyStep} of 2
                </h3>
              </div>
              <span className="text-xs text-gray-500">
                {modifyStep === 1 ? 'Edit Parameters' : 'Re-evaluated Review'}
              </span>
            </div>

            {modifyStep === 1 ? (
              // Step 1: Submit Modification
              <form onSubmit={handleModifyStep1Submit} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-300 mb-1">
                    Plan Rationale & Description
                  </label>
                  <input
                    type="text"
                    required
                    value={modDescription}
                    onChange={(e) => setModDescription(e.target.value)}
                    className="w-full rounded-lg border border-gray-800 bg-[#0a0d14] p-2.5 text-xs text-gray-200 focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-300 mb-1">
                    Action Steps (One command/step per line)
                  </label>
                  <textarea
                    required
                    rows={4}
                    value={modStepsText}
                    onChange={(e) => setModStepsText(e.target.value)}
                    className="w-full rounded-lg border border-gray-800 bg-[#0a0d14] p-2.5 font-mono text-xs text-gray-200 focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div className="flex justify-end space-x-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowModifyModal(false)}
                    className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-2 text-xs text-gray-300 hover:bg-gray-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={loading}
                    className="flex items-center space-x-1.5 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-50"
                  >
                    <span>Re-evaluate Risk Engine</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </form>
            ) : (
              // Step 2: Review Re-evaluated Plan & Decide
              <div className="space-y-4">
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 space-y-2">
                  <h4 className="text-xs font-bold text-emerald-300 uppercase tracking-wide">
                    Risk Engine Re-evaluation Complete
                  </h4>
                  <div className="flex items-center space-x-2 text-xs text-gray-300">
                    <span>Re-evaluated Risk Tier:</span>
                    <span className="font-bold text-emerald-400 uppercase bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-500/40">
                      {reevaluatedRiskTier || 'medium'}
                    </span>
                  </div>
                </div>

                <div className="space-y-2">
                  <h5 className="text-xs font-semibold text-gray-400">Modified Steps for Execution:</h5>
                  <div className="rounded-lg bg-[#0a0d14] p-3 border border-gray-800 font-mono text-xs text-gray-300 space-y-1">
                    {modStepsText.split('\n').map((step, idx) => (
                      <div key={idx} className="flex items-center space-x-2">
                        <span className="text-gray-500">{idx + 1}.</span>
                        <span>{step}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex justify-end space-x-3 pt-3">
                  <button
                    type="button"
                    onClick={() => setModifyStep(1)}
                    className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-2 text-xs text-gray-300 hover:bg-gray-800"
                  >
                    Back to Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowModifyModal(false)}
                    className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-xs font-semibold text-red-300 hover:bg-red-500/20"
                  >
                    Reject Modified
                  </button>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={handleModifyStep2Approve}
                    className="flex items-center space-x-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    <span>Approve & Resume Graph</span>
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

export interface ActionModalsProps {
  incidentId: string;
  actionId: string;
  currentPlan?: ActionPlanDTO | null;
  showApprove: boolean;
  showReject: boolean;
  showModify: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function ActionModals({
  incidentId,
  actionId,
  currentPlan,
  showApprove,
  showReject,
  showModify,
  onClose,
  onSuccess,
}: ActionModalsProps) {
  const dummyAction: RemediationActionDTO = {
    id: actionId,
    incident_id: incidentId,
    name: 'Execute Action Plan',
    risk_tier: 'high',
    status: 'pending_approval',
  };

  return (
    <ActionControls
      incidentId={incidentId}
      action={dummyAction}
      recommendedPlan={currentPlan}
      onRefresh={onSuccess}
    />
  );
}

