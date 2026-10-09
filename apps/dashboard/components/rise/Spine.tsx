import React from 'react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';
import { StageMarker } from './LifecycleStage';
import { RISE_LIFECYCLE, deriveLifecycle, type StageState } from './tokens';
import type { IncidentStatus } from '../../lib/types';

/**
 * The RISE agent-pipeline spine: the ingest→verify rail visualised as a series
 * of stage markers joined by connectors.
 *
 * Honesty contract: stage state is derived only from real inputs — either an
 * explicit `stages` array (built from actual AgentStep rows) or an
 * `IncidentStatus` mapped through {@link deriveLifecycle}. With neither, every
 * stage renders 'pending' (nothing has run) rather than implying progress. A
 * connector is "filled" (violet) only when the stage it leaves is complete.
 */
export interface SpineStage {
  key: string;
  label: string;
  state: StageState;
}

export interface SpineProps {
  /** Derive the whole rail from a real incident status. Ignored if `stages` is given. */
  status?: IncidentStatus;
  /** Explicit per-stage state (e.g. built from real AgentStep rows). */
  stages?: SpineStage[];
  orientation?: 'vertical' | 'horizontal';
  className?: string;
}

function resolveStages(status?: IncidentStatus, stages?: SpineStage[]): SpineStage[] {
  if (stages && stages.length > 0) return stages;
  if (status) {
    const derived = deriveLifecycle(status);
    return RISE_LIFECYCLE.map((s) => ({ key: s.key, label: s.label, state: derived[s.key] }));
  }
  return RISE_LIFECYCLE.map((s) => ({ key: s.key, label: s.label, state: 'pending' as StageState }));
}

/** Connector between stage i and i+1: violet once the stage it leaves is complete. */
function connectorClass(leaving: StageState): string {
  return leaving === 'complete' ? 'bg-violet-accent' : 'bg-warm-grey-700/40';
}

export function Spine({ status, stages, orientation = 'vertical', className }: SpineProps) {
  const resolved = resolveStages(status, stages);
  const last = resolved.length - 1;

  if (orientation === 'horizontal') {
    return (
      <ol className={cn('flex items-start', className)} aria-label="RISE agent pipeline">
        {resolved.map((stage, i) => (
          <li key={stage.key} className={cn('flex flex-col items-center', i < last && 'flex-1')}>
            <div className="flex w-full items-center">
              <StageMarker state={stage.state} className="mx-auto" />
              {i < last && <span className={cn('h-px flex-1', connectorClass(stage.state))} />}
            </div>
            <span
              className={cn(
                tx('cardMeta'),
                'mt-1.5 text-center',
                stage.state === 'active' ? 'text-cream font-semibold' : 'text-warm-grey-600',
              )}
            >
              {stage.label}
            </span>
          </li>
        ))}
      </ol>
    );
  }

  return (
    <ol className={cn('flex flex-col', className)} aria-label="RISE agent pipeline">
      {resolved.map((stage, i) => (
        <li key={stage.key} className="flex gap-3">
          <div className="flex flex-col items-center">
            <StageMarker state={stage.state} />
            {i < last && <span className={cn('my-1 min-h-[16px] w-px flex-1', connectorClass(stage.state))} aria-hidden />}
          </div>
          <div className={cn('pt-0.5', i < last && 'pb-3')}>
            <span
              className={cn(
                tx('cardMeta'),
                stage.state === 'active' ? 'text-cream font-semibold' : stage.state === 'complete' ? 'text-warm-grey-100' : 'text-warm-grey-600',
              )}
            >
              {stage.label}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}
