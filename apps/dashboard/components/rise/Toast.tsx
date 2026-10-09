'use client';

import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, Info, AlertTriangle, XCircle, X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';
import { useMounted } from './hooks';

export type ToastTone = 'success' | 'info' | 'warning' | 'error';

export interface ToastOptions {
  title: string;
  description?: string;
  tone?: ToastTone;
  /** ms until auto-dismiss; 0 keeps it until dismissed. Default 5000 (8000 for errors). */
  duration?: number;
}

interface ToastRecord {
  id: string;
  tone: ToastTone;
  title: string;
  description?: string;
}

interface ToastContextValue {
  notify: (opts: ToastOptions) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/* Semantic tone → RISE colour + icon. Icon shape carries meaning independently
   of colour, so state is never communicated by colour alone. */
const TONE_META: Record<ToastTone, { icon: LucideIcon; accent: string; ring: string }> = {
  success: { icon: CheckCircle2, accent: 'text-status-approved', ring: 'border-status-approved/40' },
  info: { icon: Info, accent: 'text-violet-accent', ring: 'border-violet-accent/40' },
  warning: { icon: AlertTriangle, accent: 'text-amber-accent', ring: 'border-amber-accent/40' },
  error: { icon: XCircle, accent: 'text-sev1', ring: 'border-sev1/40' },
};

let counter = 0;
const nextId = () => `toast-${++counter}`;

/**
 * Toast host. Mount once near the app root. Exposes {@link useToast} for
 * imperative, non-decorative notifications: errors announce assertively, all
 * other tones politely. Never use a toast to report unavailable data as
 * success — pick the tone that matches the real outcome.
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const notify = useCallback(
    (opts: ToastOptions) => {
      const id = nextId();
      const tone = opts.tone ?? 'info';
      setToasts((prev) => [
        ...prev,
        { id, tone, title: opts.title, description: opts.description },
      ]);
      const duration = opts.duration ?? (tone === 'error' ? 8000 : 5000);
      if (duration > 0) {
        timers.current.set(id, setTimeout(() => dismiss(id), duration));
      }
      return id;
    },
    [dismiss],
  );

  const value = useMemo(() => ({ notify, dismiss }), [notify, dismiss]);

  const errors = toasts.filter((t) => t.tone === 'error');
  const rest = toasts.filter((t) => t.tone !== 'error');

  return (
    <ToastContext.Provider value={value}>
      {children}
      <Toaster errors={errors} rest={rest} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

/** Access the toast API. Throws if used outside a {@link ToastProvider}. */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a <ToastProvider>.');
  return ctx;
}

function Toaster({
  errors,
  rest,
  onDismiss,
}: {
  errors: ToastRecord[];
  rest: ToastRecord[];
  onDismiss: (id: string) => void;
}) {
  const mounted = useMounted();
  if (!mounted) return null;

  return createPortal(
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[110] flex flex-col items-center gap-2 p-4 sm:inset-x-auto sm:right-0 sm:items-end">
      {/* Errors interrupt (assertive); everything else is announced politely.
          Both regions are always present so screen readers register additions. */}
      <div role="alert" aria-live="assertive" className="flex w-full flex-col items-center gap-2 sm:items-end">
        {errors.map((t) => (
          <ToastCard key={t.id} toast={t} onDismiss={onDismiss} />
        ))}
      </div>
      <div role="status" aria-live="polite" className="flex w-full flex-col items-center gap-2 sm:items-end">
        {rest.map((t) => (
          <ToastCard key={t.id} toast={t} onDismiss={onDismiss} />
        ))}
      </div>
    </div>,
    document.body,
  );
}

function ToastCard({
  toast,
  onDismiss,
}: {
  toast: ToastRecord;
  onDismiss: (id: string) => void;
}) {
  const meta = TONE_META[toast.tone];
  const Icon = meta.icon;
  return (
    <div
      className={cn(
        'rise-animate-toast pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-[var(--radius-lg)] border bg-surface-3/95 p-3.5 shadow-elevation-3 backdrop-blur-md',
        meta.ring,
      )}
    >
      <Icon className={cn('mt-0.5 h-5 w-5 flex-shrink-0', meta.accent)} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className={tx('cardMeta', 'font-semibold text-cream')}>{toast.title}</p>
        {toast.description && (
          <p className={tx('cardMeta', 'mt-0.5 text-warm-grey-100')}>{toast.description}</p>
        )}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
        className="flex-shrink-0 rounded-[var(--radius-sm)] p-0.5 text-warm-grey-600 transition-colors duration-fast hover:text-cream focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-focus)]"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
