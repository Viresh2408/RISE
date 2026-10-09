import React from 'react';
import { cn } from '../../lib/cn';
import { tx } from '../../lib/typography';
import { resolveConfidence, type ConfidenceBand } from './tokens';

/**
 * Linear confidence indicator. Same honesty contract as {@link ConfidenceRing}:
 * a not-computed score renders an empty track labelled "Not computed" rather
 * than a fabricated fill; a real 0 renders an empty (0%) bar, not a default.
 */
const BAND_BG: Record<ConfidenceBand, string> = {
  high: 'bg-status-approved',
  medium: 'bg-amber-accent',
  low: 'bg-sev2',
  none: 'bg-warm-grey-700',
};

const BAND_TEXT: Record<ConfidenceBand, string> = {
  high: 'text-status-approved',
  medium: 'text-amber-accent',
  low: 'text-sev2',
  none: 'text-warm-grey-600',
};

export interface ConfidenceBarProps {
  value: number | null | undefined;
  scale?: 1 | 100;
  /** Show the numeric/"Not computed" label above the track. */
  showValue?: boolean;
  /** Optional caption to the left of the value (e.g. "Root-cause confidence"). */
  label?: string;
  className?: string;
}

export function ConfidenceBar({
  value,
  scale = 1,
  showValue = true,
  label,
  className,
}: ConfidenceBarProps) {
  const resolved = resolveConfidence(value, scale);

  return (
    <div className={cn('w-full', className)}>
      {(showValue || label) && (
        <div className="mb-1.5 flex items-baseline justify-between gap-2">
          {label && <span className={tx('cardMeta', 'text-warm-grey-100')}>{label}</span>}
          {showValue && (
            <span className={cn('tabular-nums font-medium', BAND_TEXT[resolved.band])}>
              {resolved.label}
            </span>
          )}
        </div>
      )}
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-warm-grey-700/40"
        role="meter"
        aria-valuenow={resolved.percent ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Confidence: ${resolved.label}`}
      >
        {resolved.state === 'computed' && (
          <div
            className={cn('h-full rounded-full transition-[width] duration-slow ease-out-expo', BAND_BG[resolved.band])}
            style={{ width: `${resolved.percent}%` }}
          />
        )}
      </div>
    </div>
  );
}
