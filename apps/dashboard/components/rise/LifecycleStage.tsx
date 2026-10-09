import React from 'react';
import { Check } from 'lucide-react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';
import type { StageState } from './tokens';

/**
 * One node on the RISE agent-pipeline spine. Its state is derived from real
 * pipeline progress by the caller (see {@link deriveLifecycle} or actual
 * AgentStep rows) — 'complete' only ever means a prior, structurally-implied
 * stage, never fabricated forward progress.
 */
const MARKER_STYLES: Record<StageState, string> = {
  complete: 'border-violet-accent bg-violet-accent text-near-black',
  active: 'border-violet-accent bg-violet-accent/15 text-violet-accent shadow-glow-violet',
  pending: 'border-warm-grey-700 bg-transparent text-warm-grey-600',
};

const LABEL_STYLES: Record<StageState, string> = {
  complete: 'text-warm-grey-100',
  active: 'text-cream font-semibold',
  pending: 'text-warm-grey-600',
};

/** The circular stage marker alone — shared by <LifecycleStage> and <Spine>. */
export function StageMarker({ state, className }: { state: StageState; className?: string }) {
  return (
    <span
      className={cn(
        'relative flex h-6 w-6 shrink-0 items-center justify-center rounded-full border transition-colors duration-base',
        MARKER_STYLES[state],
        className,
      )}
      aria-hidden
    >
      {state === 'complete' ? (
        <Check className="h-3.5 w-3.5" strokeWidth={3} />
      ) : state === 'active' ? (
        <span className="h-2 w-2 rounded-full bg-violet-accent" />
      ) : null}
    </span>
  );
}

export interface LifecycleStageProps {
  label: string;
  state: StageState;
  /** Layout hint; 'horizontal' stacks the label under the marker. */
  orientation?: 'vertical' | 'horizontal';
  className?: string;
}

export function LifecycleStage({ label, state, orientation = 'vertical', className }: LifecycleStageProps) {
  return (
    <span
      className={cn(
        'flex items-center gap-2',
        orientation === 'horizontal' && 'flex-col text-center',
        className,
      )}
    >
      <StageMarker state={state} />
      <span className={cn(tx('cardMeta'), LABEL_STYLES[state])}>{label}</span>
      <span className="sr-only">{`(${state})`}</span>
    </span>
  );
}

export { LABEL_STYLES as LIFECYCLE_LABEL_STYLES };
