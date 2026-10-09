'use client';

import React from 'react';
import { Check, X, PencilLine, ShieldAlert } from 'lucide-react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';

/**
 * Human approval control for a proposed remediation.
 *
 * This component is presentational and advisory only: it emits the operator's
 * intent via callbacks and NEVER auto-approves. The actual auto-vs-human gate is
 * enforced server-side (Risk Engine + RiskPolicy + persisted Approval anchor);
 * rendering these buttons does not bypass it. Amber is the human-attention
 * signal — when `requiresApproval` is set we say so explicitly rather than
 * implying the system already decided.
 */
export interface ApprovalActionProps {
  onApprove?: () => void;
  onReject?: () => void;
  /** Optional "modify plan" affordance; hidden when no handler is given. */
  onModify?: () => void;
  /** Disable every control (e.g. while a decision is in flight or already made). */
  disabled?: boolean;
  /** Show the amber "human approval required" banner above the controls. */
  requiresApproval?: boolean;
  className?: string;
}

const BTN_BASE =
  'inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-sm)] border px-3 py-1.5 transition-colors duration-base disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-near-black';

export function ApprovalAction({
  onApprove,
  onReject,
  onModify,
  disabled = false,
  requiresApproval = false,
  className,
}: ApprovalActionProps) {
  return (
    <div className={cn('flex flex-col gap-3', className)}>
      {requiresApproval && (
        <div
          className={cn(
            'flex items-center gap-2 rounded-[var(--radius-sm)] border border-amber-accent/30 bg-amber-accent/10 px-3 py-2',
            tx('cardMeta', 'text-amber-accent'),
          )}
          role="status"
        >
          <ShieldAlert className="h-4 w-4 shrink-0" aria-hidden />
          <span>Human approval required before execution.</span>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onApprove}
          disabled={disabled || !onApprove}
          className={cn(
            BTN_BASE,
            tx('actionButton'),
            'border-status-approved/40 bg-status-approved/15 text-status-approved hover:bg-status-approved/25 focus-visible:ring-status-approved',
          )}
        >
          <Check className="h-4 w-4" aria-hidden />
          Approve
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={disabled || !onReject}
          className={cn(
            BTN_BASE,
            tx('actionButton'),
            'border-status-rejected/40 bg-status-rejected/15 text-status-rejected hover:bg-status-rejected/25 focus-visible:ring-status-rejected',
          )}
        >
          <X className="h-4 w-4" aria-hidden />
          Reject
        </button>
        {onModify && (
          <button
            type="button"
            onClick={onModify}
            disabled={disabled}
            className={cn(
              BTN_BASE,
              tx('actionButton'),
              'border-warm-grey-700 bg-transparent text-warm-grey-100 hover:bg-warm-grey-700/40 focus-visible:ring-violet-accent',
            )}
          >
            <PencilLine className="h-4 w-4" aria-hidden />
            Modify plan
          </button>
        )}
      </div>
    </div>
  );
}
