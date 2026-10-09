import React from 'react';
import { CheckCircle2, XCircle, MinusCircle, Loader2, Circle, type LucideIcon } from 'lucide-react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';
import { AGENT_STATE_META, TONE_TEXT_CLASSES, type AgentRunState } from './tokens';
import { ElevationSurface } from './ElevationSurface';

/**
 * A single agent pipeline node (one LangGraph step). Represents a real run
 * state; it never invents telemetry — a missing duration renders "—", not a
 * fabricated latency, and `summary` is shown only when the caller supplies one.
 */
const STATE_ICON: Record<AgentRunState, LucideIcon> = {
  success: CheckCircle2,
  failed: XCircle,
  skipped: MinusCircle,
  running: Loader2,
  pending: Circle,
};

/** Format a real duration; a null/undefined value is unknown, shown as "—". */
function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

export interface AgentNodeProps {
  label: string;
  state: AgentRunState;
  /** Real step duration in ms; unknown → "—" (never fabricated). */
  durationMs?: number | null;
  /** Real one-line output summary; omitted when unavailable. */
  summary?: string | null;
  className?: string;
}

export function AgentNode({ label, state, durationMs, summary, className }: AgentNodeProps) {
  const meta = AGENT_STATE_META[state];
  const Icon = STATE_ICON[state];
  const hasDuration = durationMs !== null && durationMs !== undefined && !Number.isNaN(durationMs);

  return (
    <ElevationSurface level={1} className={cn('flex items-center gap-3 px-3 py-2.5', className)}>
      <Icon
        className={cn('h-4 w-4 shrink-0', TONE_TEXT_CLASSES[meta.tone], state === 'running' && 'animate-spin')}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className={tx('cardTitle', 'truncate text-cream')}>{label}</span>
          <span className={cn('shrink-0 tabular-nums', tx('cardMeta', TONE_TEXT_CLASSES[meta.tone]))}>
            {meta.label}
          </span>
        </div>
        {summary ? (
          <p className={tx('cardMeta', 'mt-0.5 truncate text-warm-grey-600')}>{summary}</p>
        ) : null}
      </div>
      <span
        className={cn('shrink-0 font-mono text-[0.75rem] tabular-nums', hasDuration ? 'text-warm-grey-100' : 'text-warm-grey-600')}
        title={hasDuration ? 'Step duration' : 'Duration not available'}
      >
        {formatDuration(durationMs)}
      </span>
    </ElevationSurface>
  );
}
