'use client';

import React, { useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X, AlertTriangle } from 'lucide-react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';
import {
  useBodyScrollLock,
  useFocusTrap,
  useMounted,
  useOnEscape,
} from './hooks';

const SIZE_CLASSES = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
} as const;

export type DialogSize = keyof typeof SIZE_CLASSES;

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  size?: DialogSize;
  /** Optional leading icon node (already coloured by the caller). */
  icon?: React.ReactNode;
  /** When false, overlay-click and Escape will not dismiss (e.g. mid-mutation). */
  dismissable?: boolean;
  className?: string;
}

/**
 * Accessible modal dialog. Hand-rolled (no Radix): portals to `document.body`,
 * traps Tab focus, closes on Escape / overlay-click (when `dismissable`), locks
 * body scroll, and restores focus to the trigger on close. SSR-safe via
 * `useMounted`.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  icon,
  dismissable = true,
  className,
}: DialogProps) {
  const mounted = useMounted();
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();

  useBodyScrollLock(open);
  useFocusTrap(panelRef, open);
  useOnEscape(() => {
    if (dismissable) onClose();
  }, open);

  if (!mounted || !open) return null;

  return createPortal(
    <div
      className="rise-animate-overlay fixed inset-0 z-[100] flex items-center justify-center bg-near-black/80 p-4 backdrop-blur-sm"
      onMouseDown={(e) => {
        // Dismiss only on a genuine overlay click, not a drag ending on it.
        if (dismissable && e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cn(
          'rise-surface rise-elev-4 rise-surface--highlight rise-animate-dialog',
          'relative flex w-full flex-col rounded-[var(--radius-xl)] outline-none',
          SIZE_CLASSES[size],
          className,
        )}
      >
        <div className="flex items-start gap-3 border-b border-[var(--rise-border)] p-5">
          {icon && <span className="mt-0.5 flex-shrink-0">{icon}</span>}
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className={tx('cardTitle', 'text-cream')}>
              {title}
            </h2>
            {description && (
              <p id={descId} className={tx('cardSummary', 'mt-1 text-warm-grey-100')}>
                {description}
              </p>
            )}
          </div>
          {dismissable && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close dialog"
              className="flex-shrink-0 rounded-[var(--radius-sm)] p-1 text-warm-grey-600 transition-colors duration-fast hover:bg-warm-grey-100/10 hover:text-cream focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-focus)]"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {children && <div className="p-5">{children}</div>}

        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-[var(--rise-border)] p-4">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 'danger' styles the confirm control as a destructive action. */
  intent?: 'default' | 'danger';
  /** Disables controls + blocks dismissal while an async action is in flight. */
  busy?: boolean;
}

/**
 * Confirmation dialog built on {@link Dialog} — the in-app replacement for the
 * native `window.confirm()`. Focus is trapped and the confirm button is the
 * caller's responsibility to make the safe/primary action; destructive intents
 * are colour + icon flagged (never colour alone).
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  intent = 'default',
  busy = false,
}: ConfirmDialogProps) {
  const danger = intent === 'danger';
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size="sm"
      dismissable={!busy}
      icon={
        danger ? (
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-sev1/15">
            <AlertTriangle className="h-5 w-5 text-sev1" />
          </span>
        ) : undefined
      }
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className={cn(
              tx('actionButton'),
              'rounded-[var(--radius-md)] border border-[var(--rise-border)] px-3 py-1.5 text-warm-grey-100 transition-colors duration-fast hover:bg-warm-grey-100/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-focus)] disabled:opacity-50',
            )}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className={cn(
              tx('actionButton'),
              'rounded-[var(--radius-md)] px-3 py-1.5 font-semibold transition-colors duration-fast focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-focus)] disabled:opacity-50',
              danger
                ? 'bg-sev1 text-cream hover:bg-sev1/90'
                : 'bg-violet-accent text-cream hover:bg-violet-accent/90',
            )}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </>
      }
    />
  );
}
